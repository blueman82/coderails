#!/bin/bash
# Behavioural test for unregistered_loop_guard.sh — feeds synthetic Stop
# payloads with fixture transcripts and asserts the nudge fires/stays silent
# per the spec's six cases. All state lives under a temp dir
# (CLAUDE_AGENTIC_LOOP_DIR), never the repo tree. Mirrors loop_state_guard.test.sh
# conventions.
set -u
GUARD="$(cd "$(dirname "$0")/.." && pwd)/unregistered_loop_guard.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_AGENTIC_LOOP_DIR="$TMP/state"
export CLAUDE_DISCIPLINE_LOG="$TMP/discipline.log"
CWD="/work/project"
fails=0

check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# --- Fixture builders (Task 1 interfaces) ---------------------------------

# n_distinct_turns -> path (each turn = distinct message.id, one Agent tool_use)
mk_dispatch_transcript() {
  local n="$1"
  local out="$TMP/d_${n}_$RANDOM.jsonl" i=0
  : > "$out"
  while [ "$i" -lt "$n" ]; do
    jq -cn --arg id "msg-$i" '{"type":"assistant","message":{"id":$id,"content":[{"type":"tool_use","name":"Agent","input":{}}]}}' >> "$out"
    i=$((i+1))
  done
  printf '%s' "$out"
}
# n_parallel_calls -> path (ONE message.id, N Agent tool_use entries)
mk_fanout_transcript() {
  local n="$1"
  local out="$TMP/fanout_${n}_$RANDOM.jsonl" i=0 content="["
  while [ "$i" -lt "$n" ]; do
    [ "$i" -gt 0 ] && content="$content,"
    content="$content{\"type\":\"tool_use\",\"name\":\"Agent\",\"input\":{}}"
    i=$((i+1))
  done
  content="$content]"
  jq -cn --argjson c "$content" '{"type":"assistant","message":{"id":"msg-0","content":$c}}' > "$out"
  printf '%s' "$out"
}
# n_distinct_turns -> path (each turn = distinct message.id, one Task tool_use — proves exact name match)
mk_task_transcript() {
  local n="$1"
  local out="$TMP/task_${n}_$RANDOM.jsonl" i=0
  : > "$out"
  while [ "$i" -lt "$n" ]; do
    jq -cn --arg id "msg-$i" '{"type":"assistant","message":{"id":$id,"content":[{"type":"tool_use","name":"Task","input":{}}]}}' >> "$out"
    i=$((i+1))
  done
  printf '%s' "$out"
}
# A transcript with N agentic-loop Skill invocations (mirrors loop_state_guard.test.sh's mk_transcript).
mk_skill_transcript() {
  local n="$1"
  local out="$TMP/skill_${n}_$RANDOM.jsonl" i=0
  : > "$out"
  while [ "$i" -lt "$n" ]; do
    printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:agentic-loop"}}]}}' >> "$out"
    i=$((i+1))
  done
  printf '%s' "$out"
}
# A transcript with a non-loop Skill call only.
mk_other_transcript() {
  local out="$TMP/other_$RANDOM.jsonl"
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:prep"}}]}}' > "$out"
  printf '%s' "$out"
}

# =====================================================================
# Task 1 — ulg_count_dispatch_turns (source ONLY the detection function)
# =====================================================================
# The guard script's main body is gated behind a `[ "${BASH_SOURCE[0]}" =
# "${0}" ]` check (only runs when executed directly, not when sourced), so
# sourcing it in a subshell defines the functions without triggering the
# stdin read or any gate exit — safe to call the pure functions directly.
call_fn() { # fn_name arg... -> stdout of calling fn_name after sourcing guard's functions only
  local fn="$1"; shift
  ( . "$GUARD"; "$fn" "$@" )
}

n=$(call_fn ulg_count_dispatch_turns "$(mk_dispatch_transcript 3)")
check "3 distinct message.id, 1 Agent each -> count 3" "3" "$n"

