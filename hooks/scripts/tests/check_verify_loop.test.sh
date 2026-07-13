#!/bin/bash
# Behavioural test for check_verify_loop.sh — feeds synthetic Stop payloads with
# fixture transcripts and asserts exit codes. All state lives under a temp dir.
set -u
HOOK="$(cd "$(dirname "$0")/.." && pwd)/check_verify_loop.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_AGENTIC_LOOP_DIR="$TMP/state"
export CLAUDE_DISCIPLINE_LOG="$TMP/discipline.log"
export CLAUDE_HOOK_MAX_ATTEMPTS=1   # no flush-race retry sleeps in tests
export CLAUDE_HOOK_SLEEP_S=0
CWD="/work/project"
SLUG="-work-project"
fails=0

# Build a JSONL transcript with an Edit tool use + an assistant text message.
# The hook skips when no files were edited (file_count < 1), so every case that
# needs enforcement must include at least one Write/Edit/MultiEdit tool_use entry.
mk_transcript() { # text -> path
  local text="$1" out="$TMP/t_$RANDOM.jsonl"
  # tool_use line: simulates an Edit call
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/f.py"}}]}}' > "$out"
  # text line: assistant response that the hook inspects
  jq -nc --arg t "$text" '{"type":"assistant","message":{"content":[{"type":"text","text":$t}]}}' >> "$out"
  printf '%s' "$out"
}

# Transcript with a text message but NO file edits — hook skips file_count check.
mk_transcript_no_edit() { # text -> path
  local text="$1" out="$TMP/t_ne_$RANDOM.jsonl"
  jq -nc --arg t "$text" '{"type":"assistant","message":{"content":[{"type":"text","text":$t}]}}' > "$out"
  printf '%s' "$out"
}

payload() { # transcript_path [stop_hook_active] -> json
  local tp="$1" sha="${2:-false}"
  printf '{"transcript_path":"%s","session_id":"S1","cwd":"%s","stop_hook_active":%s}' "$tp" "$CWD" "$sha"
}

run() { # json -> exit code
  printf '%s' "$1" | bash "$HOOK" >/dev/null 2>&1; echo $?
}

