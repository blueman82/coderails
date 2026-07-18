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

# A GENUINE tier-0 approval carries verdict=legitimate in its description — only
# the real `legitimate` judgment posts that (tier-gate-runner tg_gate_pr). The
# gate now requires it: state=success + right creator is necessary but not
# sufficient (closes the verdict-laundering path where a non-judged/minted
# success is reused as a tier-0 pass).
SUCCESS_RIGHT_CREATOR="[{\"state\":\"success\",\"creator\":{\"login\":\"${MACHINE_USER}\"},\"description\":\"verdict=legitimate tier=0 host=h\"}]"
SUCCESS_WRONG_CREATOR="[{\"state\":\"success\",\"creator\":{\"login\":\"repo-owner\"},\"description\":\"verdict=legitimate tier=0 host=h\"}]"
# A success with the RIGHT creator but WITHOUT verdict=legitimate — the laundered
# / non-judged status an adversary would try to reuse. Must block.
SUCCESS_NO_VERDICT="[{\"state\":\"success\",\"creator\":{\"login\":\"${MACHINE_USER}\"},\"description\":\"verdict=not-tier-0 tier=0 host=h\"}]"
ERROR_STATUS="[{\"state\":\"error\",\"creator\":{\"login\":\"${MACHINE_USER}\"},\"description\":\"verdict=error tier=0 host=h\"}]"
PENDING_STATUS="[{\"state\":\"pending\",\"creator\":{\"login\":\"${MACHINE_USER}\"},\"description\":\"verdict=pending tier=0 host=h\"}]"
# Tier-1 fixtures — the gate is being hoisted to run at EVERY tier, and the
# posted status must carry a tier=N token matching the artifact's own claimed
# tier (PR_EVAL_TIER). These exercise that binding directly.
TIER1_LEGIT="[{\"state\":\"success\",\"creator\":{\"login\":\"${MACHINE_USER}\"},\"description\":\"verdict=legitimate tier=1 host=h\"}]"
TIER1_SELF_EDIT="[{\"state\":\"failure\",\"creator\":{\"login\":\"${MACHINE_USER}\"},\"description\":\"verdict=self_edit tier=1 host=h\"}]"
TIER1_INSUFFICIENT="[{\"state\":\"failure\",\"creator\":{\"login\":\"${MACHINE_USER}\"},\"description\":\"verdict=insufficient tier=1 host=h\"}]"
TIER1_ILLEGITIMATE="[{\"state\":\"failure\",\"creator\":{\"login\":\"${MACHINE_USER}\"},\"description\":\"verdict=illegitimate tier=1 host=h\"}]"
# Delimiter case: a tier=1 status must NOT satisfy a tier=12 claim (substring
# match without a delimiter would wrongly pass this).
TIER12_LEGIT="[{\"state\":\"success\",\"creator\":{\"login\":\"${MACHINE_USER}\"},\"description\":\"verdict=legitimate tier=12 host=h\"}]"
# Adjacent same-length-prefix delimiter case: a tier=1 status must NOT satisfy
# a tier=10 claim either — "tier=1" is a substring of "tier=10" too, distinct
# from the two-digit tier=12 case above (different digit count, same failure
# mode a naive unanchored match would miss).
TIER10_LEGIT="[{\"state\":\"success\",\"creator\":{\"login\":\"${MACHINE_USER}\"},\"description\":\"verdict=legitimate tier=10 host=h\"}]"
# Tier=2 fixture — the third and last legal tier value ([0-2]); tier=0 and
# tier=1 are both already exercised above, this closes the gap.
TIER2_LEGIT="[{\"state\":\"success\",\"creator\":{\"login\":\"${MACHINE_USER}\"},\"description\":\"verdict=legitimate tier=2 host=h\"}]"

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

# ─── Test 3: tier=0, success + RIGHT creator + verdict=legitimate -> pass ────
run_tier_gate_test 0 "$MACHINE_USER" "$SUCCESS_RIGHT_CREATOR"
rc=$?
check "tier-review gate passes on success with RIGHT creator + verdict=legitimate" 0 $rc

# ─── Test 3b: tier=0, success + RIGHT creator but NO verdict=legitimate -> block
# The verdict-laundering regression lock: a state=success by the machine user
# whose description is NOT verdict=legitimate (e.g. a minted/non-judged status)
# must NOT pass. Before the description check this passed (Test 3's old fixture
# had no description) — a bare state+creator match was the whole gate.
run_tier_gate_test 0 "$MACHINE_USER" "$SUCCESS_NO_VERDICT"
rc=$?
check "tier-review gate BLOCKS success+right-creator when description lacks verdict=legitimate" 1 $rc
check_msg "laundering block message names verdict=legitimate" "verdict=legitimate" "$LAST_STDERR"

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