n=$(call_fn ulg_count_dispatch_turns "$(mk_fanout_transcript 3)")
check "1 shared message.id, 3 Agent tool_use (fan-out) -> count 1" "1" "$n"

n=$(call_fn ulg_count_dispatch_turns "$(mk_task_transcript 3)")
check "tool_use name Task (not Agent) -> count 0" "0" "$n"

n=$(call_fn ulg_count_dispatch_turns "$TMP/does-not-exist.jsonl")
check "missing transcript path -> count 0" "0" "$n"

# Malformed transcript: 2 valid dispatch lines + 1 truncated/broken JSON line.
# jq -s (slurp) aborts the WHOLE parse on a single bad line, so this must be
# distinguishable from a genuine empty/quiet transcript — ULG_PARSE_REASON is
# the signal callers use to log that distinction (see hooks_json main body).
mk_corrupt_transcript() {
  local out="$TMP/corrupt_$RANDOM.jsonl"
  jq -cn --arg id "msg-0" '{"type":"assistant","message":{"id":$id,"content":[{"type":"tool_use","name":"Agent","input":{}}]}}' > "$out"
  jq -cn --arg id "msg-1" '{"type":"assistant","message":{"id":$id,"content":[{"type":"tool_use","name":"Agent","input":{}}]}}' >> "$out"
  printf '%s\n' '{"type":"assistant", THIS IS NOT VALID JSON' >> "$out"
  printf '%s' "$out"
}
corrupt_t=$(mk_corrupt_transcript)
n=$( ( . "$GUARD"; ulg_count_dispatch_turns "$corrupt_t" ) )
check "malformed transcript JSON -> count 0 (fail-safe default)" "0" "$n"
parse_reason=$( ( . "$GUARD"; ulg_count_dispatch_turns "$corrupt_t" >/dev/null; printf '%s' "$ULG_PARSE_REASON" ) )
check "malformed transcript JSON -> ULG_PARSE_REASON=jq_parse_error (distinguishable from genuine 0)" "jq_parse_error" "$parse_reason"

# jq not on PATH -> ULG_PARSE_REASON=jq_missing, count 0. Source the guard
# FIRST (while jq is still reachable, since sourcing needs `dirname`), then
# blank PATH before calling the function under test.
jq_missing_t=$(mk_dispatch_transcript 3)
jq_missing_reason=$( (
  . "$GUARD"
  export PATH="/nonexistent_empty_dir_for_jq_shadow_test"
  ulg_count_dispatch_turns "$jq_missing_t" >/dev/null 2>&1
  printf '%s' "$ULG_PARSE_REASON"
) )
check "jq not on PATH -> ULG_PARSE_REASON=jq_missing" "jq_missing" "$jq_missing_reason"

empty_file="$TMP/empty_$RANDOM.jsonl"
: > "$empty_file"
n=$(call_fn ulg_count_dispatch_turns "$empty_file")
check "empty transcript file -> count 0" "0" "$n"

# =====================================================================
# Task 2 — ulg_has_progress_file / ulg_has_skill_invocation
# =====================================================================
SESSION_A="sess-A"

resolved_dir() { # session_id -> dir agentic_loop_path.sh resolves to for CWD
  local p
  p=$(bash "$(cd "$(dirname "$0")/../lib" && pwd)/agentic_loop_path.sh" "$CWD" "$1" 2>/dev/null)
  dirname "$p"
}

rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
n=$(call_fn ulg_has_progress_file "$CWD" "$SESSION_A")
check "no progress.json at resolved path -> 0" "0" "$n"

dir=$(resolved_dir "$SESSION_A")
mkdir -p "$dir"
printf '{"schema_version":1,"status":"in-progress","session_id":"%s"}' "$SESSION_A" > "$dir/progress.json"
n=$(call_fn ulg_has_progress_file "$CWD" "$SESSION_A")
check "progress.json present at resolved path -> 1" "1" "$n"
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"

n=$(call_fn ulg_has_skill_invocation "$(mk_skill_transcript 1)")
check "transcript with coderails:agentic-loop Skill call -> 1" "1" "$n"