check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected exit %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# ── Loop-scoped warn-demotion fixture helpers (mirrors loop_stall_guard.test.sh) ──
file_dir() { printf '%s/%s/%s' "$CLAUDE_AGENTIC_LOOP_DIR" "$SLUG" "$1"; }   # session_id -> dir
# Builds a transcript with N agentic-loop invocations, an Edit tool_use (so
# file_count>=1), then the given final text (typically with an untagged DNV bullet).
mk_loop_transcript() { # n_invocations final_text -> path
  local n="$1" final="$2" out="$TMP/lt_${RANDOM}.jsonl" i=0
  : > "$out"
  while [ "$i" -lt "$n" ]; do
    printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:agentic-loop"}}]}}' >> "$out"
    i=$((i+1))
  done
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/f.py"}}]}}' >> "$out"
  if [ -n "$final" ]; then
    jq -cn --arg t "$final" '{type:"assistant",message:{content:[{type:"text",text:$t}]}}' >> "$out"
  fi
  printf '%s' "$out"
}
write_progress() { # session_id status completed_marker
  local dir; dir=$(file_dir "$1")
  mkdir -p "$dir"
  printf '{"schema_version":1,"status":"%s","session_id":"%s","completed_marker":%s}' "$2" "$1" "$3" > "$dir/progress.json"
}
loop_payload() { # transcript session_id [stop_hook_active] [hook_event_name]
  printf '{"transcript_path":"%s","session_id":"%s","cwd":"%s","stop_hook_active":%s,"hook_event_name":"%s"}' \
    "$1" "$2" "$CWD" "${3:-false}" "${4:-Stop}"
}
run_capture() { # json -> sets RC_OUT and OUT_OUT (stdout), no subshell needed for RC
  OUT_OUT=$(printf '%s' "$1" | bash "$HOOK" 2>/dev/null)
  RC_OUT=$?
}
reset_loop() { rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"; }

RESP_NO_DNV="This is a response that edits files but has no Did Not Verify section. (verified)"

# Case 1: no transcript file -> allow
check "no transcript -> allow" 0 "$(run '{"transcript_path":"/nonexistent.jsonl","session_id":"S1","stop_hook_active":false}')"

# Case 2: no files edited + NO DNV section -> allow (don't nag pure-conversation turns)
T=$(mk_transcript_no_edit "Some text. (verified)")
check "no files edited, no DNV section -> allow" 0 "$(run "$(payload "$T")")"

# Case 2b: no files edited + untagged DNV bullet -> BLOCK (DNV section present = enforce it)
T=$(mk_transcript_no_edit "Some text. (verified)
## Did Not Verify
- untagged item about something")
check "no files edited + untagged DNV -> block" 2 "$(run "$(payload "$T")")"

# Case 2c: no files edited + all bullets tagged (unverifiable) -> allow
T=$(mk_transcript_no_edit "Some text. (verified)
## Did Not Verify
- (unverifiable: prod-only observation) whether the deploy actually succeeded")
check "no files edited + all bullets tagged -> allow" 0 "$(run "$(payload "$T")")"

# Case 3: stop_hook_active=true -> allow (loop-guard prevents re-block)
T=$(mk_transcript "Some text.
## Did Not Verify
- untagged item about something")
check "stop_hook_active -> allow" 0 "$(run "$(payload "$T" true)")"

# Case 4: no DNV section in response -> allow
T=$(mk_transcript "$RESP_NO_DNV")
check "no DNV section -> allow" 0 "$(run "$(payload "$T")")"

# Case 5: DNV section with untagged bullet -> block (exit 2)
T=$(mk_transcript "Some text here. (verified)
## Did Not Verify
- the integration test was not run")
check "untagged DNV bullet -> block" 2 "$(run "$(payload "$T")")"

# Case 6: DNV section where ALL bullets are tagged (unverifiable) -> allow
T=$(mk_transcript "Some text here. (verified)
## Did Not Verify
- (unverifiable: prod-only observation) whether the deploy actually succeeded")
check "all bullets tagged unverifiable -> allow" 0 "$(run "$(payload "$T")")"

# Case 7: DNV section with mixed bullets (one tagged, one not) -> block
T=$(mk_transcript "Some text here. (verified)
## Did Not Verify
- (unverifiable: external system) deploy pipeline status
- tests were not run locally")
check "mixed bullets (one untagged) -> block" 2 "$(run "$(payload "$T")")"

# Case 8: DNV section with multiple untagged bullets -> block
T=$(mk_transcript "Some text here. (inferred)
## Did Not Verify
- call sites in app.py were not read
- the dedup test catches the bug")
check "multiple untagged bullets -> block" 2 "$(run "$(payload "$T")")"

# Case 9: empty DNV bullet (bare "- ") -> allow (not a claim)
T=$(mk_transcript "Some text here. (verified)
## Did Not Verify
- ")
check "bare DNV bullet (no content) -> allow" 0 "$(run "$(payload "$T")")"

# ── DNV-presence cases ───────────────────────────────────────────────────────
# When file_count >= 3 and the response has no "## Did Not Verify" section at
# all, that is treated the same as an untagged bullet: something checkable was
# silently omitted rather than resolved or tagged.

# Build a JSONL transcript with N unique Edit tool_use entries + an assistant
# text message.
mk_transcript_n_files() { # text n_files -> path
  local text="$1" n="$2" out="$TMP/t_nf_$RANDOM.jsonl" i
  : > "$out"
  for i in $(seq 1 "$n"); do
    printf '%s\n' "{\"type\":\"assistant\",\"message\":{\"content\":[{\"type\":\"tool_use\",\"name\":\"Edit\",\"input\":{\"file_path\":\"/tmp/f${i}.py\"}}]}}" >> "$out"
  done
  jq -nc --arg t "$text" '{"type":"assistant","message":{"content":[{"type":"text","text":$t}]}}' >> "$out"
  printf '%s' "$out"
}

# Test A: >=3 unique edited files, non-empty final text, NO DNV section -> block (exit 2)
T=$(mk_transcript_n_files "Done, all changes applied. (verified)" 3)
RES_A=$(printf '%s' "$(payload "$T")" | bash "$HOOK" 2>&1 >/dev/null)
check "3 files, no DNV section -> block" 2 "$(run "$(payload "$T")")"
case "$RES_A" in
  *'no "## Did Not Verify" section'*) printf 'ok   - %s\n' "3 files, no DNV -> stderr names missing section" ;;
  *) printf 'FAIL - %s (stderr: %s)\n' "3 files, no DNV -> stderr names missing section" "$RES_A"; fails=$((fails+1)) ;;
esac

# Test B: same transcript shape, but final text HAS a DNV section with one
# tagged (unverifiable) bullet -> allow (exit 0)
T=$(mk_transcript_n_files "Done, all changes applied. (verified)
## Did Not Verify
- (unverifiable: prod-only observation) whether the deploy actually succeeded" 3)
check "3 files, DNV section present with tagged bullet -> allow" 0 "$(run "$(payload "$T")")"

# Test C: only 2 edited files, no DNV section -> allow (below the file_count>=3 threshold)
T=$(mk_transcript_n_files "Done. (verified)" 2)
check "2 files, no DNV section -> allow" 0 "$(run "$(payload "$T")")"

# Test D: stop_hook_active=true, >=3 files, no DNV section -> allow (loop-guard precedence)
T=$(mk_transcript_n_files "Done, all changes applied. (verified)" 3)
check "stop_hook_active + 3 files, no DNV -> allow (guard precedence)" 0 "$(run "$(payload "$T" true)")"

# ── Presence-block loop-scoped warn-demotion (wired through the SAME
# als_loop_active_incomplete predicate #155 used for the bullet path) ───────
# mk_transcript_n_files builds assistant-only records (no genuine user
# record), so dc_file_count falls back to whole-transcript counting — the
# turn-scoping cutoff never applies here, matching the pre-existing Test A-D
# fixtures above.

# Build a transcript with N agentic-loop invocations, N_files unique Edit
# tool_use entries, then optional final text (mirrors mk_loop_transcript but
# parameterised on file count instead of a fixed single edit).
mk_loop_transcript_n_files() { # n_invocations n_files final_text -> path
  local n_inv="$1" n_files="$2" final="$3" out="$TMP/lnf_${RANDOM}.jsonl" i=0
  : > "$out"
  while [ "$i" -lt "$n_inv" ]; do
    printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:agentic-loop"}}]}}' >> "$out"
    i=$((i+1))
  done
  for i in $(seq 1 "$n_files"); do
    printf '%s\n' "{\"type\":\"assistant\",\"message\":{\"content\":[{\"type\":\"tool_use\",\"name\":\"Edit\",\"input\":{\"file_path\":\"/tmp/lf${i}.py\"}}]}}" >> "$out"
  done
  if [ -n "$final" ]; then
    jq -cn --arg t "$final" '{type:"assistant",message:{content:[{type:"text",text:$t}]}}' >> "$out"
  fi
  printf '%s' "$out"
}

# Case P1: loop active+incomplete, Stop, 3 turn-edits, NO DNV header -> exit 0,
# stdout carries additionalContext AND the discipline-warn(loop) prefix AND
# the presence message (session modified N files ... no section).
reset_loop; T=$(mk_loop_transcript_n_files 1 3 "Done, all changes applied. (verified)"); write_progress S1 in-progress 0
run_capture "$(loop_payload "$T" S1)"
check "presence: loop active+incomplete -> exit 0" 0 "$RC_OUT"
case "$OUT_OUT" in *additionalContext*) p1_ctx=1 ;; *) p1_ctx=0 ;; esac
check "presence: loop active+incomplete -> stdout has additionalContext" 1 "$p1_ctx"
case "$OUT_OUT" in *"discipline-warn(loop)"*) p1_warn=1 ;; *) p1_warn=0 ;; esac
check "presence: loop active+incomplete -> warn message tagged discipline-warn(loop)" 1 "$p1_warn"
p1_shape=$(printf '%s' "$OUT_OUT" | jq -e '.hookSpecificOutput.hookEventName == "Stop"' 2>/dev/null)
check "presence: loop active+incomplete -> stdout is valid JSON with hookEventName=Stop" "true" "$p1_shape"
p1_msg=$(printf '%s' "$OUT_OUT" | jq -e '.hookSpecificOutput.additionalContext | contains("no \"## Did Not Verify\" section")' 2>/dev/null)
check "presence: loop active+incomplete -> presence message embedded in additionalContext" "true" "$p1_msg"

# Case P2: no loop invocation in transcript, Stop, 3 turn-edits, no DNV header
# -> exit 2 (unchanged hard block outside a loop).
reset_loop; T=$(mk_transcript_n_files "Done, all changes applied. (verified)" 3)
check "presence: no loop invocation -> exit 2 unchanged" 2 "$(run "$(loop_payload "$T" S1)")"

# Case P3: loop complete (marker == invocations, session-owned), Stop, 3
# turn-edits, no DNV header -> exit 2 (completed loop is not demoted).
reset_loop; T=$(mk_loop_transcript_n_files 1 3 "Done, all changes applied. (verified)"); write_progress S1 complete 1
check "presence: loop complete (not re-armed, owned) -> exit 2" 2 "$(run "$(loop_payload "$T" S1)")"

# Case P4: demoted-path log line for the presence branch matches
# presence_block=1 would_block=1 warned=1 blocked=0.
reset_loop; : > "$CLAUDE_DISCIPLINE_LOG"; T=$(mk_loop_transcript_n_files 1 3 "Done, all changes applied. (verified)"); write_progress S1 in-progress 0
run "$(loop_payload "$T" S1)" >/dev/null 2>&1
case "$(cat "$CLAUDE_DISCIPLINE_LOG" 2>/dev/null)" in
  *"presence_block=1 would_block=1 warned=1 blocked=0"*) p4_match=1 ;;
  *) p4_match=0 ;;
esac
check "presence: demoted-path log line: presence_block=1 would_block=1 warned=1 blocked=0" 1 "$p4_match"

# ── Turn-scoping cases (file_count scoped to records after the last genuine
# user prompt, not session-cumulative) ──────────────────────────────────────

# Build a transcript with a genuine user prompt record (content is a string).
mk_user_record() { # text -> jsonl line
  jq -nc --arg t "$1" '{"type":"user","message":{"content":$t}}'
}

# Test (d): 3 edits in an EARLIER turn (before a genuine user record), final
# turn is text-only with no DNV -> allow (exit 0). The earlier edits must not
# leak into the current turn's file_count.
T="$TMP/t_earlier_turn_$RANDOM.jsonl"
{
  mk_user_record "first prompt"
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/a.py"}}]}}'
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/b.py"}}]}}'
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/c.py"}}]}}'
  mk_user_record "second prompt"
  jq -nc --arg t "Done, no edits this turn. (verified)" '{"type":"assistant","message":{"content":[{"type":"text","text":$t}]}}'
} > "$T"
check "3 edits in earlier turn, current turn text-only no DNV -> allow" 0 "$(run "$(payload "$T")")"

# Test (e): 3 edits AFTER the last genuine user record, no DNV -> block (exit 2)
T="$TMP/t_current_turn_$RANDOM.jsonl"
{
  mk_user_record "first prompt"
  jq -nc --arg t "ack" '{"type":"assistant","message":{"content":[{"type":"text","text":$t}]}}'
  mk_user_record "second prompt"
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/a.py"}}]}}'
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/b.py"}}]}}'
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/c.py"}}]}}'
  jq -nc --arg t "Done, all changes applied. (verified)" '{"type":"assistant","message":{"content":[{"type":"text","text":$t}]}}'
} > "$T"
check "3 edits after last user record, no DNV -> block" 2 "$(run "$(payload "$T")")"

# ── Header-presence cases (FIX 3: gate on the "## Did Not Verify" HEADER
# being absent, not on zero bullets — a compliant prose-only section with the
# header but no bullets must pass, not be misread as "no section") ─────────

# Test (f): 3 turn-edits + text with the DNV header present but only prose,
# no bullets -> allow (exit 0). The header's presence is the honesty
# boundary, same as an all-tagged bullet list.
T=$(mk_transcript_n_files "Done, all changes applied. (verified)
## Did Not Verify
Nothing outstanding — every claim above was checked directly." 3)
check "3 files, DNV header present with only prose (no bullets) -> allow" 0 "$(run "$(payload "$T")")"

# ── SubagentStop cases ────────────────────────────────────────────────────────
# SubagentStop payloads carry last_assistant_message directly. The hook must read
# that field, not transcript_path (which is the PARENT session transcript).
# For file_count, the hook scans agent_transcript_path; if absent/unreadable,
# file_count is treated as 0 (graceful skip — no false blocks).

subagentstop_payload() { # last_assistant_message [agent_transcript_path] -> json
  local msg="$1" atp="${2:-/nonexistent/subagent.jsonl}"
  jq -n --arg msg "$msg" --arg atp "$atp" '{
    "hook_event_name": "SubagentStop",
    "session_id": "S_sub",
    "agent_id": "agent-test",
    "transcript_path": "/nonexistent/parent.jsonl",
    "agent_transcript_path": $atp,
    "stop_hook_active": false,
    "last_assistant_message": $msg
  }'
}

# Build a subagent transcript that includes file edits (so file_count >= 1).
mk_agent_transcript() { # text -> path
  local text="$1" out="$TMP/at_$RANDOM.jsonl"
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/f.py"}}]}}' > "$out"
  jq -nc --arg t "$text" '{"type":"assistant","message":{"content":[{"type":"text","text":$t}]}}' >> "$out"
  printf '%s' "$out"
}

# Case 10: SubagentStop, no DNV in message, agent transcript has edits -> allow
AT=$(mk_agent_transcript "Work done. (verified)")
check "SubagentStop no DNV -> allow" 0 "$(run "$(subagentstop_payload "Work done. (verified)" "$AT")")"

# Case 11: SubagentStop, untagged DNV bullet, agent transcript has edits -> block (exit 2)
DNV_MSG="Some work. (verified)
## Did Not Verify
- the integration test was not run"
AT=$(mk_agent_transcript "$DNV_MSG")
check "SubagentStop untagged DNV bullet -> block" 2 "$(run "$(subagentstop_payload "$DNV_MSG" "$AT")")"

# Case 12: SubagentStop, all DNV bullets tagged -> allow
TAGGED_MSG="Some work. (verified)
## Did Not Verify
- (unverifiable: external system) deploy pipeline status"
AT=$(mk_agent_transcript "$TAGGED_MSG")
check "SubagentStop all bullets tagged -> allow" 0 "$(run "$(subagentstop_payload "$TAGGED_MSG" "$AT")")"

# Case 13: SubagentStop, agent_transcript_path absent/malformed -> must BLOCK (exit 2).
# The fix: SubagentStop no longer gates on file_count; it polices last_assistant_message
# directly. So an untagged DNV bullet in the message blocks regardless of whether
# agent_transcript_path is readable.
DNV_MSG2="Some work. (verified)
## Did Not Verify
- untagged item"
check "SubagentStop unreadable agent_transcript -> block (untagged DNV in message)" 2 "$(run "$(subagentstop_payload "$DNV_MSG2" "/nonexistent/subagent.jsonl")")"

# Case 14: Repro — agent_transcript_path is a MALFORMED file (one non-JSON line),
# last_assistant_message has an untagged DNV bullet. Under the old code, jq fails on
# the malformed file, file_count becomes 0, and the hook silently exits 0 (silent-pass
# bug). Under the fix, file_count is irrelevant for SubagentStop; the untagged DNV in
# the message must block (exit 2).
MALFORMED_TRANSCRIPT="$TMP/malformed_$RANDOM.jsonl"
printf 'this is not JSON\n' > "$MALFORMED_TRANSCRIPT"
DNV_MALFORMED="Some work. (verified)
## Did Not Verify
- the integration test was not run"
check "SubagentStop malformed agent_transcript + untagged DNV -> block (repro)" 2 "$(run "$(subagentstop_payload "$DNV_MALFORMED" "$MALFORMED_TRANSCRIPT")")"

# Regression: parent transcript has untagged DNV content, but last_assistant_message
# does NOT have a DNV section — must ALLOW. Proves we read last_assistant_message,
# not transcript_path (parent session).
PARENT_T=$(mk_transcript "Parent text. (verified)
## Did Not Verify
- untagged item in parent")
# The subagentstop message itself is clean; we point transcript_path at the dirty parent
check "SubagentStop: dirty parent transcript, clean message -> allow" 0 "$(
  AT2=$(mk_agent_transcript "Clean subagent response. (verified)")
  jq -n --arg tp "$PARENT_T" --arg msg "Clean subagent response. (verified)" --arg atp "$AT2" '{
    "hook_event_name": "SubagentStop",
    "session_id": "S_reg",
    "agent_id": "agent-reg",
    "transcript_path": $tp,
    "agent_transcript_path": $atp,
    "stop_hook_active": false,
    "last_assistant_message": $msg
  }' | bash "$HOOK" >/dev/null 2>&1; echo $?
)"

# ── Fixture-based test ───────────────────────────────────────────────────────
# Case 15: Load the real captured SubagentStop fixture, override last_assistant_message
# to a non-compliant value (untagged DNV bullet), and wire agent_transcript_path to a
# real transcript that includes file edits. Asserts exit 2.
# This keeps the fixture load-bearing so it can't drift silently from the actual payload shape.
FIXTURE="$(cd "$(dirname "$0")" && pwd)/fixtures/subagentstop_payload.json"
AT_FIX=$(mk_agent_transcript "Work. (verified)")
DNV_NON_COMPLIANT="Final response. (verified)
## Did Not Verify
- untagged item that was not resolved"
check "fixture SubagentStop non-compliant -> block" 2 "$(
  jq --arg msg "$DNV_NON_COMPLIANT" --arg atp "$AT_FIX" \
    '.last_assistant_message = $msg | .agent_transcript_path = $atp' \
    "$FIXTURE" | bash "$HOOK" >/dev/null 2>&1; echo $?
)"

