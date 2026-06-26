#!/bin/bash
# Behavioural test for check_confidence_labels.sh — feeds synthetic Stop payloads
# with fixture transcripts and asserts exit codes. All state lives under a temp dir.
set -u
HOOK="$(cd "$(dirname "$0")/.." && pwd)/check_confidence_labels.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_DISCIPLINE_LOG="$TMP/discipline.log"
export CLAUDE_HOOK_MAX_ATTEMPTS=1   # no flush-race retry sleeps in tests
export CLAUDE_HOOK_SLEEP_S=0
fails=0

# Build a synthetic JSONL transcript with one assistant text message.
mk_transcript() { # text -> path
  local text="$1" out="$TMP/t_$RANDOM.jsonl"
  jq -n --arg t "$text" '{"type":"assistant","message":{"content":[{"type":"text","text":$t}]}}' > "$out"
  printf '%s' "$out"
}

payload() { # transcript_path -> json
  printf '{"transcript_path":"%s","session_id":"S1"}' "$1"
}

run() { # json -> exit code
  printf '%s' "$1" | bash "$HOOK" >/dev/null 2>&1; echo $?
}

check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected exit %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

LONG_TEXT=$(printf '%200s' | tr ' ' 'x')  # exactly 200 chars — meets the >=200 threshold

# Case 1: long response WITH a (verified) label -> allow (exit 0)
T=$(mk_transcript "${LONG_TEXT} (verified) and more text here")
check "labelled long response -> allow" 0 "$(run "$(payload "$T")")"

# Case 2: long response with (inferred) label -> allow
T=$(mk_transcript "${LONG_TEXT} (inferred) something")
check "inferred label -> allow" 0 "$(run "$(payload "$T")")"

# Case 3: long response with (guess) label -> allow
T=$(mk_transcript "${LONG_TEXT} (guess) something")
check "guess label -> allow" 0 "$(run "$(payload "$T")")"

# Case 4: long response with NO label -> block (exit 2)
T=$(mk_transcript "${LONG_TEXT}")
check "unlabelled long response -> block" 2 "$(run "$(payload "$T")")"

# Case 5: short response (< 200 chars) with NO label -> allow
T=$(mk_transcript "Short response without labels.")
check "short unlabelled response -> allow" 0 "$(run "$(payload "$T")")"

# Case 6: no transcript file -> allow
check "no transcript -> allow" 0 "$(run '{"transcript_path":"/nonexistent/path.jsonl","session_id":"S1"}')"

# Case 7: empty transcript_path -> allow
check "empty transcript_path -> allow" 0 "$(run '{"session_id":"S1"}')"

# ── SubagentStop cases ────────────────────────────────────────────────────────
# Build a SubagentStop payload using last_assistant_message directly (no transcript
# parsing). The parent transcript_path is intentionally a non-existent path to prove
# the hook reads last_assistant_message, not transcript_path.

subagentstop_payload() { # last_assistant_message -> json
  local msg="$1"
  jq -n --arg msg "$msg" '{
    "hook_event_name": "SubagentStop",
    "session_id": "S_sub",
    "agent_id": "agent-test",
    "transcript_path": "/nonexistent/parent.jsonl",
    "agent_transcript_path": "/nonexistent/subagent.jsonl",
    "stop_hook_active": false,
    "last_assistant_message": $msg
  }'
}

# Case 8: SubagentStop with labelled long message -> allow
check "SubagentStop labelled message -> allow" 0 "$(run "$(subagentstop_payload "${LONG_TEXT} (verified) claim")")"

# Case 9: SubagentStop with unlabelled long message -> block (exit 2)
check "SubagentStop unlabelled message -> block" 2 "$(run "$(subagentstop_payload "${LONG_TEXT}")")"

# Case 10: SubagentStop with (inferred) label -> allow
check "SubagentStop inferred label -> allow" 0 "$(run "$(subagentstop_payload "${LONG_TEXT} (inferred) claim")")"

# Case 11: SubagentStop with (guess) label -> allow
check "SubagentStop guess label -> allow" 0 "$(run "$(subagentstop_payload "${LONG_TEXT} (guess) claim")")"

# Case 12: SubagentStop with short message (< 200 chars) -> allow regardless of labels
check "SubagentStop short message -> allow" 0 "$(run "$(subagentstop_payload "Short subagent reply.")")"

# Regression: parent transcript is compliant (has a label in its text), but
# last_assistant_message is NOT compliant — must still BLOCK.
# This proves the script reads last_assistant_message, not transcript_path.
COMPLIANT_TRANSCRIPT=$(mk_transcript "${LONG_TEXT} (verified) parent content")
check "SubagentStop: compliant parent but non-compliant last_assistant_message -> block" 2 "$(
  jq -n --arg tp "$COMPLIANT_TRANSCRIPT" --arg msg "${LONG_TEXT}" '{
    "hook_event_name": "SubagentStop",
    "session_id": "S_reg",
    "agent_id": "agent-reg",
    "transcript_path": $tp,
    "agent_transcript_path": "/nonexistent/subagent.jsonl",
    "stop_hook_active": false,
    "last_assistant_message": $msg
  }' | bash "$HOOK" >/dev/null 2>&1; echo $?
)"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