n=$(call_fn ulg_has_skill_invocation "$(mk_other_transcript)")
check "transcript with only non-loop Skill call -> 0" "0" "$n"

# PR A follow-up: ulg_has_skill_invocation delegates to als_count_invocations
# (lib/loop_state_common.sh), which on jq failure signals a reason tag on
# STDERR (never logs directly — see its own comment: only als_stable_invocations,
# the retrying wrapper, decides whether/how to log, to avoid the ambiguous
# double-log / lost-recovery bug that per-attempt direct logging caused). This
# one-shot consumer calls als_count_invocations directly, not through the
# retry wrapper, so it must keep returning "0" unchanged (fail-open, same as
# before) AND must NOT produce a discipline-log line itself — matching its
# prior (pre-hardening) behavior of being silent on a parse failure.
: > "$CLAUDE_DISCIPLINE_LOG"
n=$(call_fn ulg_has_skill_invocation "$corrupt_t")
check "malformed transcript -> ulg_has_skill_invocation still returns 0 unchanged" "0" "$n"
check "malformed transcript, one-shot delegate call -> discipline log NOT touched" 0 \
  "$(grep -c 'reason=jq_parse_error' "$CLAUDE_DISCIPLINE_LOG" 2>/dev/null; true)"

# =====================================================================
# Task 3 — end-to-end gate: threshold, registration, nudge delivery
# =====================================================================
payload() { # transcript_path session_id -> JSON
  printf '{"transcript_path":"%s","session_id":"%s","cwd":"%s"}' "$1" "$2" "$CWD"
}
run() { printf '%s' "$1" | bash "$GUARD" >/dev/null 2>&1; echo $?; }               # -> exit code
run_stdout() { printf '%s' "$1" | bash "$GUARD" 2>/dev/null; }                     # -> stdout

# dispatch_turns=3, no progress.json, no Skill invocation -> exit 0 AND nudge fires.
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
T=$(mk_dispatch_transcript 3)
code=$(run "$(payload "$T" S1)")
check "3 dispatches, unregistered -> exit 0" "0" "$code"
: > "$CLAUDE_DISCIPLINE_LOG"  # nudge-once-per-session: reset so the next call is a first nudge for S1, not a suppressed repeat
out=$(run_stdout "$(payload "$T" S1)")
event=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.hookEventName // empty' 2>/dev/null)
ctx=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.additionalContext // empty' 2>/dev/null)
check "nudge stdout hookEventName == Stop" "Stop" "$event"
[ -n "$ctx" ] && check "nudge stdout additionalContext non-empty" "ok" "ok" || check "nudge stdout additionalContext non-empty" "ok" "FAIL: empty"

# dispatch_turns=3, progress.json present -> silent.
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
T=$(mk_dispatch_transcript 3)
dir=$(resolved_dir S1)
mkdir -p "$dir"
printf '{"schema_version":1,"status":"in-progress","session_id":"S1"}' > "$dir/progress.json"
code=$(run "$(payload "$T" S1)")
out=$(run_stdout "$(payload "$T" S1)")
check "3 dispatches, registered (progress.json) -> exit 0" "0" "$code"
check "3 dispatches, registered -> silent stdout" "" "$out"
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"

# dispatch_turns=3, no progress.json, but Skill invocation present -> silent.
# (Build a transcript containing BOTH 3 distinct Agent-dispatch turns AND an
# agentic-loop Skill invocation, so the dispatch count still clears the
# threshold while registration-by-Skill silences the nudge.)
mixed="$TMP/mixed_$RANDOM.jsonl"
: > "$mixed"
i=0
while [ "$i" -lt 3 ]; do
  jq -cn --arg id "mx-$i" '{"type":"assistant","message":{"id":$id,"content":[{"type":"tool_use","name":"Agent","input":{}}]}}' >> "$mixed"
  i=$((i+1))
