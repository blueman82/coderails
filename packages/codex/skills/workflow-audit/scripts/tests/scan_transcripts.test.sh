#!/bin/bash
# Synthetic native-Codex coverage for scan_transcripts.sh.
set -u
set -o pipefail

SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/scan_transcripts.sh"
FIXTURES="$(cd "$(dirname "$0")" && pwd)/fixtures"
fails=0

check() {
    if [[ "$2" == "$3" ]]; then
        printf 'ok   - %s\n' "$1"
    else
        printf 'FAIL - %s\n      expected: %s\n      actual:   %s\n' "$1" "$2" "$3"
        fails=$((fails + 1))
    fi
}

check_contains() {
    if printf '%s' "$2" | grep -qF "$3"; then
        printf 'ok   - %s\n' "$1"
    else
        printf 'FAIL - %s\n      expected to contain: %s\n      actual: %s\n' "$1" "$3" "$2"
        fails=$((fails + 1))
    fi
}

check_not_contains() {
    if printf '%s' "$2" | grep -qF "$3"; then
        printf 'FAIL - %s\n      must NOT contain: %s\n      actual: %s\n' "$1" "$3" "$2"
        fails=$((fails + 1))
    else
        printf 'ok   - %s\n' "$1"
    fi
}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
SESSIONS="$TMP/2026/07/01"
mkdir -p "$SESSIONS"
cp "$FIXTURES/fixture-small.jsonl" "$SESSIONS/rollout-small.jsonl"
cp "$FIXTURES/fixture-edge.jsonl" "$SESSIONS/rollout-edge.jsonl"
cp "$FIXTURES/fixture-sentinel.jsonl" "$SESSIONS/rollout-sentinel.jsonl"

OUT=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-small --days 36500)
EXPECTED='[{"tool":"CommandExecution","head":"git log"},{"tool":"FileChange"},{"tool":"Extension","head":"web.search"},{"tool":"CollabAgentToolCall","head":"spawn_agent"}]'
check "native item_completed events are extracted" "$EXPECTED" "$(printf '%s' "$OUT" | jq -c '.events')"
check "event_count matches" "4" "$(printf '%s' "$OUT" | jq -r '.event_count')"
check "session id comes from session_meta" "11111111-1111-1111-1111-111111111111" "$(printf '%s' "$OUT" | jq -r '.session_id')"
check "project slug comes from session_meta cwd" "proj-small" "$(printf '%s' "$OUT" | jq -r '.project_slug')"

EDGE_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-edge --days 36500)
check "non-tool message records are ignored" \
    '[{"tool":"CommandExecution","head":"npm test"},{"tool":"Extension","head":"web.search"}]' \
    "$(printf '%s' "$EDGE_OUT" | jq -c '.events')"

SENTINEL_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-sentinel --days 36500)
check_not_contains "prompt and command arguments never reach output" "$SENTINEL_OUT" "SENTINEL_sk_live_99xyz"
check_contains "only the two-token command head survives" "$SENTINEL_OUT" '"head":"curl -H"'
check_contains "sentinel fixture contains the negative control" "$(cat "$FIXTURES/fixture-sentinel.jsonl")" "SENTINEL_sk_live_99xyz"

CORRUPT="$SESSIONS/rollout-corrupt.jsonl"
cp "$FIXTURES/fixture-small.jsonl" "$CORRUPT"
printf '{ not valid json\n' >>"$CORRUPT"
CORRUPT_ERR=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-small --days 36500 2>&1 >/dev/null)
check_contains "corrupt line is reported" "$CORRUPT_ERR" "jq_parse_error:"
CORRUPT_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-small --days 36500 2>/dev/null)
check "valid records in a partly corrupt file still emit" "2" "$(printf '%s' "$CORRUPT_OUT" | jq -s 'length')"

NONSTRING="$SESSIONS/rollout-nonstring.jsonl"
{
    printf '%s\n' '{"type":"session_meta","timestamp":"2026-07-05T00:00:00Z","payload":{"id":"nonstring","session_id":"nonstring","cwd":"/work/proj-nonstring","parent_thread_id":null}}'
    printf '%s\n' '{"type":"event_msg","timestamp":"2026-07-05T00:00:01Z","payload":{"type":"item_completed","item":{"type":"CommandExecution","command":{"secret":"command_secret"}}}}'
    printf '%s\n' '{"type":"event_msg","timestamp":"2026-07-05T00:00:02Z","payload":{"type":"item_completed","item":{"type":"Extension","kind":{"secret":"kind_secret"}}}}'
    printf '%s\n' '{"type":"event_msg","timestamp":"2026-07-05T00:00:03Z","payload":{"type":"item_completed","item":{"type":"Extension","kind":"kind_secret"}}}'
    printf '%s\n' '{"type":"event_msg","timestamp":"2026-07-05T00:00:04Z","payload":{"type":"item_completed","item":{"type":"CollabAgentToolCall","tool":["tool_secret"]}}}'
    printf '%s\n' '{"type":"event_msg","timestamp":"2026-07-05T00:00:05Z","payload":{"type":"item_completed","item":{"type":"CollabAgentToolCall","tool":"tool_secret"}}}'
} >"$NONSTRING"
NONSTRING_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-nonstring --days 36500)
check_not_contains "malformed or unknown native fields do not leak" "$NONSTRING_OUT" "secret"
check "malformed and unknown heads are omitted" \
    '[{"tool":"CommandExecution"},{"tool":"Extension"},{"tool":"Extension"},{"tool":"CollabAgentToolCall"},{"tool":"CollabAgentToolCall"}]' \
    "$(printf '%s' "$NONSTRING_OUT" | jq -c '.events')"