# ── Loop-scoped warn-demotion (PR1) ─────────────────────────────────────────
DNV_TEXT="Some text here. (verified)
## Did Not Verify
- the integration test was not run"

# Case D1: loop active+incomplete, Stop, would-block text (untagged DNV) ->
# exit 0, stdout carries additionalContext AND the discipline-warn(loop) prefix.
# Also asserts VALID JSON shape and that the DNV bullet text is actually
# embedded inside .additionalContext (not just present somewhere in stdout) —
# a broken jq emission must fail this test, not pass by substring luck (pairs
# with the fail-toward-blocking restructure below).
reset_loop; T=$(mk_loop_transcript 1 "$DNV_TEXT"); write_progress S1 in-progress 0
run_capture "$(loop_payload "$T" S1)"
check "loop active+incomplete -> exit 0" 0 "$RC_OUT"
case "$OUT_OUT" in *additionalContext*) d1_ctx=1 ;; *) d1_ctx=0 ;; esac
check "loop active+incomplete -> stdout has additionalContext" 1 "$d1_ctx"
case "$OUT_OUT" in *"discipline-warn(loop)"*) d1_warn=1 ;; *) d1_warn=0 ;; esac
check "loop active+incomplete -> warn message tagged discipline-warn(loop)" 1 "$d1_warn"
d1_shape=$(printf '%s' "$OUT_OUT" | jq -e '.hookSpecificOutput.hookEventName == "Stop"' 2>/dev/null)
check "loop active+incomplete -> stdout is valid JSON with hookEventName=Stop" "true" "$d1_shape"
d1_bullet=$(printf '%s' "$OUT_OUT" | jq -e '.hookSpecificOutput.additionalContext | contains("the integration test was not run")' 2>/dev/null)
check "loop active+incomplete -> DNV bullet text embedded in additionalContext" "true" "$d1_bullet"