done
printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:agentic-loop"}}]}}' >> "$mixed"
code=$(run "$(payload "$mixed" S1)")
out=$(run_stdout "$(payload "$mixed" S1)")
check "3 dispatches, no progress.json, Skill invoked -> exit 0" "0" "$code"
check "3 dispatches, Skill invoked -> silent stdout" "" "$out"

# dispatch_turns=2 (below threshold), no progress.json, no Skill invocation -> silent.
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
T=$(mk_dispatch_transcript 2)
code=$(run "$(payload "$T" S1)")
out=$(run_stdout "$(payload "$T" S1)")
check "2 dispatches (below threshold) -> exit 0" "0" "$code"
check "2 dispatches (below threshold) -> silent stdout" "" "$out"

# fan-out transcript: 5 parallel Agent calls, 1 message.id -> count 1, below
# threshold, silent even though 5 agents were spawned.
T=$(mk_fanout_transcript 5)
code=$(run "$(payload "$T" S1)")
out=$(run_stdout "$(payload "$T" S1)")
check "fan-out (5 parallel, 1 message.id) -> exit 0" "0" "$code"
check "fan-out (5 parallel, 1 message.id) -> silent (never trips nudge)" "" "$out"

# Stdin handling smoke case: pipe payload via printf (not echo), assert no hang/crash.
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
T=$(mk_dispatch_transcript 3)
code=$(printf '%s' "$(payload "$T" S1)" | bash "$GUARD" >/dev/null 2>&1; echo $?)
check "direct-payload stdin smoke (printf, not echo) -> exit 0" "0" "$code"

# End-to-end: malformed transcript JSON -> stays silent (fail-open design),
# same as any other skip reason, never a crash/hang and never a spurious nudge.
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
corrupt_e2e=$(mk_corrupt_transcript)
code=$(run "$(payload "$corrupt_e2e" S1)")
out=$(run_stdout "$(payload "$corrupt_e2e" S1)")
check "malformed transcript end-to-end -> exit 0" "0" "$code"
check "malformed transcript end-to-end -> silent stdout (fail-open, no spurious nudge)" "" "$out"

# End-to-end: malformed STDIN PAYLOAD (not transcript) -> logs reason=payload_parse_error,
# stays silent, exit 0. Distinct seam from the transcript-parse-error case above.
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
malformed_payload='{"transcript_path": "THIS IS NOT VALID JSON'
code=$(printf '%s' "$malformed_payload" | bash "$GUARD" >/dev/null 2>&1; echo $?)
out=$(printf '%s' "$malformed_payload" | bash "$GUARD" 2>/dev/null)
check "malformed stdin payload -> exit 0" "0" "$code"
check "malformed stdin payload -> silent stdout (fail-open, no spurious nudge)" "" "$out"

# =====================================================================
# Task 4 — nudge-once-per-session suppression
# =====================================================================
# The guard previously re-emitted its nudge on EVERY Stop for a non-loop
# session with no per-session termination, causing a self-perpetuating
# loop (nudge -> honest "no action needed" turn -> Stop -> nudge again).
# The discipline log already records "nudged=1" lines keyed by session_id
# on the emit path, so suppression reads that log for a prior nudge for
# THIS session_id before emitting again.

# Same session, two consecutive Stop invocations, conditions unchanged
# (3+ dispatches, no progress.json, no Skill invocation) -> nudge fires on
# the FIRST call but NOT the second.
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
: > "$CLAUDE_DISCIPLINE_LOG"
T=$(mk_dispatch_transcript 3)
out1=$(run_stdout "$(payload "$T" S-REPEAT)")
code1=$(run "$(payload "$T" S-REPEAT)")
check "repeat-session first Stop -> exit 0" "0" "$code1"
[ -n "$out1" ] && check "repeat-session first Stop -> nudge fires (non-empty stdout)" "ok" "ok" || check "repeat-session first Stop -> nudge fires (non-empty stdout)" "ok" "FAIL: empty"

