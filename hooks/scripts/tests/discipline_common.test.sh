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

# --- Test (g-h): BLOCKER regression - PREFIX COLLISION must not substring-match.
# session=sess-a must not match a line for session=sess-ab. This is the
# function's headline guarantee (exact match, not substring): mutating the
# awk match from `$i == "session=" sid` to a substring/regex match (verified
# manually with `$i ~ ("session=" sid)`) makes this fixture return
# events:2 instead of events:1 -- this test fails under that mutation. ---
LOG="$TMP/discipline_mine_prefix.log"
cat > "$LOG" <<'EOF'
ts=1 session=sess-a hook=hook_five blocked=0
ts=2 session=sess-ab hook=hook_five blocked=0
EOF
result=$(dc_mine_hook_blocks "sess-a" "$LOG")
expected='{"hook_five":{"events":1,"flagged":0}}'
check "prefix collision: session=sess-ab line excluded from session=sess-a mine" "$expected" "$result"

# --- Test (g-i): multi-hook-per-session -- two distinct hooks in the same
# session must each land as independent, correctly-keyed entries ---
LOG="$TMP/discipline_mine_multihook.log"
cat > "$LOG" <<'EOF'
ts=1 session=sess-a hook=hook_alpha blocked=0
ts=2 session=sess-a hook=hook_beta blocked=1
ts=3 session=sess-a hook=hook_alpha blocked=0
EOF
result=$(dc_mine_hook_blocks "sess-a" "$LOG")
expected='{"hook_alpha":{"events":2,"flagged":0},"hook_beta":{"events":1,"flagged":1}}'
check "multi-hook session: both hooks tracked independently" "$expected" "$result"

# --- Test (g-j): log exists and is non-empty but zero lines match the
# session (no hook= at all) -- must fall to {} same as the missing-file and
# empty-session cases, not just those two ---
LOG="$TMP/discipline_mine_allgarbage.log"
cat > "$LOG" <<'EOF'
this line has no session or hook key at all
another totally unrelated line of text
EOF
result=$(dc_mine_hook_blocks "sess-a" "$LOG")
check "non-empty log, zero matches -> {}" "{}" "$result"

# --- Test (g-g): NEGATIVE CONTROL - proves the check() harness itself can
# detect a failure. Calls check() with a deliberately wrong expectation and
# confirms the failure counter increments; the induced failure is then
# subtracted back out so it doesn't pollute the real pass/fail total. ---
LOG="$TMP/discipline_mine_negctrl.log"
cat > "$LOG" <<'EOF'
ts=1 session=sess-a hook=hook_four blocked=0
EOF
result=$(dc_mine_hook_blocks "sess-a" "$LOG")
fails_before=$fails
check "negative control (expected to fail here)" '{"hook_four":{"events":99,"flagged":99}}' "$result"
if [ "$fails" -eq "$((fails_before + 1))" ]; then
  printf 'ok   - negative control: check() harness correctly detected the induced mismatch\n'
  fails=$fails_before
else
  printf 'FAIL - negative control: check() harness did NOT detect the induced mismatch (fails=%s, expected %s)\n' "$fails" "$((fails_before + 1))"
  fails=$((fails_before + 1))
fi

# --- dc_file_count ---

# --- Test (h): a malformed MIDDLE line must not zero the count -- the two
# valid edits either side of it should still be counted (fail-open harden,
# same per-line tolerant style as dc_extract_last_text) ---
T=$(mk_transcript \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/a.py"}}]}}' \
  'this is not valid json' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/b.py"}}]}}')
result=$(dc_file_count "$T")
check "malformed middle line does not zero the count" "2" "$result"

# --- Test (i): a truncated TRAILING line (torn final write during flush)
# must not hide the preceding valid edits ---
T=$(mk_transcript \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/a.py"}}]}}' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/b.py"}}]}}' \
  '{"type":"assistant","message":{"content":[{"typ')
result=$(dc_file_count "$T")
check "truncated trailing line does not zero the count" "2" "$result"

# --- Test (j): 3 edits to the SAME file path dedupe to 1 ---
T=$(mk_transcript \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/same.py"}}]}}' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/same.py"}}]}}' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/same.py"}}]}}')
result=$(dc_file_count "$T")
check "3 edits to one file path dedupe to 1" "1" "$result"

# --- Test (k): a line that is VALID JSON but a bare SCALAR must not zero the
# count. This is a different failure from test (h)'s malformed line: `fromjson?`
# DROPS unparseable text, but it KEEPS a scalar, which then reaches `.type` and
# makes jq error out ("Cannot index string with string \"type\""). Because
# stderr is discarded, that error is silent and the whole count came back 0.
# Same defect als_extract_last_text carried until PR #208. ---
T=$(mk_transcript \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/a.py"}}]}}' \
  '42' \
  '"a bare json string"' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/b.py"}}]}}')
result=$(dc_file_count "$T")
check "valid-JSON scalar line does not zero the count" "2" "$result"

