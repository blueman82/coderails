#!/bin/bash
# shellcheck disable=SC1010,SC1091
set -u
TESTS_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$TESTS_DIR/../lib/parallel_review_join.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
ARTIFACT="$TMP/artifact.txt"
printf 'frozen stage artifact contents\n' >"$ARTIFACT"
REAL_DIGEST=$(shasum -a 256 "$ARTIFACT" | awk '{print $1}')
CANONICAL="$TMP/canonical.json"
RUN_ID=run-1
REVISION=abc123
HEAD_SHA=deadbeef
NODE='J4b-review[0]'
PARALLEL_REVIEW_DISPATCHER=orchestrator
export PARALLEL_REVIEW_DISPATCHER
parallel_review_fanout::write_digest "$ARTIFACT" "$RUN_ID" "$REVISION" "$HEAD_SHA" "$NODE" "$CANONICAL"

write_evidence() {
    jq -n --arg provider "$2" --arg outcome "$3" --arg digest "$REAL_DIGEST" --arg run_id "$RUN_ID" --arg revision "$REVISION" --arg head "$HEAD_SHA" \
        '{schema_version:1,gate:"parallel-review",node:"U4b-review[0]",provider:$provider,run_id:$run_id,revision:$revision,head:$head,frozen_input_digest:$digest,digest_algorithm:"sha256",verdict:{outcome:$outcome,reasoning:"test reasoning"},written_at:"2026-01-01T00:00:00Z"}' >"$1"
}
check() { [ "$2" = "$3" ] || {
    echo "FAIL $1"
    exit 1
}; }

CLAUDE="$TMP/claude.json"
CODEX="$TMP/codex.json"
write_evidence "$CLAUDE" claude approve
write_evidence "$CODEX" codex approve
OUT="$TMP/pass.json"
parallel_review_join::evaluate "$CANONICAL" "$CLAUDE" "$CODEX" done done "$RUN_ID" "$REVISION" "$HEAD_SHA" orchestrator "$NODE" "$OUT"
check pass-keys '["evaluated_at","evaluated_by","frozen_input_digest","hard_stop_reason","inputs","node","outcome","policy","schema_version"]' "$(jq -cS 'keys' "$OUT")"
check pass-outcome pass "$(jq -r .outcome "$OUT")"
check pass-digest "$REAL_DIGEST" "$(jq -r .frozen_input_digest "$OUT")"

OUT="$TMP/hard-stop.json"
parallel_review_join::evaluate "$CANONICAL" "$CLAUDE" "" done skipped "$RUN_ID" "$REVISION" "$HEAD_SHA" orchestrator "$NODE" "$OUT"
check hard-stop-outcome hard-stop "$(jq -r .outcome "$OUT")"
check missing-reason missing-evidence "$(jq -r .hard_stop_reason "$OUT")"
check null-codex null "$(jq -r .inputs.codex.outcome "$OUT")"

OUT="$TMP/skipped.json"
parallel_review_join::evaluate "$CANONICAL" "" "" skipped skipped "$RUN_ID" "$REVISION" "$HEAD_SHA" orchestrator "$NODE" "$OUT"
check skipped-outcome skipped "$(jq -r .outcome "$OUT")"
check skipped-reason null "$(jq -r '.hard_stop_reason | type' "$OUT")"
echo PASS