# Case D2: no loop invocation in transcript, Stop -> exit 2 (unchanged).
reset_loop; T=$(mk_transcript "$DNV_TEXT")
check "no loop invocation -> exit 2 unchanged" 2 "$(run "$(payload "$T")")"

# Case D3: loop complete (marker == invocations, session-owned), Stop -> exit 2.
reset_loop; T=$(mk_loop_transcript 1 "$DNV_TEXT"); write_progress S1 complete 1
check "loop complete (not re-armed, owned) -> exit 2" 2 "$(run "$(loop_payload "$T" S1)")"

# Case D3b (ownership conjunct coverage — G1): progress.json lives at THIS
# session's resolved path (S1's dir) but its session_id FIELD names a
# different session, status=complete, marker==invocations. The completed-loop
# exemption requires ALS_SESSION == session_id; without that conjunct, a
# foreign session's stale complete record would silently demote an unrelated
# active session. Expect: still ACTIVE -> exit 0 warn.
reset_loop; T=$(mk_loop_transcript 1 "$DNV_TEXT"); dir=$(file_dir S1); mkdir -p "$dir"
printf '{"schema_version":1,"status":"complete","session_id":"OTHER-SESSION","completed_marker":1}' > "$dir/progress.json"
run_capture "$(loop_payload "$T" S1)"
check "foreign-owned complete progress.json -> still exit 0 (ownership required for exemption)" 0 "$RC_OUT"
case "$OUT_OUT" in *additionalContext*) d3b_ctx=1 ;; *) d3b_ctx=0 ;; esac
check "foreign-owned complete progress.json -> additionalContext present (demoted, not blocked)" 1 "$d3b_ctx"

