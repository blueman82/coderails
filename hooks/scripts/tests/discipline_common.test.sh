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

# --- Test (e): a malformed (non-JSON) line in the tail window must not
# collapse extraction to empty -- the valid assistant text should still win ---
T=$(mk_transcript \
  'this is not valid json' \
  '{"type":"assistant","message":{"content":[{"type":"text","text":"survives malformed line"}]}}')
result=$(dc_extract_last_text "$T" 200)
check "malformed line tolerated: valid text still extracted" "survives malformed line" "$result"

# --- Test (e2): a malformed line INTERLEAVED between valid messages must not
# disturb `last` ordering -- the final valid assistant text still wins ---
T=$(mk_transcript \
  '{"type":"assistant","message":{"content":[{"type":"text","text":"first valid"}]}}' \
  'this is not valid json' \
  '{"type":"assistant","message":{"content":[{"type":"text","text":"last valid"}]}}')
result=$(dc_extract_last_text "$T" 200)
check "malformed line interleaved: last valid text wins (ordering preserved)" "last valid" "$result"

# --- Test (e3): a trailing malformed line (torn final write during flush) must
# not hide the preceding valid message ---
T=$(mk_transcript \
  '{"type":"assistant","message":{"content":[{"type":"text","text":"valid before torn line"}]}}' \
  '{"type":"assistant","message":{"content":[{"typ')
result=$(dc_extract_last_text "$T" 200)
check "trailing torn line tolerated: preceding valid text still extracted" "valid before torn line" "$result"

# --- Test (e4): every line malformed -> empty (negative half of the contract) ---
T=$(mk_transcript \
  'not json at all' \
  '{"type":"assistant", broken')
result=$(dc_extract_last_text "$T" 200)
check "all lines malformed -> empty" "" "$result"

# --- Test (f): dc_stable_text stabilises (MAX_ATTEMPTS=1 so runs once) ---
T=$(mk_transcript \
  '{"type":"assistant","message":{"content":[{"type":"text","text":"stable text"}]}}')
export CLAUDE_HOOK_MAX_ATTEMPTS=1
result=$(dc_stable_text "$T" 200 1 0)
check "dc_stable_text returns text on single attempt" "stable text" "$result"

# --- dc_mine_hook_blocks ---

# --- Test (g-a): two sessions interleaved -> only target session's lines counted ---
LOG="$TMP/discipline_mine.log"
cat > "$LOG" <<'EOF'
ts=1 session=sess-a hook=test_gate.sh blocked=0
ts=2 session=sess-b hook=test_gate.sh blocked=1
ts=3 session=sess-a hook=test_gate.sh blocked=0
EOF
result=$(dc_mine_hook_blocks "sess-a" "$LOG")
expected='{"test_gate.sh":{"events":2,"flagged":0}}'
check "two sessions interleaved: only target session counted" "$expected" "$result"

# --- Test (g-b): blocked=1 / would_block=1 / nudged=1 each land in flagged; clean lines only in events ---
LOG="$TMP/discipline_mine_flags.log"
cat > "$LOG" <<'EOF'
ts=1 session=sess-a hook=hook_one blocked=1
ts=2 session=sess-a hook=hook_one would_block=1
ts=3 session=sess-a hook=hook_one nudged=1
ts=4 session=sess-a hook=hook_one
EOF
result=$(dc_mine_hook_blocks "sess-a" "$LOG")
expected='{"hook_one":{"events":4,"flagged":3}}'
check "blocked/would_block/nudged all flag; clean line only bumps events" "$expected" "$result"

# --- Test (g-c): missing log file -> {} ---
result=$(dc_mine_hook_blocks "sess-a" "$TMP/does_not_exist.log")
check "missing log file -> {}" "{}" "$result"

# --- Test (g-d): empty session id -> {} ---
result=$(dc_mine_hook_blocks "" "$LOG")
check "empty session id -> {}" "{}" "$result"

# --- Test (g-e): a garbage line with no hook= is skipped without breaking the parse ---
LOG="$TMP/discipline_mine_garbage.log"
cat > "$LOG" <<'EOF'
this is a garbage line with no key=value shape
ts=1 session=sess-a hook=hook_two blocked=0
EOF
result=$(dc_mine_hook_blocks "sess-a" "$LOG")
expected='{"hook_two":{"events":1,"flagged":0}}'
check "garbage line with no hook= skipped without breaking parse" "$expected" "$result"

# --- Test (g-f): real-shape line with hook= but NO session= field at all is excluded ---
LOG="$TMP/discipline_mine_nosession.log"
cat > "$LOG" <<'EOF'
ts=1 hook=unregistered_loop_guard.sh payload_parse_error=1
ts=2 session=sess-a hook=hook_three blocked=0
EOF
result=$(dc_mine_hook_blocks "sess-a" "$LOG")
expected='{"hook_three":{"events":1,"flagged":0}}'
check "line with hook= but no session= excluded from every session's counts" "$expected" "$result"

# --- Test (g-g): NEGATIVE CONTROL - a deliberately-wrong expected count must fail the comparison ---
LOG="$TMP/discipline_mine_negctrl.log"
cat > "$LOG" <<'EOF'
ts=1 session=sess-a hook=hook_four blocked=0
EOF
result=$(dc_mine_hook_blocks "sess-a" "$LOG")
wrong_expected='{"hook_four":{"events":99,"flagged":99}}'
if [ "$wrong_expected" = "$result" ]; then
  printf 'FAIL - negative control: wrong expectation should NOT match actual\n'
  fails=$((fails+1))
else
  printf 'ok   - negative control: wrong expectation correctly fails comparison\n'
fi

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails failures)"; exit 1; }