# ─── Test 7: tier=1, config set, NO tier-review status -> BLOCK ──────────────
# The headline regression lock: the gate now runs at EVERY tier, not just
# tier=0. Before the hoist, a tier=1 PR with no tier-review status at all
# merged unimpeded — this must now block exactly like the tier=0 case.
run_tier_gate_test 1 "$MACHINE_USER" "[]"
rc=$?
check "tier-review gate BLOCKS at tier=1 with no status (was: skipped)" 1 $rc
check_msg "tier=1 no-status block message mentions tier-review" "tier-review" "$LAST_STDERR"

# ─── Test 8: tier=0, config key absent -> gate inactive, merge proceeds ──────
run_tier_gate_test 0 "" "[]"
rc=$?
check "tier-review gate inactive when config key absent" 0 $rc

# ─── Test 9: tier=1, config set, verdict=legitimate tier=1 -> ALLOW ──────────
run_tier_gate_test 1 "$MACHINE_USER" "$TIER1_LEGIT"
rc=$?
check "tier-review gate passes at tier=1 with matching verdict=legitimate tier=1" 0 $rc

# ─── Test 10: tier=1, status carries tier=0 token -> BLOCK (token mismatch) ──
# A tier-0 status must not satisfy a tier-1 claim — the anti-laundering bind.
run_tier_gate_test 1 "$MACHINE_USER" "$SUCCESS_RIGHT_CREATOR"
rc=$?
check "tier-review gate BLOCKS tier=1 claim satisfied by a tier=0 status" 1 $rc
check_msg "tier-mismatch block message mentions tier" "tier" "$LAST_STDERR"

# ─── Test 11: tier=0, status carries tier=1 token -> BLOCK (reverse direction)
run_tier_gate_test 0 "$MACHINE_USER" "$TIER1_LEGIT"
rc=$?
check "tier-review gate BLOCKS tier=0 claim satisfied by a tier=1 status (reverse)" 1 $rc

# ─── Test 12: tier=1, verdict=self_edit -> BLOCK ─────────────────────────────
run_tier_gate_test 1 "$MACHINE_USER" "$TIER1_SELF_EDIT"
rc=$?
check "tier-review gate blocks tier=1 verdict=self_edit" 1 $rc

# ─── Test 13: tier=1, verdict=insufficient -> BLOCK ──────────────────────────
run_tier_gate_test 1 "$MACHINE_USER" "$TIER1_INSUFFICIENT"
rc=$?
check "tier-review gate blocks tier=1 verdict=insufficient" 1 $rc

# ─── Test 14: tier=1, verdict=illegitimate -> BLOCK ──────────────────────────
run_tier_gate_test 1 "$MACHINE_USER" "$TIER1_ILLEGITIMATE"
rc=$?
check "tier-review gate blocks tier=1 verdict=illegitimate" 1 $rc

# ─── Test 15: tier=1, WRONG creator -> BLOCK (creator check must still apply
# at every tier, not just tier=0) ─────────────────────────────────────────────
run_tier_gate_test 1 "$MACHINE_USER" "$SUCCESS_WRONG_CREATOR"
rc=$?
check "tier-review gate blocks tier=1 with WRONG creator" 1 $rc
check_msg "tier=1 wrong-creator block message names the misconfig/forgery framing" "creator" "$LAST_STDERR"

# ─── Test 16: tier=1 claim, status token tier=12 -> BLOCK (delimiter case) ───
# A naive substring match ("tier=1" found inside "tier=12 host=h") would
# wrongly ALLOW here; only a delimited (space/EOL-bounded) match correctly
# BLOCKS. The reverse direction (claim=12, status tier=1) can't discriminate a
# buggy impl from a correct one — "tier=12" is never a substring of "tier=1
# host=h" either way — so it is deliberately not tested. tier=12 is only ever
# reachable as free text inside a status description, never as a real claimed
# tier (PR_EVAL_TIER is sourced from the eval-artifact marker, capped at 0-2).
run_tier_gate_test 1 "$MACHINE_USER" "$TIER12_LEGIT"
rc=$?
check "tier-review gate BLOCKS tier=1 claim satisfied by a tier=12 status (delimiter)" 1 $rc

# ─── Test 17: tier=1 claim, status token tier=10 -> BLOCK (adjacent digit) ───
# Same failure mode as Test 16 but with a different digit count: "tier=1" is
# also a substring of "tier=10 host=h". A naive substring match would wrongly
# ALLOW here too; only the delimited match correctly BLOCKS.
run_tier_gate_test 1 "$MACHINE_USER" "$TIER10_LEGIT"
rc=$?
check "tier-review gate BLOCKS tier=1 claim satisfied by a tier=10 status (adjacent digit)" 1 $rc

# ─── Test 18: tier=2 claim, matching verdict=legitimate tier=2 -> ALLOW ──────
# tier=2 is the third and last legal artifact tier ([0-2]); tier=0 and tier=1
# are both already exercised above (Tests 1-15), this closes the gap.
run_tier_gate_test 2 "$MACHINE_USER" "$TIER2_LEGIT"
rc=$?
check "tier-review gate passes at tier=2 with matching verdict=legitimate tier=2" 0 $rc

[[ $fails -eq 0 ]] && { echo PASS; exit 0; } || { echo "FAIL ($fails)"; exit 1; }
