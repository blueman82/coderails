#!/bin/bash
# Behavioural test for unregistered_loop_guard.sh — feeds synthetic Stop
# payloads with fixture transcripts and asserts BOTH directions of the gate:
# an unregistered dispatch-heavy session BLOCKS (exit 2, stderr message), and
# a registered one (stub present, or agentic-loop Skill invoked) does NOT.
# A gate whose deny path is never exercised is unproven, so the block is
# asserted on exit code, delivery channel, message content, persistence
# across repeated stops, and both sides of the threshold boundary.
# All state lives under a temp dir
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
  while [ "$i" -lt 4 ]; do
    jq -cn --arg id "nf-$i" '{"type":"assistant","message":{"id":$id,"content":[{"type":"tool_use","name":"Agent","input":{}}]}}' >> "$out"
    i=$((i+1))
  done
  printf '%s\n' '{"type":"assistant", THIS IS NOT VALID JSON' >> "$out"
  printf '%s' "$out"
}
nudge_fires_t=$(mk_nudge_fires_transcript)
n=$( ( . "$GUARD"; ulg_count_dispatch_turns "$nudge_fires_t" ) )
check "4 valid + 1 malformed -> count 4 (threshold crossed)" "4" "$n"
nudge_fires_reason=$( ( . "$GUARD"; ulg_count_dispatch_turns "$nudge_fires_t" >/dev/null; printf '%s' "$ULG_PARSE_REASON" ) )
check "4 valid + 1 malformed -> ULG_PARSE_REASON empty" "" "$nudge_fires_reason"

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

# -> stderr only (stdout discarded). Wrapping the stdout discard in braces and
# putting `2>&1` last is the form shellcheck SC2069 accepts without a
# suppression: stdout goes to /dev/null inside the group, then the group's
# stderr is duped onto the captured stdout.
run_stderr() { printf '%s' "$1" | { bash "$GUARD" >/dev/null; } 2>&1; }

# DENY DIRECTION. dispatch_turns=3, no progress.json, no Skill invocation ->
# exit 2 (BLOCK) with the message on stderr, the delivery shape a blocking Stop
# hook uses (mirrors loop_stall_guard.sh's block_missing_declaration). This is
# the whole point of the guard: advisory additionalContext was read and ignored
# live on 2026-07-21, so the nudge became a block.
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
T=$(mk_dispatch_transcript 4)
code=$(run "$(payload "$T" S1)")
check "4 dispatches, unregistered -> exit 2 (BLOCKS)" "2" "$code"
err=$(run_stderr "$(payload "$T" S1)")
[ -n "$err" ] && check "block message delivered on stderr (blocking-Stop channel)" "ok" "ok" || check "block message delivered on stderr (blocking-Stop channel)" "ok" "FAIL: empty"
# The message must name the EXACT resolved progress.json path. A message that
# made the model compute the path itself could re-block a complying session —
# the one realistic way this block could have deadlocked in practice.
expected_path=$(bash "$(cd "$(dirname "$0")/../lib" && pwd)/agentic_loop_path.sh" "$CWD" S1 2>/dev/null)
check "block message names the exact resolved progress.json path" "ok" \
  "$(printf '%s' "$err" | grep -qF "$expected_path" && echo ok || echo "FAIL: resolved path absent from message")"
check "block message names the agentic-loop Skill as the other clear" "ok" \
  "$(printf '%s' "$err" | grep -q 'agentic-loop' && echo ok || echo "FAIL: skill clear not offered")"
out=$(run_stdout "$(payload "$T" S1)")
check "block emits nothing on stdout (not an additionalContext nudge)" "" "$out"

# The block must NOT be clearable by anything the model can merely assert. No
# flag, no justification field, no "this was a one-off" declaration — the ONLY
# clears are the two real registrations. Two checks, because a text grep alone
# is a weak instrument:
#   (a) the message must not carry the OLD advisory sentence, which under a
#       block would have been the loophole ("no action is needed").
#   (b) the behavioural proof — a session that does nothing but keep stopping
#       stays blocked. Asserted by the repeat-stop checks above.
# Note "one-off" legitimately appears as the LABEL for clear #1 (write the
# stub); labelling a real clear is not offering an assertion escape, so this
# greps the escape phrasing specifically, not the word.
check "block message does not carry the old advisory no-action-needed escape" "ok" \
  "$(printf '%s' "$err" | grep -qiE 'no action is needed|no action needed' && echo "FAIL: advisory escape sentence survived" || echo ok)"
