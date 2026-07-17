#!/bin/bash
# Behavioural tests for the tier-review gate in scripts/merge.sh — the
# redundant local defence-in-depth layer inserted directly after the existing
# eval-artifact gate. Active only when the eval artifact's tier is 0 AND
# config key tier_review.machine_user is set; otherwise inactive (skip).
# Mirrors merge_evals_gate.test.sh's stub-dir/wrapper technique, additionally
# stubbing `gh api .../statuses` (this gate reads the raw GitHub statuses API,
# not a git-common.sh pr::* helper) and coderails::config_path/resolve_config
# to control whether tier_review.machine_user is configured.
set -u

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
MERGE_SH="$REPO_ROOT/scripts/merge.sh"
TMP=$(mktemp -d)
trap 'chmod -R u+w "$TMP" 2>/dev/null; find "$TMP" -maxdepth 3 -type f -delete 2>/dev/null; rmdir "$TMP"/* "$TMP" 2>/dev/null || true' EXIT

fails=0

check() { # desc expected_exit actual_exit
  if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected exit: %s\n  actual exit:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

check_msg() { # desc pattern output
  if echo "$3" | grep -qF "$2"; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected pattern: %s\n  actual output:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# ─── Build a stub dir that merge.sh will source ──────────────────────────────
STUB_DIR="$TMP/stubs"
mkdir -p "$STUB_DIR/lib"

MACHINE_USER="coderails-tier-bot"

# Stub config.sh — CONFIG_MACHINE_USER (set per-test below via env before the
# wrapper runs) controls whether tier_review.machine_user resolves to a value
# or is absent (empty -> gate inactive).
cat > "$STUB_DIR/lib/config.sh" <<CONFIGSTUB
#!/bin/bash
coderails::config_path() { echo "$TMP/fake-config.yaml"; }
coderails::resolve_config() { cat "$TMP/fake-config.yaml" 2>/dev/null || echo "NO_CONFIG"; }
CONFIGSTUB

# Stub git-common.sh base (always constant)
cat > "$STUB_DIR/lib/git-common-base.sh" <<'BASELIB'
#!/bin/bash
readonly C_RED='' C_GRN='' C_YLW='' C_BLU='' C_DIM='' C_BLD='' C_RST='' 2>/dev/null || true
info()    { :; }
ok()      { :; }
warn()    { :; }
err()     { printf '%s\n' "$1" >&2; exit 1; }
dim()     { :; }
step()    { :; }
banner()  { :; }

branch()  { echo "feature/test"; }
dirty()   { return 1; }
clean()   { return 0; }
main()    { echo "main"; }

repo()    { echo "test-owner/test-repo"; }
protected() { return 1; }
sync::main_branch() { return 0; }

require::feature() { return 0; }
require::clean()   { return 0; }
require::repo()    { return 0; }

pr::num()    { echo "42"; }
pr::url()    { echo "https://github.com/test-owner/test-repo/pull/42"; }
pr::state()  { echo "OPEN"; }
pr::title()  { echo "Test PR"; }
pr::review() { echo "APPROVED"; }
pr::exists() { return 0; }
BASELIB

# Stub gh: `pr merge` / branch-delete plumbing always succeeds; the tier-review
# statuses lookup is driven by MOCK_STATUSES_JSON / MOCK_STATUSES_FAIL env vars
# set per-test.
cat > "$STUB_DIR/gh" <<'GHSTUB'
#!/bin/bash
case "$*" in
  *"pr merge"*) exit 0 ;;
  *"pr view "*"headRefName"*) printf '{"headRefName":"feature/test"}\n' ;;
  *"api repos/"*"/commits/"*"/statuses"*)
    [ -n "${MOCK_STATUSES_FAIL:-}" ] && exit 1
    printf '%s' "${MOCK_STATUSES_JSON:-[]}"
    ;;
  *) exit 0 ;;
esac
GHSTUB
chmod +x "$STUB_DIR/gh"

# git stub: branch push --delete should silently succeed
cat > "$STUB_DIR/git" <<'GITSTUB'
#!/bin/bash
case "$*" in
  *"push origin --delete"*) exit 0 ;;
  *"branch -D"*) exit 0 ;;
  *) exec /usr/bin/git "$@" ;;
esac
GITSTUB
chmod +x "$STUB_DIR/git"