OLDER="$SESSIONS/rollout-older.jsonl"
NEWER="$SESSIONS/rollout-newer.jsonl"
printf '%s\n' \
    '{"type":"session_meta","timestamp":"2020-01-01T00:00:00Z","payload":{"id":"older","session_id":"older","cwd":"/work/proj-order","parent_thread_id":null}}' \
    '{"type":"event_msg","timestamp":"2020-01-01T00:00:01Z","payload":{"type":"item_completed","item":{"type":"FileChange"}}}' >"$OLDER"
printf '%s\n' \
    '{"type":"session_meta","timestamp":"2026-01-01T00:00:00Z","payload":{"id":"newer","session_id":"newer","cwd":"/work/proj-order","parent_thread_id":null}}' \
    '{"type":"event_msg","timestamp":"2026-01-01T00:00:01Z","payload":{"type":"item_completed","item":{"type":"Extension","kind":"web.search"}}}' >"$NEWER"
touch "$OLDER"
ORDER_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-order --last-sessions 1)
check "last-sessions uses JSONL timestamps, not mtime" "newer" "$(printf '%s' "$ORDER_OUT" | jq -r '.session_id')"

OWN="$SESSIONS/rollout-own.jsonl"
printf '%s\n' '{"type":"session_meta","timestamp":"2026-07-05T00:00:00Z","payload":{"id":"OWNTHREAD","session_id":"OWNSESSION","cwd":"/work/proj-own","parent_thread_id":null}}' >"$OWN"
OWN_ERR=$(WORKFLOW_AUDIT_ROOT="$TMP" CODEX_SESSION_ID="OWNSESSION" CODEX_THREAD_ID="OWNTHREAD" bash "$SCRIPT" --project proj-own --days 36500 2>&1 >/dev/null)
OWN_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP" CODEX_SESSION_ID="OWNSESSION" CODEX_THREAD_ID="OWNTHREAD" bash "$SCRIPT" --project proj-own --days 36500 2>/dev/null)
check "current session is excluded" "" "$OWN_OUT"
check_contains "current-session exclusion is reported" "$OWN_ERR" "skipped_own_session:"

CHILD="$SESSIONS/rollout-child.jsonl"
printf '%s\n' \
    '{"type":"session_meta","timestamp":"2026-07-05T00:00:00Z","payload":{"id":"child","session_id":"parent","cwd":"/work/proj-child","parent_thread_id":"parent"}}' \
    '{"type":"event_msg","timestamp":"2026-07-05T00:00:01Z","payload":{"type":"item_completed","item":{"type":"FileChange"}}}' >"$CHILD"
CHILD_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-child --days 36500 2>/dev/null)
check "child threads do not inflate session counts" "" "$CHILD_OUT"

NARROW_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-edge --days 36500)
check_not_contains "project filter excludes other cwd basenames" "$NARROW_OUT" "11111111-1111-1111-1111-111111111111"
check_contains "project filter includes the matching cwd basename" "$NARROW_OUT" "22222222-2222-2222-2222-222222222222"

DAYS_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-order --days 14)
check "old sessions are excluded by days" "" "$DAYS_OUT"
DAYS_WIDE=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-order --days 36500)
check "wide days window includes both sessions" "2" "$(printf '%s' "$DAYS_WIDE" | jq -s 'length')"

HELP_OUT=$(bash "$SCRIPT" --help)
check_contains "help names native session root" "$HELP_OUT" ".codex/sessions"
SANITY_ERR=$(WORKFLOW_AUDIT_ROOT="$TMP" bash "$SCRIPT" --project proj-small --days 36500 2>&1 >/dev/null)
check_contains "scan size is reported" "$SANITY_ERR" "scanning file_count="

if [[ "$fails" -eq 0 ]]; then
    printf '%s\n' PASS
    exit 0
fi
printf 'FAILED (%s)\n' "$fails"
exit 1
