#!/bin/bash
# Behavioural tests for the review-artifact gate in scripts/merge.sh.
# Stubs pr::head_sha and pr::has_coderails_review_for_head to test the
# three gate outcomes: proceed, no-artifact (block), gh-fetch-failed (block).
# Uses a wrapper that sources git-common.sh + config.sh from a stub dir so
# merge.sh's gate is exercised without real network calls.
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
# merge.sh does:
#   source "$(dirname "$0")/lib/git-common.sh"
#   source "$(dirname "$0")/lib/config.sh"
# We place a wrapper merge.sh in a stub bin dir and put stub libs alongside it.

STUB_DIR="$TMP/stubs"
mkdir -p "$STUB_DIR/lib"

# Stub config.sh
cat > "$STUB_DIR/lib/config.sh" <<'CONFIGSTUB'
#!/bin/bash
coderails::config_path() { echo ""; }
coderails::resolve_config() { echo "NO_CONFIG"; }
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

# Stub gh (for the post-merge branch-delete step)
cat > "$STUB_DIR/gh" <<'GHSTUB'
#!/bin/bash
case "$*" in
  *"pr merge"*) exit 0 ;;
  *"pr view"*"headRefName"*) printf '{"headRefName":"feature/test"}\n' ;;
  *) exit 0 ;;
esac
GHSTUB
chmod +x "$STUB_DIR/gh"

# git stub: branch push --delete should silently succeed
cat > "$STUB_DIR/git" <<'GITSTUB'
#!/bin/bash
# Only stub the push --delete call; pass everything else to real git
case "$*" in
  *"push origin --delete"*) exit 0 ;;
  *"branch -D"*) exit 0 ;;
  *) exec /usr/bin/git "$@" ;;
esac
GITSTUB
chmod +x "$STUB_DIR/git"

# Helper: run merge.sh with customised pr::head_sha and pr::has_coderails_review_for_head
# $1 = sha to return from pr::head_sha (empty string = simulate failure)
# $2 = exit code for pr::has_coderails_review_for_head
run_gate_test() {
    local sha_return="$1"
    local review_exit="$2"
    local stderr_file="$TMP/stderr_run"
    local stdout_file="$TMP/stdout_run"

    # Write a git-common.sh stub that includes the variable stubs
    cat > "$STUB_DIR/lib/git-common.sh" <<GCSTUB
#!/bin/bash
source "$STUB_DIR/lib/git-common-base.sh"

pr::head_sha() {
    echo "${sha_return}"
}

pr::has_coderails_review_for_head() {
    return ${review_exit}
}
GCSTUB

    # Write a merge wrapper that places our stub libs where merge.sh expects them
    local wrapper="$STUB_DIR/merge_test.sh"
    cat > "$wrapper" <<WRAPPER
#!/bin/bash
set -euo pipefail
_DIR="\$(dirname "\${BASH_SOURCE[0]}")"
source "\$_DIR/lib/git-common.sh"
source "\$_DIR/lib/config.sh"
WRAPPER
    # Append merge.sh body minus its shebang line and its two source lines
    # (which reference $(dirname "$0")/lib/... — we've already sourced our stubs)
    awk '
        NR==1 { next }               # skip shebang
        /^source.*git-common/ { next }  # skip original git-common source
        /^source.*config/ { next }      # skip original config source
        { print }
    ' "$MERGE_SH" >> "$wrapper"

    (
        export PATH="$STUB_DIR:$PATH"
        bash "$wrapper" 42 2>"$stderr_file" >"$stdout_file"
    )
    local rc=$?
    LAST_STDERR=$(cat "$stderr_file" 2>/dev/null || true)
    LAST_STDOUT=$(cat "$stdout_file" 2>/dev/null || true)
    return $rc
}

# ─── Test 1: artifact present → merge proceeds (exit 0) ──────────────────────
run_gate_test "deadbeef" 0
check "merge proceeds when has_coderails_review_for_head is true" 0 $?

# ─── Test 2: no matching artifact (review_exit=1) → merge aborts ─────────────
run_gate_test "deadbeef" 1
rc=$?
check "merge aborts when no artifact found (exit non-zero)" 1 $rc
check_msg "merge: no-artifact message mentions post-review" "post-review" "$LAST_STDERR"
check_msg "merge: no-artifact message mentions head sha" "deadbeef" "$LAST_STDERR"

# ─── Test 3: gh fetch failure (review_exit=2) → merge aborts with distinct message ──
run_gate_test "deadbeef" 2
rc=$?
check "merge aborts on gh fetch failure (exit non-zero)" 1 $rc
check_msg "merge: fetch-fail message mentions GitHub fetch" "GitHub fetch" "$LAST_STDERR"

# ─── Test 4: empty sha (pr::head_sha returns empty) → merge aborts ───────────
run_gate_test "" 1
rc=$?
check "merge aborts when head sha is empty" 1 $rc
check_msg "merge: empty-sha message mentions GitHub fetch" "GitHub fetch" "$LAST_STDERR"

# ─── Test 5: no progress.json fallback — review_exit=1 must still block ──────
# Even with review_exit=1 (no artifact on GitHub), no local file can override.
# This is structural: the test above already proves it; we assert it explicitly.
run_gate_test "deadbeef" 1
rc=$?
check "merge blocks (no fallback) even with no-artifact exit=1" 1 $rc

[[ $fails -eq 0 ]] && { echo PASS; exit 0; } || { echo "FAIL ($fails)"; exit 1; }
