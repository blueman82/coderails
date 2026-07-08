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
# Tolerant two-stage parse (mirrors als_count_invocations): a single bad line
# is dropped at stage 1, the 2 valid lines still get counted at stage 2 — a
# BENIGN PARTIAL SKIP, not a failure. The count is valid and must be allowed
# through (ULG_PARSE_REASON stays empty), unlike a total-loss parse below.
mk_corrupt_transcript() {
  local out="$TMP/corrupt_$RANDOM.jsonl"
  jq -cn --arg id "msg-0" '{"type":"assistant","message":{"id":$id,"content":[{"type":"tool_use","name":"Agent","input":{}}]}}' > "$out"
  jq -cn --arg id "msg-1" '{"type":"assistant","message":{"id":$id,"content":[{"type":"tool_use","name":"Agent","input":{}}]}}' >> "$out"
  printf '%s\n' '{"type":"assistant", THIS IS NOT VALID JSON' >> "$out"
  printf '%s' "$out"
}
corrupt_t=$(mk_corrupt_transcript)
n=$( ( . "$GUARD"; ulg_count_dispatch_turns "$corrupt_t" ) )
check "benign partial skip (2 valid + 1 bad line) -> count 2 (recovered, not dropped)" "2" "$n"
parse_reason=$( ( . "$GUARD"; ulg_count_dispatch_turns "$corrupt_t" >/dev/null; printf '%s' "$ULG_PARSE_REASON" ) )
check "benign partial skip -> ULG_PARSE_REASON empty (partial skip is not a failure)" "" "$parse_reason"

# All-malformed transcript: every line is broken JSON -> TOTAL LOSS. Count
# must stay 0 AND ULG_PARSE_REASON must be non-empty (attribution preserved),
# distinguishing "every line malformed" from "0 dispatches, quiet session."
mk_all_malformed_transcript() {
  local out="$TMP/all_malformed_$RANDOM.jsonl"
  printf '%s\n' '{"type":"assistant", THIS IS NOT VALID JSON' > "$out"
  printf '%s\n' '{"also broken' >> "$out"
  printf '%s' "$out"
}
all_malformed_t=$(mk_all_malformed_transcript)
n=$( ( . "$GUARD"; ulg_count_dispatch_turns "$all_malformed_t" ) )
check "all-malformed transcript -> count 0 (total loss)" "0" "$n"
all_malformed_reason=$( ( . "$GUARD"; ulg_count_dispatch_turns "$all_malformed_t" >/dev/null; printf '%s' "$ULG_PARSE_REASON" ) )
[ -n "$all_malformed_reason" ] && check "all-malformed transcript -> ULG_PARSE_REASON non-empty (total loss attributed)" "ok" "ok" || check "all-malformed transcript -> ULG_PARSE_REASON non-empty (total loss attributed)" "ok" "FAIL: empty"
check "benign-skip and total-loss reasons are distinct (discriminator)" "ok" \
  "$([ "$parse_reason" != "$all_malformed_reason" ] && echo ok || echo "FAIL: both are '$parse_reason'")"

# Order independence: malformed line FIRST, then 2 valid lines (the existing
# fixture above only puts the malformed line last). Stage 1 parses per-line,
# so a bad line's position must not matter — this must still recover count 2
# with an empty reason, same as the malformed-last fixture.
mk_corrupt_first_transcript() {
  local out="$TMP/corrupt_first_$RANDOM.jsonl"
  printf '%s\n' '{"type":"assistant", THIS IS NOT VALID JSON' > "$out"
  jq -cn --arg id "msg-0" '{"type":"assistant","message":{"id":$id,"content":[{"type":"tool_use","name":"Agent","input":{}}]}}' >> "$out"
  jq -cn --arg id "msg-1" '{"type":"assistant","message":{"id":$id,"content":[{"type":"tool_use","name":"Agent","input":{}}]}}' >> "$out"
  printf '%s' "$out"
}
corrupt_first_t=$(mk_corrupt_first_transcript)
n=$( ( . "$GUARD"; ulg_count_dispatch_turns "$corrupt_first_t" ) )
check "benign partial skip, malformed line FIRST -> count 2 (order-independent)" "2" "$n"
corrupt_first_reason=$( ( . "$GUARD"; ulg_count_dispatch_turns "$corrupt_first_t" >/dev/null; printf '%s' "$ULG_PARSE_REASON" ) )
check "benign partial skip, malformed line FIRST -> ULG_PARSE_REASON empty" "" "$corrupt_first_reason"

