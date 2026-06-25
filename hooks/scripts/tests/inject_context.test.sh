#!/bin/bash
# Behavioural test for inject_context.sh — feeds synthetic UserPromptSubmit payloads
# and asserts the [ctx] additionalContext line is always injected with expected fields.
set -u
HOOK="$(cd "$(dirname "$0")/.." && pwd)/inject_context.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fails=0

# Build an empty transcript (no prior assistant turns).
mk_empty_transcript() {
  local out="$TMP/t_empty_$RANDOM.jsonl"
  : > "$out"
  printf '%s' "$out"
}

# Build a transcript with one prior assistant turn (non-first prompt).
mk_transcript_with_prior() {
  local out="$TMP/t_prior_$RANDOM.jsonl"
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"text","text":"Hello"}]}}' > "$out"
  printf '%s' "$out"
}

run() { # json -> hook output
  printf '%s' "$1" | bash "$HOOK" 2>/dev/null
}

check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

check_contains() { # desc substring output
  if printf '%s' "$3" | grep -q "$2"; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected to contain "%s")\n' "$1" "$2"; fails=$((fails+1)); fi
}

# Case 1: output is valid JSON with hookSpecificOutput
out=$(run '{"session_id":"S1"}')
check "output is valid JSON" 0 "$(printf '%s' "$out" | jq -e . >/dev/null 2>&1; echo $?)"

# Case 2: hookEventName is UserPromptSubmit
out=$(run '{"session_id":"S1"}')
check "hookEventName=UserPromptSubmit" "UserPromptSubmit" "$(printf '%s' "$out" | jq -r '.hookSpecificOutput.hookEventName')"

# Case 3: additionalContext always contains [ctx]
out=$(run '{"session_id":"S1"}')
check_contains "[ctx] prefix present" "[ctx]" "$(printf '%s' "$out" | jq -r '.hookSpecificOutput.additionalContext')"

# Case 4: additionalContext contains today's date (YYYY-MM-DD format)
out=$(run '{"session_id":"S1"}')
TODAY=$(date '+%Y-%m-%d')
check_contains "context contains today's date" "$TODAY" "$(printf '%s' "$out" | jq -r '.hookSpecificOutput.additionalContext')"

# Case 5: additionalContext contains cwd=
out=$(run '{"session_id":"S1"}')
check_contains "context contains cwd=" "cwd=" "$(printf '%s' "$out" | jq -r '.hookSpecificOutput.additionalContext')"

# Case 6: additionalContext contains branch=
out=$(run '{"session_id":"S1"}')
check_contains "context contains branch=" "branch=" "$(printf '%s' "$out" | jq -r '.hookSpecificOutput.additionalContext')"

# Case 7: first prompt of session (empty transcript) -> discipline reminder is appended
T=$(mk_empty_transcript)
out=$(run "{\"session_id\":\"S1\",\"transcript_path\":\"$T\"}")
check_contains "first prompt has discipline reminder" "[discipline]" "$(printf '%s' "$out" | jq -r '.hookSpecificOutput.additionalContext')"

# Case 8: non-first prompt (prior assistant turn exists) -> no discipline reminder
T=$(mk_transcript_with_prior)
out=$(run "{\"session_id\":\"S1\",\"transcript_path\":\"$T\"}")
ctx=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.additionalContext')
if printf '%s' "$ctx" | grep -q "\[discipline\]"; then
  printf 'FAIL - non-first prompt should not contain discipline reminder\n'; fails=$((fails+1))
else
  printf 'ok   - non-first prompt has no discipline reminder\n'
fi

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
