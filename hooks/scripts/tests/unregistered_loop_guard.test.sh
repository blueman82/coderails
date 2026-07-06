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
# distinguishable from a genuine empty/quiet transcript — ULG_PARSE_FAILED is
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
parse_failed=$( ( . "$GUARD"; ulg_count_dispatch_turns "$corrupt_t" >/dev/null; printf '%s' "$ULG_PARSE_FAILED" ) )
check "malformed transcript JSON -> ULG_PARSE_FAILED=1 (distinguishable from genuine 0)" "1" "$parse_failed"

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

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