# Blank/whitespace-only lines mixed with one malformed content line. The
# `total` line-count (grep -c '[^[:space:]]', a NEW variable this fix
# introduces) must exclude the blank lines so this still reads as "1
# non-blank line, that line is malformed" -> TOTAL LOSS, not a benign skip
# miscounted as 3 lines with 2 blank "successes".
mk_blank_and_malformed_transcript() {
  local out="$TMP/blank_malformed_$RANDOM.jsonl"
  printf '\n' > "$out"
  printf '   \n' >> "$out"
  printf '%s\n' '{"type":"assistant", THIS IS NOT VALID JSON' >> "$out"
  printf '%s' "$out"
}
blank_malformed_t=$(mk_blank_and_malformed_transcript)
n=$( ( . "$GUARD"; ulg_count_dispatch_turns "$blank_malformed_t" ) )
check "blank lines + 1 malformed content line -> count 0 (blank lines excluded from total)" "0" "$n"
blank_malformed_reason=$( ( . "$GUARD"; ulg_count_dispatch_turns "$blank_malformed_t" >/dev/null; printf '%s' "$ULG_PARSE_REASON" ) )
[ -n "$blank_malformed_reason" ] && check "blank lines + 1 malformed content line -> ULG_PARSE_REASON non-empty (total loss, not miscounted)" "ok" "ok" || check "blank lines + 1 malformed content line -> ULG_PARSE_REASON non-empty (total loss, not miscounted)" "ok" "FAIL: empty"

# Behavioural proof that a benign partial skip does not suppress a nudge that
# would otherwise fire: 3 valid dispatch turns + 1 malformed line -> the
# recovered count (3) still crosses the >=3 nudge threshold. The 2-valid
# fixture above can't prove this on its own (2<3).
mk_nudge_fires_transcript() {
  local out="$TMP/nudge_fires_$RANDOM.jsonl" i=0
  : > "$out"
  while [ "$i" -lt 3 ]; do
    jq -cn --arg id "nf-$i" '{"type":"assistant","message":{"id":$id,"content":[{"type":"tool_use","name":"Agent","input":{}}]}}' >> "$out"
    i=$((i+1))
  done
  printf '%s\n' '{"type":"assistant", THIS IS NOT VALID JSON' >> "$out"
  printf '%s' "$out"
}
nudge_fires_t=$(mk_nudge_fires_transcript)
n=$( ( . "$GUARD"; ulg_count_dispatch_turns "$nudge_fires_t" ) )
check "3 valid + 1 malformed -> count 3 (threshold crossed)" "3" "$n"
nudge_fires_reason=$( ( . "$GUARD"; ulg_count_dispatch_turns "$nudge_fires_t" >/dev/null; printf '%s' "$ULG_PARSE_REASON" ) )
check "3 valid + 1 malformed -> ULG_PARSE_REASON empty" "" "$nudge_fires_reason"

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

# End-to-end: benign-partial-skip transcript (2 valid + 1 bad line, recovered
# count 2) stays silent because 2 is still below the >=3 threshold — not
# because of a parse failure. Never a crash/hang and never a spurious nudge.
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
corrupt_e2e=$(mk_corrupt_transcript)
code=$(run "$(payload "$corrupt_e2e" S1)")
out=$(run_stdout "$(payload "$corrupt_e2e" S1)")
check "benign-partial-skip transcript end-to-end (count 2, below threshold) -> exit 0" "0" "$code"
check "benign-partial-skip transcript end-to-end -> silent stdout (below threshold)" "" "$out"

# End-to-end: all-malformed transcript (total loss, count 0) -> stays silent
# (fail-open design), same as any other skip reason, never a spurious nudge.
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
all_malformed_e2e=$(mk_all_malformed_transcript)
code=$(run "$(payload "$all_malformed_e2e" S1)")
out=$(run_stdout "$(payload "$all_malformed_e2e" S1)")
check "all-malformed transcript end-to-end -> exit 0" "0" "$code"
check "all-malformed transcript end-to-end -> silent stdout (fail-open, no spurious nudge)" "" "$out"

# Regression (subshell-loss bug): ulg_count_dispatch_turns sets ULG_PARSE_REASON
# on a GLOBAL, but the hook body calls it via command substitution
# (dispatch_turns=$(...)), which runs the function in a SUBSHELL -> the global
# assignment dies there and the parent-shell read of ULG_PARSE_REASON is always
# empty in production. For an all-malformed transcript this means the
# jq_parse_error reason=... log line the hook is SUPPOSED to emit never fires;
# it falls through to the >=3 threshold check and logs reason=below_threshold
# instead. Drives the REAL hook binary (not the sourced function) end-to-end
# and asserts the discipline log actually contains reason=jq_parse_error.
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
: > "$CLAUDE_DISCIPLINE_LOG"
all_malformed_reason_e2e=$(mk_all_malformed_transcript)
run "$(payload "$all_malformed_reason_e2e" S-JQERR)" >/dev/null
check "all-malformed transcript end-to-end -> discipline log records reason=jq_parse_error" 1 \
  "$(grep -c 'hook=unregistered_loop_guard session=S-JQERR.*reason=jq_parse_error' "$CLAUDE_DISCIPLINE_LOG" 2>/dev/null; true)"