check "block message states no assertion can clear it" "ok" \
  "$(printf '%s' "$err" | grep -qiE 'nothing you can write|no third option' && echo ok || echo "FAIL: message does not close the assertion path")"

# Block REPEATS while unregistered — it is not suppressed after firing once.
# This is the specific regression the removed nudge-once-per-session logic
# caused: a guard that blocks once then goes quiet is the failure being fixed.
code2=$(run "$(payload "$T" S1)")
check "4 dispatches, unregistered, SECOND stop -> still exit 2 (no once-per-session suppression)" "2" "$code2"
code3=$(run "$(payload "$T" S1)")
check "4 dispatches, unregistered, THIRD stop -> still exit 2 (block persists until registered)" "2" "$code3"
check "no already_nudged_this_session suppression remains in the log" 0 \
  "$(grep -c 'already_nudged_this_session' "$CLAUDE_DISCIPLINE_LOG" 2>/dev/null; true)"

# ALLOW DIRECTION, escape 1 of 2: writing the bare progress.json stub at the
# resolved path clears the block. Verified empirically that a bare stub with NO
# Skill invocation leaves loop_state_guard.sh and loop_stall_guard.sh both at
# invocations=0/blocked=0, so this clear does not cascade into a sibling block.
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
dir=$(resolved_dir S-CLEAR)
mkdir -p "$dir"
printf '{"schema_version":1,"status":"in-progress","session_id":"S-CLEAR"}' > "$dir/progress.json"
code=$(run "$(payload "$T" S-CLEAR)")
check "block CLEARED by writing the progress.json stub -> exit 0" "0" "$code"
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"

# dispatch_turns=3, progress.json present -> silent.
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
T=$(mk_dispatch_transcript 4)
dir=$(resolved_dir S1)
mkdir -p "$dir"
printf '{"schema_version":1,"status":"in-progress","session_id":"S1"}' > "$dir/progress.json"
code=$(run "$(payload "$T" S1)")
out=$(run_stdout "$(payload "$T" S1)")
check "4 dispatches, registered (progress.json) -> exit 0 (does NOT block)" "0" "$code"
check "4 dispatches, registered -> silent stdout" "" "$out"
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"

# dispatch_turns=3, no progress.json, but Skill invocation present -> silent.
# (Build a transcript containing BOTH 3 distinct Agent-dispatch turns AND an
# agentic-loop Skill invocation, so the dispatch count still clears the
# threshold while registration-by-Skill silences the nudge.)
mixed="$TMP/mixed_$RANDOM.jsonl"
: > "$mixed"
i=0
while [ "$i" -lt 4 ]; do
  jq -cn --arg id "mx-$i" '{"type":"assistant","message":{"id":$id,"content":[{"type":"tool_use","name":"Agent","input":{}}]}}' >> "$mixed"
  i=$((i+1))
done
printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:agentic-loop"}}]}}' >> "$mixed"
code=$(run "$(payload "$mixed" S1)")
out=$(run_stdout "$(payload "$mixed" S1)")
check "4 dispatches, no progress.json, Skill invoked -> exit 0 (does NOT block)" "0" "$code"
check "4 dispatches, Skill invoked -> silent stdout" "" "$out"

# THRESHOLD BOUNDARY. Raised 3 -> 4 with the nudge->block change: under a
# nudge a false positive cost one ignorable line, under a block it costs a
# forced stub write, so the bar sits above the common benign shape (a few
# genuinely independent one-shot dispatches). Pin BOTH sides of the boundary
# so a future edit cannot drift the threshold unnoticed.
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
T3=$(mk_dispatch_transcript 3)
check "3 dispatches (exactly below threshold) -> exit 0 (does NOT block)" "0" "$(run "$(payload "$T3" S-EDGE)")"
T4=$(mk_dispatch_transcript 4)
check "4 dispatches (exactly at threshold) -> exit 2 (blocks)" "2" "$(run "$(payload "$T4" S-EDGE)")"

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
# 3 unregistered dispatches now BLOCK, so the expected code here is 2, not 0 —
# this asserts the payload was read and gated, not that the stop was allowed.
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
T=$(mk_dispatch_transcript 4)
code=$(printf '%s' "$(payload "$T" S1)" | bash "$GUARD" >/dev/null 2>&1; echo $?)
check "direct-payload stdin smoke (printf, not echo) -> exit 2 (payload read and gated)" "2" "$code"

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
# recovered count crosses the threshold and the BLOCK fires. A benign partial
# skip must not fail the guard open — the evidence is still trustworthy.
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
: > "$CLAUDE_DISCIPLINE_LOG"
nudge_fires_e2e=$(mk_nudge_fires_transcript)
code=$(run "$(payload "$nudge_fires_e2e" S-NUDGE)")
err=$(run_stderr "$(payload "$nudge_fires_e2e" S-NUDGE)")
check "4 valid + 1 malformed end-to-end -> exit 2 (benign partial skip does not fail open)" "2" "$code"
[ -n "$err" ] && check "4 valid + 1 malformed end-to-end -> block message on stderr" "ok" "ok" || check "3 valid + 1 malformed end-to-end -> block message on stderr" "ok" "FAIL: empty"