# Case D4: unreadable/absent transcript -> unchanged existing no-transcript path (exit 0).
reset_loop
check "unreadable transcript -> exit 0 unchanged" 0 "$(run "$(loop_payload "$TMP/nope.jsonl" S1)")"

# Case D5: corrupt progress.json + invocation present, Stop -> exit 0 warn.
# (Documented pairing: loop_state_guard blocks this same stop separately;
# check_verify_loop.sh only judges DNV-tag compliance.)
reset_loop; T=$(mk_loop_transcript 1 "$DNV_TEXT"); dir=$(file_dir S1); mkdir -p "$dir"
printf '{not valid json' > "$dir/progress.json"
run_capture "$(loop_payload "$T" S1)"
check "corrupt progress.json + invocation present -> exit 0 warn" 0 "$RC_OUT"
case "$OUT_OUT" in *additionalContext*) d5_ctx=1 ;; *) d5_ctx=0 ;; esac
check "corrupt progress.json + invocation present -> additionalContext present" 1 "$d5_ctx"

# Case D6: re-arm (status=complete but invocations > completed_marker), Stop -> exit 0 warn.
reset_loop; T=$(mk_loop_transcript 2 "$DNV_TEXT"); write_progress S1 complete 1
run_capture "$(loop_payload "$T" S1)"
check "re-arm (invocations>marker) -> exit 0 warn" 0 "$RC_OUT"
case "$OUT_OUT" in *additionalContext*) d6_ctx=1 ;; *) d6_ctx=0 ;; esac
check "re-arm -> additionalContext present" 1 "$d6_ctx"