# run_tier_gate_test: <eval_tier> <config_machine_user> <statuses_json> [statuses_fail]
# review + eval gates are always stubbed to pass; only the new tier-review
# gate's behaviour varies.
run_tier_gate_test() {
    local eval_tier="$1" config_mu="$2" statuses_json="$3" statuses_fail="${4:-}"
    local stderr_file="$TMP/stderr_run"
    local stdout_file="$TMP/stdout_run"

    if [[ -n "$config_mu" ]]; then
        printf 'tier_review:\n  machine_user: %s\n' "$config_mu" > "$TMP/fake-config.yaml"
    else
        printf 'project: my-project\n' > "$TMP/fake-config.yaml"
    fi

    cat > "$STUB_DIR/lib/git-common.sh" <<GCSTUB
#!/bin/bash
source "$STUB_DIR/lib/git-common-base.sh"

pr::head_sha() {
    echo "deadbeef"
}

pr::has_coderails_review_for_head() {
    return 0
}

pr::has_coderails_eval_for_head() {
    PR_EVAL_TIER="${eval_tier}"
    return 0
}
GCSTUB

    local wrapper="$STUB_DIR/merge_test.sh"
    cat > "$wrapper" <<WRAPPER
#!/bin/bash
set -euo pipefail
_DIR="\$(dirname "\${BASH_SOURCE[0]}")"
source "\$_DIR/lib/git-common.sh"
source "\$_DIR/lib/config.sh"
WRAPPER
    awk '
        NR==1 { next }
        /^source.*git-common/ { next }
        /^source.*config/ { next }
        { print }
    ' "$MERGE_SH" >> "$wrapper"

    (
        export PATH="$STUB_DIR:$PATH"
        export MOCK_STATUSES_JSON="$statuses_json"
        [[ -n "$statuses_fail" ]] && export MOCK_STATUSES_FAIL=1
        bash "$wrapper" 42 2>"$stderr_file" >"$stdout_file"
    )
    local rc=$?
    LAST_STDERR=$(cat "$stderr_file" 2>/dev/null || true)
    LAST_STDOUT=$(cat "$stdout_file" 2>/dev/null || true)
    return $rc
}

SUCCESS_RIGHT_CREATOR="[{\"state\":\"success\",\"creator\":{\"login\":\"${MACHINE_USER}\"}}]"
SUCCESS_WRONG_CREATOR="[{\"state\":\"success\",\"creator\":{\"login\":\"repo-owner\"}}]"
ERROR_STATUS="[{\"state\":\"error\",\"creator\":{\"login\":\"${MACHINE_USER}\"}}]"
PENDING_STATUS="[{\"state\":\"pending\",\"creator\":{\"login\":\"${MACHINE_USER}\"}}]"

# ─── Test 1: tier=0, config set, no status at all -> block ───────────────────
run_tier_gate_test 0 "$MACHINE_USER" "[]"
rc=$?
check "tier-review gate blocks when no status exists (tier=0, configured)" 1 $rc
check_msg "block message mentions tier-review" "tier-review" "$LAST_STDERR"

# ─── Test 2: tier=0, config set, success + WRONG creator -> block ────────────
# Load-bearing: the whole design turns on creator attribution, not just state.
run_tier_gate_test 0 "$MACHINE_USER" "$SUCCESS_WRONG_CREATOR"
rc=$?
check "tier-review gate blocks on success with WRONG creator" 1 $rc
check_msg "wrong-creator block message names the misconfig/forgery framing" "creator" "$LAST_STDERR"

# ─── Test 3: tier=0, config set, success + RIGHT creator -> pass ─────────────
run_tier_gate_test 0 "$MACHINE_USER" "$SUCCESS_RIGHT_CREATOR"
rc=$?
check "tier-review gate passes on success with RIGHT creator" 0 $rc

# ─── Test 4: tier=0, config set, state=error -> block ────────────────────────
run_tier_gate_test 0 "$MACHINE_USER" "$ERROR_STATUS"
rc=$?
check "tier-review gate blocks on state=error" 1 $rc

# ─── Test 5: tier=0, config set, state=pending -> block ──────────────────────
run_tier_gate_test 0 "$MACHINE_USER" "$PENDING_STATUS"
rc=$?
check "tier-review gate blocks on state=pending" 1 $rc

# ─── Test 6: tier=0, config set, gh fetch fails -> block (fail-closed) ───────
run_tier_gate_test 0 "$MACHINE_USER" "" fail
rc=$?
check "tier-review gate blocks on gh fetch failure (fail-closed)" 1 $rc
check_msg "fetch-fail block message mentions fetch" "fetch" "$LAST_STDERR"

# ─── Test 7: tier != 0 -> gate inactive (skip), merge proceeds ───────────────
run_tier_gate_test 1 "$MACHINE_USER" "[]"
rc=$?
check "tier-review gate skips when tier != 0" 0 $rc

# ─── Test 8: tier=0, config key absent -> gate inactive, merge proceeds ──────
run_tier_gate_test 0 "" "[]"
rc=$?
check "tier-review gate inactive when config key absent" 0 $rc

[[ $fails -eq 0 ]] && { echo PASS; exit 0; } || { echo "FAIL ($fails)"; exit 1; }