# --- Test (l): the same scalar hazard for dc_extract_last_text -- a scalar line
# must not blank the extraction of a later assistant turn. ---
T=$(mk_transcript \
  '"a bare json string"' \
  '{"type":"assistant","message":{"content":[{"type":"text","text":"REAL ANSWER"}]}}')
result=$(dc_extract_last_text "$T" 50)
check "valid-JSON scalar line does not blank the extraction" "REAL ANSWER" "$result"

# --- Test (m): a wrong-shape OBJECT line -- `.message` a bare STRING, not an
# object -- must not zero the count. This is a different failure from test (k)'s
# scalar line: `select(type == "object")` passes this line (the outer value IS
# an object), but indexing `.message.content` on a string `.message` aborts the
# whole `jq -s` slurp ("Cannot index string with string \"content\""). Because
# stderr is discarded, that abort is silent and the count came back 0. Same
# defect ulg_count_dispatch_turns carried until PR (this one); third member of
# that family (dc_file_count, dc_extract_last_text, ulg_count_dispatch_turns). ---
T=$(mk_transcript \
  '{"type":"user","message":{"content":"please edit the file"}}' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Write","input":{"file_path":"/a.txt"}}]}}' \
  '{"type":"assistant","message":"oops"}')
result=$(dc_file_count "$T")
check "wrong-shape object (.message a bare string) does not zero the count" "1" "$result"

# --- Test (n): the same wrong-shape-object hazard for dc_extract_last_text --
# a non-object element inside `.message.content` (here `.message` itself is a
# bare ARRAY, not an object with a .content key) must not blank the extraction
# of a later assistant turn's real text. ---
T=$(mk_transcript \
  '{"type":"assistant","message":{"content":[{"type":"text","text":"REALTEXT"}]}}' \
  '{"type":"assistant","message":["bare"]}')
result=$(dc_extract_last_text "$T" 50)
check "wrong-shape object (.message a bare array) does not blank the extraction" "REALTEXT" "$result"

# --- Test (o): the same wrong-shape-object hazard reached through
# is_genuine_user -- a bare-STRING `.message` on a USER line (not an assistant
# line, unlike (m)) aborts the same slurp identically, because is_genuine_user
# also indexes `.message.content`. Must recover, not zero. ---
T=$(mk_transcript \
  '{"type":"user","message":"oops"}' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/a.py"}}]}}')
result=$(dc_file_count "$T")
check "wrong-shape object on a USER line (is_genuine_user hazard) does not zero the count" "1" "$result"

# --- Test (p): a shape that defeats the Layer 1 inner guards and genuinely
# aborts stage 2 -- a tool_use block whose `.input` is a bare STRING (not an
# object). This is not covered by any Layer 1 guard (those check `.message`
# and content-element shape, not `.input` shape), so it reaches Layer 2's
# agg_rc net. Must fail OPEN to 0, not error or hang -- and per this family's
# documented trade, over-attributes: the earlier valid Edit line is lost too,
# since Layer 2 is a whole-slurp net, not per-line recovery.
# NOTE: stdout "0" alone does NOT discriminate Layer 2's presence -- dc_file_count
# already initialises n=0 before the aggregation and launders an empty/non-numeric
# $n to 0 via the trailing `case` coercion, so an abort with NO rc-check at all
# would ALSO print "0" on stdout. The only observable Layer-2 signal is the
# stderr attribution, so this test asserts stderr, not stdout. ---
T=$(mk_transcript \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/a.py"}}]}}' \
  '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Write","input":"not an object"}]}}')
result=$(dc_file_count "$T" 2>"$TMP/p_stderr")
stderr_result=$(cat "$TMP/p_stderr")
check "Layer 2 net: .input-shape hazard fails open to 0 on stdout" "0" "$result"
check "Layer 2 net: .input-shape hazard attributes jq_parse_error on stderr" "jq_parse_error" "$stderr_result"

# --- Test (q): the same Layer-2-only hazard for dc_extract_last_text -- a
# text block whose `.text` field is an OBJECT (not a string/number). This
# defeats every Layer 1 guard (those check `.message` and content-element
# shape, not the `.text` value's own type), so `join(" ")` aborts trying to
# concatenate a string accumulator with a non-string element ("string and
# object cannot be added"), reaching Layer 2's agg_rc net. Must fail OPEN to
# empty, not error or hang -- and over-attributes: the earlier valid "REAL"
# text is lost too, same whole-slurp-net trade as test (p). Per test (p)'s
# own finding, stdout alone (already "" on init) cannot discriminate Layer 2's
# presence here either, so this asserts stderr. ---
T=$(mk_transcript \
  '{"type":"assistant","message":{"content":[{"type":"text","text":"REAL"}]}}' \
  '{"type":"assistant","message":{"content":[{"type":"text","text":{"nested":"obj"}}]}}')
result=$(dc_extract_last_text "$T" 50 2>"$TMP/q_stderr")
stderr_result=$(cat "$TMP/q_stderr")
check "Layer 2 net: .text-shape hazard fails open to empty on stdout" "" "$result"
check "Layer 2 net: .text-shape hazard attributes jq_parse_error on stderr" "jq_parse_error" "$stderr_result"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails failures)"; exit 1; }