# End-to-end core proof: 3 valid dispatch turns + 1 malformed line -> the
# recovered count crosses the threshold and the nudge FIRES. This is the
# fixture that proves the fix's actual purpose (the 2-valid fixture above
# can't, since 2 stays below threshold either way).
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
: > "$CLAUDE_DISCIPLINE_LOG"
nudge_fires_e2e=$(mk_nudge_fires_transcript)
code=$(run "$(payload "$nudge_fires_e2e" S-NUDGE)")
: > "$CLAUDE_DISCIPLINE_LOG"  # nudge-once-per-session: reset so the stdout check below is a first nudge for S-NUDGE, not a suppressed repeat
out=$(run_stdout "$(payload "$nudge_fires_e2e" S-NUDGE)")
check "3 valid + 1 malformed end-to-end -> exit 0" "0" "$code"
[ -n "$out" ] && check "3 valid + 1 malformed end-to-end -> nudge fires (non-empty stdout)" "ok" "ok" || check "3 valid + 1 malformed end-to-end -> nudge fires (non-empty stdout)" "ok" "FAIL: empty"

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

# =====================================================================
# Task 5 — mktemp-failure degraded path leaves a breadcrumb (review follow-up)
# =====================================================================
# When mktemp itself is unavailable, the hook can't capture
# ulg_count_dispatch_turns' stderr reason at all (the subshell-loss problem
# this PR fixes is unrecoverable a second time, by construction, in that
# branch). Before this follow-up, that degraded mode was completely silent —
# a genuine jq_missing/jq_parse_error transcript would fall through
# indistinguishable from a clean parse, logged only as reason=below_threshold
# with zero trace that the reason was ever lost. Force mktemp to fail via a
# PATH shim (a directory containing ONLY a failing `mktemp`, prepended to
# PATH so real jq/grep/bash/cat/rm still resolve from the rest of PATH) and
# assert the log now records the degraded mode.
MKTEMP_FAIL_DIR="$TMP/mktemp_fail_bin"
mkdir -p "$MKTEMP_FAIL_DIR"
cat > "$MKTEMP_FAIL_DIR/mktemp" <<'EOF'
#!/bin/bash
exit 1
EOF
chmod +x "$MKTEMP_FAIL_DIR/mktemp"

rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
: > "$CLAUDE_DISCIPLINE_LOG"
all_malformed_mktemp_fail=$(mk_all_malformed_transcript)
PATH="$MKTEMP_FAIL_DIR:$PATH" run "$(payload "$all_malformed_mktemp_fail" S-MKTEMPFAIL)" >/dev/null
check "mktemp-failure degraded path -> discipline log records reason=mktemp_unavailable" 1 \
  "$(grep -c 'hook=unregistered_loop_guard session=S-MKTEMPFAIL reason=mktemp_unavailable attribution=lost' "$CLAUDE_DISCIPLINE_LOG" 2>/dev/null; true)"

# Log-only guarantee: mktemp failure must NOT change nudge/exit behaviour.
# A transcript with 3+ real dispatches and no registration must still nudge
# even when mktemp is broken — the breadcrumb is an EXTRA log line, not a
# new early-exit path that could swallow a legitimate nudge.
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
: > "$CLAUDE_DISCIPLINE_LOG"
T=$(mk_dispatch_transcript 3)
out_mktemp_fail=$(PATH="$MKTEMP_FAIL_DIR:$PATH" run_stdout "$(payload "$T" S-MKTEMPFAIL2)")
code_mktemp_fail=$(PATH="$MKTEMP_FAIL_DIR:$PATH" run "$(payload "$T" S-MKTEMPFAIL2)")
check "mktemp-failure degraded path, 3 clean dispatches -> exit 0 (unchanged)" "0" "$code_mktemp_fail"
[ -n "$out_mktemp_fail" ] && check "mktemp-failure degraded path -> nudge still fires (log-only change, no exit-path hijack)" "ok" "ok" || check "mktemp-failure degraded path -> nudge still fires (log-only change, no exit-path hijack)" "ok" "FAIL: empty"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
