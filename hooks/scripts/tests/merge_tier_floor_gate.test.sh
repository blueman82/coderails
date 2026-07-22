#!/bin/bash
# Integration tests for the derived tier-floor gate as wired into
# scripts/merge.sh — not the library in isolation (that is
# tier_floor.test.sh), but proof that a below-floor claim actually ABORTS a
# merge, and that the abort happens BEFORE `gh pr merge` runs.
#
# A gate whose deny path has never fired end-to-end is unproven, so the
# central assertions here are: (a) merge.sh exits non-zero, and (b) the merge
# command was never invoked — checked via a sentinel file the gh stub writes
# only when `pr merge` is actually reached.
#
# Mirrors merge_tier_review_gate.test.sh's stub-dir/wrapper technique.
set -u

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
MERGE_SH="$REPO_ROOT/scripts/merge.sh"
TMP=$(mktemp -d)
trap 'chmod -R u+w "$TMP" 2>/dev/null; rm -rf "$TMP" 2>/dev/null || true' EXIT

fails=0
check() { # desc expected actual
  if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected: %s\n  actual:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}
check_msg() { # desc pattern output
  if echo "$3" | grep -qF "$2"; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected pattern: %s\n  actual output:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

STUB_DIR="$TMP/stubs"
mkdir -p "$STUB_DIR/lib"
MERGE_SENTINEL="$TMP/merge_was_called"

# No tier_review.machine_user — the tier-review status gate stays INACTIVE
# here on purpose. That is the default-install shape, and it is exactly the
# configuration in which the tier floor is the only diff-derived check
# standing between a self-declared tier and a merge.
printf 'project: my-project\n' > "$TMP/fake-config.yaml"
cat > "$STUB_DIR/lib/config.sh" <<CONFIGSTUB
#!/bin/bash
coderails::config_path() { echo "$TMP/fake-config.yaml"; }
coderails::resolve_config() { cat "$TMP/fake-config.yaml" 2>/dev/null || echo "NO_CONFIG"; }
CONFIGSTUB

cat > "$STUB_DIR/lib/git-common-base.sh" <<'BASELIB'
#!/bin/bash
readonly C_RED='' C_GRN='' C_YLW='' C_BLU='' C_DIM='' C_BLD='' C_RST='' 2>/dev/null || true
info() { :; }; ok() { :; }; warn() { printf '%s\n' "$1" >&2; }; dim() { :; }
step() { :; }; banner() { :; }
err() { printf '%s\n' "$1" >&2; exit 1; }
branch() { echo "feature/test"; }
dirty() { return 1; }; clean() { return 0; }; main() { echo "main"; }
repo() { echo "test-owner/test-repo"; }
protected() { return 1; }
sync::main_branch() { return 0; }
require::feature() { return 0; }; require::clean() { return 0; }; require::repo() { return 0; }
pr::num() { echo "42"; }
pr::url() { echo "https://github.com/test-owner/test-repo/pull/42"; }
pr::state() { echo "OPEN"; }; pr::title() { echo "Test PR"; }
pr::review() { echo "APPROVED"; }; pr::exists() { return 0; }
BASELIB

# gh stub. MOCK_FILELIST / MOCK_LINES drive the tier-floor gate's two reads;
# MOCK_DIFF_FAIL makes the `pr diff` fetch itself exit non-zero, which is the
# INFRASTRUCTURE case (must not block). Reaching `pr merge` writes a sentinel
# so a test can prove the gate aborted before the merge, not after it.
cat > "$STUB_DIR/gh" <<GHSTUB
#!/bin/bash
case "\$*" in
  *"pr merge"*) touch "$MERGE_SENTINEL"; exit 0 ;;
  *"pr diff "*"--name-only"*)
    [ -n "\${MOCK_DIFF_FAIL:-}" ] && exit 1
    printf '%s' "\${MOCK_FILELIST:-}"
    ;;
  *"pr view "*"additions"*) printf '%s\n' "\${MOCK_LINES:-0}" ;;
  *"pr view "*"headRefName"*) printf '{"headRefName":"feature/test"}\n' ;;
  *"api repos/"*"/commits/"*"/statuses"*) printf '[]' ;;
  *) exit 0 ;;
esac
GHSTUB
chmod +x "$STUB_DIR/gh"

cat > "$STUB_DIR/git" <<'GITSTUB'
#!/bin/bash
case "$*" in
  *"push origin --delete"*) exit 0 ;;
  *"branch -D"*) exit 0 ;;
  *) exec /usr/bin/git "$@" ;;
esac
GITSTUB
chmod +x "$STUB_DIR/git"