out2=$(run_stdout "$(payload "$T" S-REPEAT)")
code2=$(run "$(payload "$T" S-REPEAT)")
check "repeat-session second Stop -> exit 0" "0" "$code2"
check "repeat-session second Stop -> nudge suppressed (silent stdout)" "" "$out2"
already_nudged_count=$(grep -c 'session=S-REPEAT.*reason=already_nudged_this_session' "$CLAUDE_DISCIPLINE_LOG" 2>/dev/null; true)
[ "$already_nudged_count" -ge 1 ] 2>/dev/null && check "repeat-session second Stop -> discipline log records already_nudged_this_session" "ok" "ok" || check "repeat-session second Stop -> discipline log records already_nudged_this_session" "ok" "FAIL: got $already_nudged_count"

# A fresh session meeting the conditions still nudges exactly once (the
# first-nudge path is untouched by the suppression branch).
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
: > "$CLAUDE_DISCIPLINE_LOG"
T=$(mk_dispatch_transcript 3)
out=$(run_stdout "$(payload "$T" S-FRESH)")
[ -n "$out" ] && check "fresh session -> nudges once (non-empty stdout)" "ok" "ok" || check "fresh session -> nudges once (non-empty stdout)" "ok" "FAIL: empty"
check "fresh session -> exactly one nudged=1 log line" 1 \
  "$(grep -c 'session=S-FRESH.*nudged=1' "$CLAUDE_DISCIPLINE_LOG" 2>/dev/null; true)"

# Different sessions are independent: session A having already nudged must
# NOT suppress session B's first nudge. Also proves the session-id match is
# exact (not a substring match) — "S-A" must not match "S-AB" or vice versa.
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
: > "$CLAUDE_DISCIPLINE_LOG"
T=$(mk_dispatch_transcript 3)
run "$(payload "$T" S-A)" >/dev/null   # session A's first (and only) nudge
out_b=$(run_stdout "$(payload "$T" S-AB)")
[ -n "$out_b" ] && check "distinct session S-AB not suppressed by prior S-A nudge" "ok" "ok" || check "distinct session S-AB not suppressed by prior S-A nudge" "ok" "FAIL: empty"

# Reverse direction of the above: S-AB nudges first, then S-A (the substring
# prefix) must still get its own first nudge. Proves the exact-match
# guarantee holds regardless of which of the two session ids fires first —
# matches the comment's "or vice versa" claim.
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
: > "$CLAUDE_DISCIPLINE_LOG"
T=$(mk_dispatch_transcript 3)
run "$(payload "$T" S-AB)" >/dev/null   # session S-AB's first (and only) nudge
out_a=$(run_stdout "$(payload "$T" S-A)")
[ -n "$out_a" ] && check "distinct session S-A not suppressed by prior S-AB nudge (reverse direction)" "ok" "ok" || check "distinct session S-A not suppressed by prior S-AB nudge (reverse direction)" "ok" "FAIL: empty"

# Regression: session_id is interpolated into a grep BRE pattern. A session
# id containing a literal BRE metachar (here "." in "s.1") must not be
# treated as a wildcard that matches an unrelated session's log line (e.g.
# "sX1"). als_sanitise_session_id only strips "/" and collapses ".." — a
# single "." survives untouched, so this is a real reachable session id.
# This test must FAIL against an unescaped grep (since a BRE "." matches any
# single char, "s.1" would wildcard-match a "session=sX1 ... nudged=1" line)
# and PASS once the session id is escaped/matched literally before use.
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
: > "$CLAUDE_DISCIPLINE_LOG"
T=$(mk_dispatch_transcript 3)
run "$(payload "$T" sX1)" >/dev/null   # sX1's first (and only) nudge
out_dot=$(run_stdout "$(payload "$T" "s.1")")
[ -n "$out_dot" ] && check "session 's.1' (literal dot) not falsely suppressed by unrelated 'sX1' nudge (BRE metachar regression)" "ok" "ok" || check "session 's.1' (literal dot) not falsely suppressed by unrelated 'sX1' nudge (BRE metachar regression)" "ok" "FAIL: empty"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
