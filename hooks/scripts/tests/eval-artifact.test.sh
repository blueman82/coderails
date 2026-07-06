#!/bin/bash
# Behavioural tests for scripts/lib/eval-artifact.sh
# Verifies marker SSOT: exact prefix+suffix grammar matching, not substring
# grep, plus the shared GO-computation function.
set -u
LIB="$(cd "$(dirname "$0")/../../.." && pwd)/scripts/lib/eval-artifact.sh"
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
MARKER=$(eval_artifact::marker 123 abc GO 1)
check_str "marker produces exact literal" \
  "<!-- coderails-eval-summary v1 pr=123 head_sha=abc result=GO tier=1 -->" \
  "$MARKER"

# ─── matches_marker: exact match at GO/tier=1 → exit 0 ───────────────────────
eval_artifact::matches_marker "$MARKER" 123 abc
check "matches_marker: exact marker → exit 0" 0 $?

# ─── matches_marker only asserts pr+sha identity, not result/tier ────────────
NOGO_LINE="<!-- coderails-eval-summary v1 pr=123 head_sha=abc result=NO-GO tier=0 -->"
eval_artifact::matches_marker "$NOGO_LINE" 123 abc
check "matches_marker: same pr/sha, different result/tier → still exit 0" 0 $?

# ─── wrong PR number → exit 1 ────────────────────────────────────────────────
eval_artifact::matches_marker "$MARKER" 999 abc
check "matches_marker: wrong pr → exit 1" 1 $?

# ─── wrong SHA → exit 1 ──────────────────────────────────────────────────────
eval_artifact::matches_marker "$MARKER" 123 wrongsha
check "matches_marker: wrong sha → exit 1" 1 $?

# ─── v2 marker line → exit 1 (fail-closed on unknown version) ────────────────
V2_LINE="<!-- coderails-eval-summary v2 pr=123 head_sha=abc result=GO tier=1 -->"
eval_artifact::matches_marker "$V2_LINE" 123 abc
check "matches_marker: v2 marker → exit 1 (unknown version fail-closed)" 1 $?

# ─── truncated line (missing trailing ' -->') → exit 1 ───────────────────────
TRUNCATED="<!-- coderails-eval-summary v1 pr=123 head_sha=abc result=GO tier=1"
eval_artifact::matches_marker "$TRUNCATED" 123 abc
check "matches_marker: missing trailing ' -->' → exit 1" 1 $?

# ─── junk-wrapped exact marker → exit 1 (proves exact anchoring, not substring) ──
JUNK_WRAPPED="junk $MARKER junk"
eval_artifact::matches_marker "$JUNK_WRAPPED" 123 abc
check "matches_marker: junk-wrapped marker → exit 1 (exact anchoring, not substring)" 1 $?

# ─── invalid result value → exit 1 (grammar violation) ───────────────────────
INVALID_RESULT="<!-- coderails-eval-summary v1 pr=123 head_sha=abc result=MAYBE tier=1 -->"
eval_artifact::matches_marker "$INVALID_RESULT" 123 abc
check "matches_marker: invalid result value → exit 1" 1 $?

# ─── invalid tier digit (3) → exit 1 (boundary: grammar only allows 0-2) ─────
INVALID_TIER="<!-- coderails-eval-summary v1 pr=123 head_sha=abc result=GO tier=3 -->"
eval_artifact::matches_marker "$INVALID_TIER" 123 abc
check "matches_marker: tier digit 3 → exit 1 (grammar boundary)" 1 $?

# ─── lowercase result casing ("go") → exit 1 (grammar is case-sensitive) ─────
LOWERCASE_RESULT="<!-- coderails-eval-summary v1 pr=123 head_sha=abc result=go tier=1 -->"
eval_artifact::matches_marker "$LOWERCASE_RESULT" 123 abc
check "matches_marker: lowercase 'go' not accepted as GO → exit 1" 1 $?

# ─── literal string-equality matching, not regex: pr/sha carrying regex ──────
# metacharacters must be matched LITERALLY, not interpreted as a pattern. A
# hardened implementation builds the expected marker prefix for (pr, head_sha)
# and compares literally — never regex with interpolated pr/sha values.
REGEX_JUNK_PR='1|.*'
eval_artifact::matches_marker "$MARKER" "$REGEX_JUNK_PR" abc
check "matches_marker: pr containing regex metacharacters never matches unrelated marker" 1 $?