# Case D7: SubagentStop with loop active, unlabelled last_assistant_message
# carrying an untagged DNV bullet -> exit 2 (workers stay block-enforced).
reset_loop; T=$(mk_loop_transcript 1 "$DNV_TEXT"); write_progress S1 in-progress 0
SUB_PAYLOAD=$(jq -n --arg msg "$DNV_TEXT" --arg tp "$T" --arg c "$CWD" '{
  "hook_event_name": "SubagentStop",
  "session_id": "S1",
  "transcript_path": $tp,
  "cwd": $c,
  "stop_hook_active": false,
  "last_assistant_message": $msg
}')
check "SubagentStop with loop active -> exit 2 (block-enforced)" 2 "$(run "$SUB_PAYLOAD")"

# Case D8: demoted-path log line matches would_block=1 warned=1 blocked=0.
reset_loop; : > "$CLAUDE_DISCIPLINE_LOG"; T=$(mk_loop_transcript 1 "$DNV_TEXT"); write_progress S1 in-progress 0
run "$(loop_payload "$T" S1)" >/dev/null 2>&1
case "$(cat "$CLAUDE_DISCIPLINE_LOG" 2>/dev/null)" in
  *"would_block=1 warned=1 blocked=0"*) d8_match=1 ;;
  *) d8_match=0 ;;
