#!/bin/bash
# Behavioural tests for scripts/lib/review-artifact.sh
# Verifies marker SSOT: exact string equality, not substring grep.
set -u
LIB="$(cd "$(dirname "$0")/../../.." && pwd)/scripts/lib/review-artifact.sh"
source "$LIB"

fails=0

check() { # desc expected_exit actual_exit
  if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected exit: %s\n  actual exit:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

check_str() { # desc expected actual
  if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected: %s\n  actual:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# ─── marker output ───────────────────────────────────────────────────────────
MARKER=$(review_artifact::marker 123 abc)
check_str "marker produces exact literal" \
  "<!-- coderails-review-summary v1 pr=123 head_sha=abc -->" \
  "$MARKER"

# ─── matches_marker: exact match → exit 0 ────────────────────────────────────
review_artifact::matches_marker "$MARKER" 123 abc
check "matches_marker: exact marker → exit 0" 0 $?

# ─── wrong PR number → exit 1 ────────────────────────────────────────────────
review_artifact::matches_marker "$MARKER" 999 abc
check "matches_marker: wrong pr → exit 1" 1 $?

# ─── wrong SHA → exit 1 ──────────────────────────────────────────────────────
review_artifact::matches_marker "$MARKER" 123 wrongsha
check "matches_marker: wrong sha → exit 1" 1 $?

# ─── v2 marker line → exit 1 (fail-closed on unknown version) ────────────────
V2_LINE="<!-- coderails-review-summary v2 pr=123 head_sha=abc -->"
review_artifact::matches_marker "$V2_LINE" 123 abc
check "matches_marker: v2 marker → exit 1 (unknown version fail-closed)" 1 $?

# ─── missing trailing ' -->' → exit 1 ────────────────────────────────────────
TRUNCATED="<!-- coderails-review-summary v1 pr=123 head_sha=abc"
review_artifact::matches_marker "$TRUNCATED" 123 abc
check "matches_marker: missing trailing ' -->' → exit 1" 1 $?

# ─── junk prefix/suffix around exact marker → exit 1 (proves exact equality, not substring) ──
JUNK_WRAPPED="junk $MARKER junk"
review_artifact::matches_marker "$JUNK_WRAPPED" 123 abc
check "matches_marker: junk-wrapped marker → exit 1 (exact equality, not substring)" 1 $?

[[ $fails -eq 0 ]] && { echo PASS; exit 0; } || { echo "FAIL ($fails)"; exit 1; }
