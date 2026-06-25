#!/bin/bash
# Behavioural test for discipline_common.sh — exercises dc_extract_last_text
# with synthetic JSONL transcripts. All state lives under a temp dir.
# Run: bash hooks/scripts/tests/discipline_common.test.sh
set -u
LIB="$(cd "$(dirname "$0")/.." && pwd)/lib/discipline_common.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_DISCIPLINE_LOG="$TMP/discipline.log"
export CLAUDE_HOOK_MAX_ATTEMPTS=1   # no flush-race retry sleeps in tests
export CLAUDE_HOOK_SLEEP_S=0
fails=0

check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected: %q\n  actual:   %q\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# Source the lib under test.
# shellcheck source=/dev/null
. "$LIB"

# Helper: write a JSONL transcript and return the path.
mk_transcript() { # content...
  local out="$TMP/t_$RANDOM.jsonl"
  printf '%s\n' "$@" > "$out"
  printf '%s' "$out"
}

# --- Test (a): array-shaped content with multiple text blocks, joined by space ---
T=$(mk_transcript \
  '{"type":"assistant","message":{"content":[{"type":"text","text":"hello"},{"type":"tool_use","name":"Read","input":{}},{"type":"text","text":"world"}]}}')
result=$(dc_extract_last_text "$T" 200)
check "array content: multiple text blocks joined by space" "hello world" "$result"

# --- Test (b): string-shaped content ---
T=$(mk_transcript \
  '{"type":"assistant","message":{"content":"plain string text"}}')
result=$(dc_extract_last_text "$T" 200)
check "string content: returned as-is" "plain string text" "$result"

# --- Test (c): LAST assistant message wins when several exist ---
T=$(mk_transcript \
  '{"type":"assistant","message":{"content":[{"type":"text","text":"first message"}]}}' \
  '{"type":"user","message":{"content":[{"type":"text","text":"user turn"}]}}' \
  '{"type":"assistant","message":{"content":[{"type":"text","text":"second message"}]}}')
result=$(dc_extract_last_text "$T" 200)
check "last assistant message wins" "second message" "$result"

# --- Test (d): no assistant text -> empty string ---
T=$(mk_transcript \
  '{"type":"user","message":{"content":[{"type":"text","text":"user only"}]}}' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","input":{}}]}}')
result=$(dc_extract_last_text "$T" 200)
check "no assistant text -> empty" "" "$result"

# --- Test (e): dc_stable_text stabilises (MAX_ATTEMPTS=1 so runs once) ---
T=$(mk_transcript \
  '{"type":"assistant","message":{"content":[{"type":"text","text":"stable text"}]}}')
export CLAUDE_HOOK_MAX_ATTEMPTS=1
result=$(dc_stable_text "$T" 200 1 0)
check "dc_stable_text returns text on single attempt" "stable text" "$result"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails failures)"; exit 1; }
