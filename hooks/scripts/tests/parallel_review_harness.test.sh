#!/bin/bash
# Behavioural test for hooks/scripts/lib/parallel_review_harness.sh — the
# cross-script wiring proof (fan-out -> dual-write -> join) for
# design/mixed-provider-review-contract (frozen commit 0c7b4639).
#
# This is the explicit regression test for the "caller passes matching
# run_id/revision/head triples across calls" assumption
# (parallel_review_join.sh's own disclosed ceiling): it runs the harness
# end-to-end with real files and asserts the intermediate records all carry
# the identical provenance triple/digest, not just that the final outcome
# is "pass".
set -u

TESTS_DIR="$(cd "$(dirname "$0")" && pwd)"
LIB_DIR="$(cd "$TESTS_DIR/../lib" && pwd)"
. "$LIB_DIR/parallel_review_harness.sh"

fails=0

ok() { printf 'ok   - %s\n' "$1"; }
fail() { printf 'FAIL - %s\n      %s\n' "$1" "$2"; fails=$((fails+1)); }

check() { # desc expected actual
  if [ "$2" = "$3" ]; then ok "$1"; else fail "$1" "expected: $2 / actual: $3"; fi
}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

RUN_ID="run-1"
REVISION="abc123"
HEAD_SHA="deadbeef"
NODE="J4b-review[0]"

ARTIFACT="$TMP/frozen_input.txt"
printf 'frozen stage artifact contents\n' > "$ARTIFACT"
EXPECTED_DIGEST=$(shasum -a 256 "$ARTIFACT" | awk '{print $1}')

WORK_DIR="$TMP/work"
OUTPUT=$(parallel_review_harness::run_pass_case "$ARTIFACT" "$RUN_ID" "$REVISION" "$HEAD_SHA" "$NODE" "$WORK_DIR")
rc=$?

check "harness: exits 0" 0 "$rc"
check "harness: prints pass outcome" "pass" "$OUTPUT"

JOIN_OUT="$WORK_DIR/join.json"
check "harness: join record outcome is pass" "pass" "$(jq -r '.outcome' "$JOIN_OUT")"
check "harness: join record hard_stop_reason is null" "null" "$(jq -r '.hard_stop_reason' "$JOIN_OUT")"

# ─── matching-triples regression: canonical.json, claude.json, codex.json
# all carry the identical provenance the caller passed in ────────────────
CANONICAL="$WORK_DIR/canonical.json"
CLAUDE="$WORK_DIR/claude.json"
CODEX="$WORK_DIR/codex.json"

check "harness: canonical.json digest matches independently computed sha256" "$EXPECTED_DIGEST" "$(jq -r '.digest' "$CANONICAL")"

check "harness: claude.json run_id matches caller-supplied run_id" "$RUN_ID" "$(jq -r '.run_id' "$CLAUDE")"
check "harness: claude.json revision matches caller-supplied revision" "$REVISION" "$(jq -r '.revision' "$CLAUDE")"
check "harness: claude.json head matches caller-supplied head" "$HEAD_SHA" "$(jq -r '.head' "$CLAUDE")"
check "harness: claude.json frozen_input_digest matches canonical digest" "$EXPECTED_DIGEST" "$(jq -r '.frozen_input_digest' "$CLAUDE")"

check "harness: codex.json run_id matches caller-supplied run_id" "$RUN_ID" "$(jq -r '.run_id' "$CODEX")"
check "harness: codex.json revision matches caller-supplied revision" "$REVISION" "$(jq -r '.revision' "$CODEX")"
check "harness: codex.json head matches caller-supplied head" "$HEAD_SHA" "$(jq -r '.head' "$CODEX")"
check "harness: codex.json frozen_input_digest matches canonical digest" "$EXPECTED_DIGEST" "$(jq -r '.frozen_input_digest' "$CODEX")"

# claude.json and codex.json triples must be identical to each other too,
# not just each independently matching the caller's values.
check "harness: claude/codex run_id identical" "$(jq -r '.run_id' "$CLAUDE")" "$(jq -r '.run_id' "$CODEX")"
check "harness: claude/codex revision identical" "$(jq -r '.revision' "$CLAUDE")" "$(jq -r '.revision' "$CODEX")"
check "harness: claude/codex head identical" "$(jq -r '.head' "$CLAUDE")" "$(jq -r '.head' "$CODEX")"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