# run_floor_test <claimed_tier> <filelist> <line_count> [diff_fail]
run_floor_test() {
    local claimed_tier="$1" filelist="$2" lines="$3" diff_fail="${4:-}"
    rm -f "$MERGE_SENTINEL"

    cat > "$STUB_DIR/lib/git-common.sh" <<GCSTUB
#!/bin/bash
source "$STUB_DIR/lib/git-common-base.sh"
pr::head_sha() { echo "deadbeef"; }
pr::has_coderails_review_for_head() { return 0; }
pr::has_coderails_eval_for_head() { PR_EVAL_TIER="${claimed_tier}"; return 0; }
GCSTUB

    local wrapper="$STUB_DIR/merge_test.sh"
    cat > "$wrapper" <<WRAPPER
#!/bin/bash
set -euo pipefail
_DIR="\$(dirname "\${BASH_SOURCE[0]}")"
source "\$_DIR/lib/git-common.sh"
source "\$_DIR/lib/config.sh"
source "$REPO_ROOT/scripts/lib/tier-floor.sh"
WRAPPER
    awk '
        NR==1 { next }
        /^source.*git-common/ { next }
        /^source.*config/ { next }
        /^source.*tier-floor/ { next }
        { print }
    ' "$MERGE_SH" >> "$wrapper"

    (
        export PATH="$STUB_DIR:$PATH"
        export MOCK_FILELIST="$filelist"
        export MOCK_LINES="$lines"
        [[ -n "$diff_fail" ]] && export MOCK_DIFF_FAIL=1
        bash "$wrapper" 42 2>"$TMP/stderr" >"$TMP/stdout"
    )
    local rc=$?
    LAST_STDERR=$(cat "$TMP/stderr" 2>/dev/null || true)
    return $rc
}

merge_reached() { [[ -f "$MERGE_SENTINEL" ]] && echo yes || echo no; }

# ══════════════════════════════════════════════════════════════════════════
# The deny path — a self-declared tier below the diff-derived floor.
# ══════════════════════════════════════════════════════════════════════════

# A tier-1 claim on a sweeping diff. This is the shape of the lie that was
# demonstrated live: the actor writes a modest tier into its own artifact
# while the change is an order of magnitude larger than the honest band.
rc=0; run_floor_test 1 $'AGENTS.md\nREADME.md\nc\nd\ne\nf\ng\nh\ni\nj' 1146 || rc=$?
check "tier-1 claim on a 10-file/1146-line diff aborts the merge" "1" "$rc"
check "the merge command was never reached" "no" "$(merge_reached)"
check_msg "abort names the claimed tier" "claimed tier 1" "$LAST_STDERR"
check_msg "abort names the derived floor" "floor 2" "$LAST_STDERR"

# A tier-0 claim on the enforcement machinery. Small diff, ordinary size —
# only the PATH forces the floor, so this proves the path predicate reaches
# merge.sh and is not shadowed by the size caps.
rc=0; run_floor_test 0 'hooks/scripts/enforce_pr_workflow.sh' 2 || rc=$?
check "tier-0 claim touching hooks/scripts/ aborts the merge" "1" "$rc"
check "the merge command was never reached (infra path)" "no" "$(merge_reached)"
check_msg "abort names the offending path" "enforce_pr_workflow.sh" "$LAST_STDERR"

# A sub-tier-2 claim on the gate's own source — automation editing its leash.
rc=0; run_floor_test 1 'scripts/tier-gate/tier-gate-runner.sh' 4 || rc=$?
check "tier-1 claim editing the gate's own source aborts the merge" "1" "$rc"
check "the merge command was never reached (gate source)" "no" "$(merge_reached)"

# A tier-0 claim on an oversize single-file diff.
rc=0; run_floor_test 0 'docs/REFERENCE.md' 205 || rc=$?
check "tier-0 claim on a 205-line diff aborts the merge" "1" "$rc"

# ══════════════════════════════════════════════════════════════════════════
# Fail-closed on evidence: the fetch SUCCEEDED but returned nothing usable.
# Every count derived from an empty list is zero, which clears every size cap
# vacuously — so this must block, not pass.
# ══════════════════════════════════════════════════════════════════════════
rc=0; run_floor_test 0 '' 0 || rc=$?
check "an empty changed-file list aborts the merge (fail-closed)" "1" "$rc"
check "the merge command was never reached (empty filelist)" "no" "$(merge_reached)"
check_msg "abort names the evidence as unusable" "unusable evidence" "$LAST_STDERR"

# ══════════════════════════════════════════════════════════════════════════
# Fail-open on infrastructure: the fetch command itself failed. There is no
# evidence either way, so the floor does not block — the eval, review and
# tier-review gates still stand.
# ══════════════════════════════════════════════════════════════════════════
rc=0; run_floor_test 0 '' 0 fail || rc=$?
check "a failed diff fetch does NOT block the merge (fail-open on infra)" "0" "$rc"
check "the merge command WAS reached on an infra failure" "yes" "$(merge_reached)"
check_msg "the skipped evaluation is reported, not silent" "infrastructure failure" "$LAST_STDERR"

# ══════════════════════════════════════════════════════════════════════════
# The allow path — an honest claim must still merge, or the gate is useless.
# ══════════════════════════════════════════════════════════════════════════
rc=0; run_floor_test 0 'docs/REFERENCE.md' 2 || rc=$?
check "an honest tier-0 claim on a tiny docs diff merges" "0" "$rc"
check "the merge command WAS reached on the honest claim" "yes" "$(merge_reached)"

rc=0; run_floor_test 1 'hooks/scripts/enforce_pr_workflow.sh' 40 || rc=$?
check "an honest tier-1 claim on an infra path merges" "0" "$rc"
check "the merge command WAS reached (honest tier-1 infra)" "yes" "$(merge_reached)"

# Claiming ABOVE the floor is never an attack and must never be blocked.
rc=0; run_floor_test 2 'docs/REFERENCE.md' 2 || rc=$?
check "a tier-2 claim on a floor-0 diff merges (over-claiming is allowed)" "0" "$rc"

printf '\n'
if [[ $fails -eq 0 ]]; then printf 'PASS\n'; exit 0; fi
printf 'FAIL (%s)\n' "$fails"; exit 1
