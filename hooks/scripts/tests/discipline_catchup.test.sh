#!/bin/bash
# Behavioural test for discipline_catchup.sh — feeds synthetic UserPromptSubmit
# payloads and asserts whether a catch-up additionalContext is injected.
set -u
HOOK="$(cd "$(dirname "$0")/.." && pwd)/discipline_catchup.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_DISCIPLINE_LOG="$TMP/discipline.log"
export CLAUDE_HOOK_TAIL_LINES=200
export CLAUDE_HOOK_MIN_LEN=200
fails=0

LONG_TEXT=$(printf '%200s' | tr ' ' 'x')   # 200 chars — meets the >=200 threshold

# Build a JSONL transcript with an optional Edit and an assistant text response.
mk_transcript() { # text num_edits -> path
  local text="$1" num_edits="${2:-0}" out="$TMP/t_$RANDOM.jsonl"
  local i=0
  while [ "$i" -lt "$num_edits" ]; do
    printf '%s\n' "{\"type\":\"assistant\",\"message\":{\"content\":[{\"type\":\"tool_use\",\"name\":\"Edit\",\"input\":{\"file_path\":\"/tmp/f$i.py\"}}]}}" >> "$out"
    i=$((i+1))
  done
  jq -n --arg t "$text" '{"type":"assistant","message":{"content":[{"type":"text","text":$t}]}}' >> "$out"
  printf '%s' "$out"
}

payload() { # transcript_path -> json
  printf '{"transcript_path":"%s","session_id":"S1"}' "$1"
}

run() { # json -> raw hook output
  printf '%s' "$1" | bash "$HOOK" 2>/dev/null
}

has_catchup() { # output -> yes|no
  if printf '%s' "$1" | grep -q '"additionalContext"'; then echo yes; else echo no; fi
}

check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# Case 1: no transcript -> silent (no output)
check "no transcript -> silent" no "$(has_catchup "$(run '{"session_id":"S1"}')")"

# Case 2: last response has labels -> no catch-up
T=$(mk_transcript "${LONG_TEXT} (verified) claim." 0)
check "response with label -> no catchup" no "$(has_catchup "$(run "$(payload "$T")")")"

# Case 3: last response is short (< MIN_LEN) without labels -> no catch-up (too short)
T=$(mk_transcript "Short response." 0)
check "short response without labels -> no catchup" no "$(has_catchup "$(run "$(payload "$T")")")"

# Case 4: long response without labels -> catch-up fires
T=$(mk_transcript "${LONG_TEXT}" 0)
check "long response without labels -> catchup fires" yes "$(has_catchup "$(run "$(payload "$T")")")"

# Case 5: catch-up mentions confidence labels
T=$(mk_transcript "${LONG_TEXT}" 0)
out=$(run "$(payload "$T")")
if printf '%s' "$out" | grep -q "confidence labels"; then
  printf 'ok   - catchup mentions confidence labels\n'
else
  printf 'FAIL - catchup should mention confidence labels\n'; fails=$((fails+1))
fi

# Case 6: long response with labels but >=3 file edits and no DNV section -> catchup fires (missing DNV)
T=$(mk_transcript "${LONG_TEXT} (verified) claim" 3)
check "3 edits, no DNV section -> catchup fires" yes "$(has_catchup "$(run "$(payload "$T")")")"

# Case 7: long response with labels and <3 file edits -> no catch-up (DNV not required below 3)
T=$(mk_transcript "${LONG_TEXT} (verified) claim" 2)
check "2 edits, has label -> no catchup" no "$(has_catchup "$(run "$(payload "$T")")")"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
