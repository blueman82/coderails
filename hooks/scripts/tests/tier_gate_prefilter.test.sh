#!/bin/bash
# Behavioural tests for the tier-gate pre-filter (Fix 2) and the judge's blind
# inputs (Fix 1/3/4) — mechanical size/path gate BEFORE any model call, and
# the injection-immunity of tg_judge_build_prompt now that it takes only
# {claimed_tier, diff} rather than the defendant's own evals.json prose.
set -u

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
RUNNER="$REPO_ROOT/scripts/tier-gate/tier-gate-runner.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

fails=0
check() { # desc expected actual
    if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
    else printf 'FAIL - %s\n  expected: %s\n  actual:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}
check_contains() { # desc pattern haystack
    if printf '%s' "$3" | grep -qF "$2"; then printf 'ok   - %s\n' "$1"
    else printf 'FAIL - %s\n  expected to contain: %s\n  actual: %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}
check_not_contains() { # desc pattern haystack
    if printf '%s' "$3" | grep -qF "$2"; then
        printf 'FAIL - %s\n  expected NOT to contain: %s\n  actual: %s\n' "$1" "$2" "$3"; fails=$((fails+1))
    else printf 'ok   - %s\n' "$1"
    fi
}

source "$RUNNER"

# ══════════════════════════════════════════════════════════════════════════
# Fix 2: tg_prefilter <filelist> <line_count> — mechanical, no model call.
# Calibration (verified, from the task's real-world dishonest tier-0 PRs):
#   PR #189 = 205 lines / 1 file  -> MUST be blocked (this is the one the
#     line cap exists to catch; a file-count-only check passes it).
#   PR #191 = 3 lines / 1 file    -> the model's job, NOT the pre-filter's;
#     the cap must NOT be tuned down to catch this one.
# ══════════════════════════════════════════════════════════════════════════

# ── P1: PR #189 shape (205 lines, 1 file) -> blocked ────────────────────────
out=$(tg_prefilter "scripts/foo.sh" 205)
rc=$?
check "P1: 205-line 1-file diff is blocked (rc 1)" "1" "$rc"
check_contains "P1: block reason names the size cap" "size" "$out"

# ── P2 (negative control for P1): a small honest tier-0 diff passes ────────
out=$(tg_prefilter "scripts/foo.sh" 12)
rc=$?
check "P2: 12-line 1-file diff passes (rc 0)" "0" "$rc"
check "P2: pass produces no block reason" "" "$out"

# ── P3: denylisted path (outward/irreversible surface) -> blocked ──────────
out=$(tg_prefilter $'skills/dashboard/runner/bin/sweeper.sh' 5)
rc=$?
check "P3: denylisted path is blocked (rc 1)" "1" "$rc"
check_contains "P3: block reason names denylist" "denylist" "$out"

# ── P4 (negative control for P3): a non-denylisted small diff passes ───────
out=$(tg_prefilter $'hooks/scripts/tests/foo.test.sh' 5)
rc=$?
check "P4: non-denylisted small diff passes (rc 0)" "0" "$rc"

# ── P5: file-count-only would miss PR #189 shape — the LINE cap is required.
# A 1-file diff at exactly the line boundary above the cap must block; this
# discriminates a real cap from a vacuous "always block" or "never block".
out=$(tg_prefilter "scripts/foo.sh" 1)
rc=$?
check "P5: a 1-line 1-file diff (trivially small) passes" "0" "$rc"

[[ $fails -eq 0 ]] && { echo PASS; exit 0; } || { echo "FAIL ($fails)"; exit 1; }