esac
check "demoted-path log line: would_block=1 warned=1 blocked=0" 1 "$d8_match"

# Case D9: a compliant turn (clean DNV — no bullets) in an active loop -> exit 0
# with NO additionalContext output (no warn spam on a passing turn).
reset_loop; T=$(mk_loop_transcript 1 "$RESP_NO_DNV"); write_progress S1 in-progress 0
run_capture "$(loop_payload "$T" S1)"
check "compliant turn in loop -> exit 0" 0 "$RC_OUT"
case "$OUT_OUT" in *additionalContext*) d9_ctx=1 ;; *) d9_ctx=0 ;; esac
check "compliant turn in loop -> NO additionalContext (no warn spam)" 0 "$d9_ctx"

# ── Pin tests (presence check must never fire outside its intended scope) ──

# Case (g): SubagentStop with a 3+-edit agent transcript and a clean message
# (no DNV section at all) -> allow. Pins that the presence check never fires
# on SubagentStop: file_count is 0 on that path (never computed from
# agent_transcript_path), so file_count>=3 can never be true there.
AT_G=$(mk_agent_transcript "Work done, no issues. (verified)")
# mk_agent_transcript only writes one Edit; extend it to 3 unique files.
{
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/g2.py"}}]}}'
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/tmp/g3.py"}}]}}'
} >> "$AT_G"
check "SubagentStop, 3+-edit agent transcript, clean message -> allow (presence never fires)" 0 "$(run "$(subagentstop_payload "Work done, no issues. (verified)" "$AT_G")")"

# Case (h): empty final text + 3 turn-edits -> allow. The empty-text skip
# (nothing was claimed, nothing to inspect) must take precedence over the
# presence check — an empty response can't be missing a section it never
# had room to include.
T=$(mk_transcript_n_files "" 3)
check "empty final text + 3 turn-edits -> allow (empty-text skip precedence)" 0 "$(run "$(payload "$T")")"

# Case P5: SubagentStop cannot reach the presence branch at all (file_count is
# always 0 on that path — case g above already pins this for a CLEAN message).
# This confirms a DIRTY (untagged-DNV) SubagentStop message still hard-blocks
# even with a loop active: the presence path structurally never fires there,
# and the bullet path's SubagentStop exclusion (event check first) already
# covers it — no new behaviour from this PR, sanity pin only.
reset_loop; write_progress S1 in-progress 1
DNV_MSG_P5="Work. (verified)
## Did Not Verify
- untagged item"
AT_P5=$(mk_agent_transcript "$DNV_MSG_P5")
check "presence: SubagentStop with loop active + untagged DNV bullet -> exit 2 (block-enforced, presence irrelevant)" 2 "$(run "$(subagentstop_payload "$DNV_MSG_P5" "$AT_P5")")"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