# End-to-end: malformed STDIN PAYLOAD (not transcript) -> logs reason=payload_parse_error,
# stays silent, exit 0. Distinct seam from the transcript-parse-error case above.
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
malformed_payload='{"transcript_path": "THIS IS NOT VALID JSON'
code=$(printf '%s' "$malformed_payload" | bash "$GUARD" >/dev/null 2>&1; echo $?)
out=$(printf '%s' "$malformed_payload" | bash "$GUARD" 2>/dev/null)
check "malformed stdin payload -> exit 0" "0" "$code"
check "malformed stdin payload -> silent stdout (fail-open, no spurious nudge)" "" "$out"

# =====================================================================
# Task 4 — the block persists across sessions and is per-session independent
# =====================================================================
# The nudge-once-per-session suppression (and its whole BRE-escaping
# regression suite) is DELETED with the advisory design it served. A warning
# needed a once-per-session ledger to stop re-firing forever; a block does
# not — it must persist until the loop is actually registered, which is the
# entire point. "Blocks once, then goes quiet" IS the failure being fixed.
# Persistence is asserted in the DENY-direction block above (2nd/3rd stop).
# What remains worth asserting here: two distinct unregistered sessions each
# get blocked independently, with no cross-session ledger coupling them.
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
: > "$CLAUDE_DISCIPLINE_LOG"
T=$(mk_dispatch_transcript 4)
code_a=$(run "$(payload "$T" S-A)")
code_b=$(run "$(payload "$T" S-AB)")
check "unregistered session S-A -> exit 2" "2" "$code_a"
check "unregistered session S-AB blocked independently of S-A -> exit 2" "2" "$code_b"

# Cross-session isolation of the CLEAR: registering S-A must not clear S-AB.
dir=$(resolved_dir S-A)
mkdir -p "$dir"
printf '{"schema_version":1,"status":"in-progress","session_id":"S-A"}' > "$dir/progress.json"
code_a2=$(run "$(payload "$T" S-A)")
code_b2=$(run "$(payload "$T" S-AB)")
check "S-A registered -> exit 0 (its own block cleared)" "0" "$code_a2"
check "S-AB still unregistered -> exit 2 (S-A's registration does not clear it)" "2" "$code_b2"
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"

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

# Log-only guarantee: mktemp failure must NOT change block/exit behaviour.
# A transcript with 3+ real dispatches and no registration must still BLOCK
# even when mktemp is broken — the breadcrumb is an EXTRA log line, not a
# new early-exit path that could swallow a legitimate block (fail-open on the
# infrastructure defect must not become fail-open on the evidence).
rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"
: > "$CLAUDE_DISCIPLINE_LOG"
T=$(mk_dispatch_transcript 4)
err_mktemp_fail=$(PATH="$MKTEMP_FAIL_DIR:$PATH" run_stderr "$(payload "$T" S-MKTEMPFAIL2)")
code_mktemp_fail=$(PATH="$MKTEMP_FAIL_DIR:$PATH" run "$(payload "$T" S-MKTEMPFAIL2)")
check "mktemp-failure degraded path, 4 clean dispatches -> exit 2 (still blocks)" "2" "$code_mktemp_fail"
[ -n "$err_mktemp_fail" ] && check "mktemp-failure degraded path -> block still fires (log-only change, no exit-path hijack)" "ok" "ok" || check "mktemp-failure degraded path -> block still fires (log-only change, no exit-path hijack)" "ok" "FAIL: empty"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
