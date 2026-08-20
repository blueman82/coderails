#!/bin/bash
# End-to-end synthetic test for native Codex scan -> cluster behavior.
set -u
set -o pipefail

SCAN_SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/scan_transcripts.sh"
CLUSTER_SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/cluster_ngrams.sh"
REPO_ROOT="$(cd "$(dirname "$0")/../../../.." && pwd)"
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

make_session() {
    local file="$1" session_id="$2" project="$3"
    {
        printf '{"type":"session_meta","timestamp":"2026-07-06T10:00:00Z","payload":{"id":"%s","session_id":"%s","cwd":"/work/%s","parent_thread_id":null}}\n' "$session_id" "$session_id" "$project"
        printf '%s\n' '{"type":"response_item","timestamp":"2026-07-06T10:00:01Z","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"private prompt"}]}}'
        printf '%s\n' '{"type":"event_msg","timestamp":"2026-07-06T10:00:02Z","payload":{"type":"item_completed","item":{"type":"CommandExecution","command":["/bin/zsh","-lc","git log --oneline"]}}}'
        printf '%s\n' '{"type":"event_msg","timestamp":"2026-07-06T10:00:03Z","payload":{"type":"item_completed","item":{"type":"CommandExecution","command":["/bin/zsh","-lc","git push origin"]}}}'
        printf '%s\n' '{"type":"event_msg","timestamp":"2026-07-06T10:00:04Z","payload":{"type":"item_completed","item":{"type":"CollabAgentToolCall","tool":"spawn_agent","prompt":"private agent prompt"}}}'
    } >"$file"
}

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
CORPUS="$TMP/corpus/2026/07/06"
mkdir -p "$CORPUS"
make_session "$CORPUS/rollout-a.jsonl" "session-a" "proj-a"
make_session "$CORPUS/rollout-b.jsonl" "session-b" "proj-b"
make_session "$CORPUS/rollout-c.jsonl" "session-c" "proj-c"

PIPELINE_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP/corpus" bash "$SCAN_SCRIPT" --all-projects --days 36500 | bash "$CLUSTER_SCRIPT" --min-sessions 3)
PIPELINE_RC=$?
check "native scan and cluster pipeline exits 0" "0" "$PIPELINE_RC"
TRIGRAM='["CommandExecution:git log","CommandExecution:git push","CollabAgentToolCall:spawn_agent"]'
CLUSTER=$(printf '%s' "$PIPELINE_OUT" | jq -c --argjson ngram "$TRIGRAM" '.clusters[] | select(.ngram == $ngram)')
check "native trigram is clustered" "$TRIGRAM" "$(printf '%s' "$CLUSTER" | jq -c '.ngram')"
check "native trigram has three-session support" "3" "$(printf '%s' "$CLUSTER" | jq -r '.sessions | length')"

SENTINEL_CORPUS="$TMP/sentinel/2026/07/06"
mkdir -p "$SENTINEL_CORPUS"
make_sentinel_session() {
    local file="$1" session_id="$2"
    {
        printf '{"type":"session_meta","timestamp":"2026-07-06T11:00:00Z","payload":{"id":"%s","session_id":"%s","cwd":"/work/proj-sentinel","parent_thread_id":null}}\n' "$session_id" "$session_id"
        printf '%s\n' '{"type":"event_msg","timestamp":"2026-07-06T11:00:01Z","payload":{"type":"item_completed","item":{"type":"CommandExecution","command":["/bin/zsh","-lc","curl -H Authorization:SENTINEL_sk_live_99xyz https://example.invalid"]}}}'
        printf '%s\n' '{"type":"response_item","timestamp":"2026-07-06T11:00:02Z","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"SENTINEL_sk_live_99xyz"}]}}'
        printf '%s\n' '{"type":"event_msg","timestamp":"2026-07-06T11:00:03Z","payload":{"type":"item_completed","item":{"type":"FileChange","changes":[{"path":"SENTINEL_sk_live_99xyz"}]}}}'
    } >"$file"
}
make_sentinel_session "$SENTINEL_CORPUS/rollout-a.jsonl" "sentinel-a"
make_sentinel_session "$SENTINEL_CORPUS/rollout-b.jsonl" "sentinel-b"
make_sentinel_session "$SENTINEL_CORPUS/rollout-c.jsonl" "sentinel-c"
check_contains "negative-control sentinel exists in synthetic input" "$(cat "$SENTINEL_CORPUS/rollout-a.jsonl")" "SENTINEL_sk_live_99xyz"
SCAN_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP/sentinel" bash "$SCAN_SCRIPT" --all-projects --days 36500)
check_not_contains "sentinel is absent from scan output" "$SCAN_OUT" "SENTINEL_sk_live_99xyz"
check_contains "safe command head remains" "$SCAN_OUT" '"head":"curl -H"'
CLUSTER_OUT=$(printf '%s' "$SCAN_OUT" | bash "$CLUSTER_SCRIPT" --min-sessions 3)
check_not_contains "sentinel is absent from cluster output" "$CLUSTER_OUT" "SENTINEL_sk_live_99xyz"

SANDBOX_HOME="$TMP/home"
mkdir -p "$SANDBOX_HOME/.codex/sessions/2026/07/06"
make_session "$SANDBOX_HOME/.codex/sessions/2026/07/06/rollout-a.jsonl" "home-a" "proj-home"
make_session "$SANDBOX_HOME/.codex/sessions/2026/07/06/rollout-b.jsonl" "home-b" "proj-home"
make_session "$SANDBOX_HOME/.codex/sessions/2026/07/06/rollout-c.jsonl" "home-c" "proj-home"
SKILLS_BEFORE=$(find "$REPO_ROOT/skills" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)
HOME="$SANDBOX_HOME" bash "$SCAN_SCRIPT" --all-projects --days 36500 | HOME="$SANDBOX_HOME" bash "$CLUSTER_SCRIPT" --min-sessions 3 >/dev/null
check "mechanical pipeline creates no personal skills" "0" "$(find "$SANDBOX_HOME" -name SKILL.md | wc -l | tr -d ' ')"
check "mechanical pipeline leaves repo skills unchanged" "$SKILLS_BEFORE" "$(find "$REPO_ROOT/skills" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | sort)"

EMPTY_CORPUS="$TMP/empty/2026/07/06"
mkdir -p "$EMPTY_CORPUS"
printf '%s\n' \
    '{"type":"session_meta","timestamp":"2026-07-06T12:00:00Z","payload":{"id":"empty","session_id":"empty","cwd":"/work/proj-empty","parent_thread_id":null}}' \
    '{"type":"event_msg","timestamp":"2026-07-06T12:00:01Z","payload":{"type":"item_completed","item":{"type":"FileChange"}}}' >"$EMPTY_CORPUS/rollout-empty.jsonl"
EMPTY_OUT=$(WORKFLOW_AUDIT_ROOT="$TMP/empty" bash "$SCAN_SCRIPT" --all-projects --days 36500 | bash "$CLUSTER_SCRIPT" --min-sessions 3)
check "no repeated sequence produces no candidates" "[]" "$(printf '%s' "$EMPTY_OUT" | jq -c '.clusters')"

if [[ "$fails" -eq 0 ]]; then
    printf '%s\n' PASS
    exit 0
fi
printf 'FAILED (%s)\n' "$fails"
exit 1