# A line whose body literally contains regex-metacharacter junk shaped like a
# pr value must not spuriously match a real numeric pr via pattern semantics.
JUNK_PR_LINE="<!-- coderails-eval-summary v1 pr=1|.* head_sha=abc result=GO tier=1 -->"
eval_artifact::matches_marker "$JUNK_PR_LINE" 123 abc
check "matches_marker: regex-metacharacter-shaped pr in line body doesn't match a different pr" 1 $?
eval_artifact::matches_marker "$JUNK_PR_LINE" "$REGEX_JUNK_PR" abc
check "matches_marker: regex-metacharacter-shaped pr matches literally when equal" 0 $?

# ─── junk-wrapped/prefixed marker lines still rejected (literal equality) ────
PREFIXED="not a marker but has: $MARKER"
eval_artifact::matches_marker "$PREFIXED" 123 abc
check "matches_marker: prefixed marker line → exit 1 (literal equality, not substring)" 1 $?

# ─── parse_result / parse_tier ────────────────────────────────────────────────
GO_TIER2=$(eval_artifact::marker 5 shaX GO 2)
check_str "parse_result: matched GO line → GO" "GO" "$(eval_artifact::parse_result "$GO_TIER2")"
check_str "parse_tier: matched tier=2 line → 2" "2" "$(eval_artifact::parse_tier "$GO_TIER2")"

NOGO_TIER0=$(eval_artifact::marker 5 shaX NO-GO 0)
check_str "parse_result: matched NO-GO line → NO-GO" "NO-GO" "$(eval_artifact::parse_result "$NOGO_TIER0")"
check_str "parse_tier: matched tier=0 line → 0" "0" "$(eval_artifact::parse_tier "$NOGO_TIER0")"

check_str "parse_result: unmatched/junk line → empty" "" "$(eval_artifact::parse_result "not a marker")"
check_str "parse_tier: unmatched/junk line → empty" "" "$(eval_artifact::parse_tier "not a marker")"

# ─── compute_go ────────────────────────────────────────────────────────────────
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

# (a) all P0 pass, some P1 fail → GO (exit 0)
FIX_A="$TMP/a.json"
jq -n '{evals: [
  {id:"e1", priority:"P0", status:"pass"},
  {id:"e2", priority:"P1", status:"fail"}
]}' > "$FIX_A"
eval_artifact::compute_go "$FIX_A"
check "compute_go: all P0 pass, P1 fail → exit 0 (GO)" 0 $?

# (b) one P0 fails → NO-GO (exit 1)
FIX_B="$TMP/b.json"
jq -n '{evals: [
  {id:"e1", priority:"P0", status:"fail"},
  {id:"e2", priority:"P1", status:"pass"}
]}' > "$FIX_B"
eval_artifact::compute_go "$FIX_B"
check "compute_go: one P0 fails → exit 1 (NO-GO)" 1 $?

# (c) malformed JSON → exit 1 (fail-closed)
FIX_C="$TMP/c.json"
printf 'NOT JSON {{{' > "$FIX_C"
eval_artifact::compute_go "$FIX_C"
check "compute_go: malformed JSON → exit 1 (fail-closed)" 1 $?

# (d) valid JSON but .evals absent → exit 1 (fail-closed)
FIX_D="$TMP/d.json"
jq -n '{schema_version: 1}' > "$FIX_D"
eval_artifact::compute_go "$FIX_D"
check "compute_go: missing .evals array → exit 1 (fail-closed)" 1 $?

# (e) .evals present but empty → exit 0 (vacuously GO)
FIX_E="$TMP/e.json"
jq -n '{evals: []}' > "$FIX_E"
eval_artifact::compute_go "$FIX_E"
check "compute_go: empty evals array → exit 0 (vacuous GO)" 0 $?

[[ $fails -eq 0 ]] && { echo PASS; exit 0; } || { echo "FAIL ($fails)"; exit 1; }
