#!/bin/bash
# Behavioural test for check_confidence_labels.sh — feeds synthetic Stop payloads
# with fixture transcripts and asserts exit codes. All state lives under a temp dir.
set -u
HOOK="$(cd "$(dirname "$0")/.." && pwd)/check_confidence_labels.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_AGENTIC_LOOP_DIR="$TMP/state"
export CLAUDE_DISCIPLINE_LOG="$TMP/discipline.log"
export CLAUDE_HOOK_MAX_ATTEMPTS=1   # no flush-race retry sleeps in tests
export CLAUDE_HOOK_SLEEP_S=0
CWD="/work/project"
SLUG="-work-project"
fails=0

# Build a synthetic JSONL transcript with one assistant text message.
mk_transcript() { # text -> path
  local text="$1" out="$TMP/t_$RANDOM.jsonl"
  jq -nc --arg t "$text" '{"type":"assistant","message":{"content":[{"type":"text","text":$t}]}}' > "$out"
  printf '%s' "$out"
}

payload() { # transcript_path [stop_hook_active] -> json
  local tp="$1" sha="${2:-false}"
  printf '{"transcript_path":"%s","session_id":"S1","cwd":"%s","stop_hook_active":%s}' "$tp" "$CWD" "$sha"
}

# ── Loop-scoped warn-demotion fixture helpers (mirrors loop_stall_guard.test.sh) ──
file_dir() { printf '%s/%s/%s' "$CLAUDE_AGENTIC_LOOP_DIR" "$SLUG" "$1"; }   # session_id -> dir
mk_loop_transcript() { # n_invocations final_text -> path
  local n="$1" final="$2" out="$TMP/lt_${RANDOM}.jsonl" i=0
  : > "$out"
  while [ "$i" -lt "$n" ]; do
    printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:agentic-loop"}}]}}' >> "$out"
    i=$((i+1))
  done
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

run() { # json -> exit code
  printf '%s' "$1" | bash "$HOOK" >/dev/null 2>&1; echo $?
}

run_stderr() { # json -> sets RC_ERR and ERR_ERR (stderr)
  ERR_ERR=$(printf '%s' "$1" | bash "$HOOK" 2>&1 >/dev/null)
  RC_ERR=$?
}

check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected exit %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

LONG_TEXT=$(printf '%200s' | tr ' ' 'x')  # exactly 200 chars — meets the >=200 threshold

# Case 1: long response WITH a (verified) label -> allow (exit 0)
T=$(mk_transcript "${LONG_TEXT} (verified) and more text here")
check "labelled long response -> allow" 0 "$(run "$(payload "$T")")"

# Case 2: long response with (inferred) label -> allow
T=$(mk_transcript "${LONG_TEXT} (inferred) something")
check "inferred label -> allow" 0 "$(run "$(payload "$T")")"

# Case 3: long response with (guess) label -> allow
T=$(mk_transcript "${LONG_TEXT} (guess) something")
check "guess label -> allow" 0 "$(run "$(payload "$T")")"

# Case 4: long response with NO label -> block (exit 2)
T=$(mk_transcript "${LONG_TEXT}")
check "unlabelled long response -> block" 2 "$(run "$(payload "$T")")"

# Case 5: short response (< 200 chars) with NO label -> allow
T=$(mk_transcript "Short response without labels.")
check "short unlabelled response -> allow" 0 "$(run "$(payload "$T")")"

# Case 6: no transcript file -> allow
check "no transcript -> allow" 0 "$(run '{"transcript_path":"/nonexistent/path.jsonl","session_id":"S1"}')"

# Case 6b: stop_hook_active=true -> allow even with unlabelled long text (loop-guard)
T=$(mk_transcript "${LONG_TEXT}")
check "stop_hook_active -> allow" 0 "$(run "$(payload "$T" true)")"

# Case 7: empty transcript_path -> allow
check "empty transcript_path -> allow" 0 "$(run '{"session_id":"S1"}')"

# ── SubagentStop cases ────────────────────────────────────────────────────────
# Build a SubagentStop payload using last_assistant_message directly (no transcript
# parsing). The parent transcript_path is intentionally a non-existent path to prove
# the hook reads last_assistant_message, not transcript_path.

subagentstop_payload() { # last_assistant_message -> json
  local msg="$1"
  jq -n --arg msg "$msg" '{
    "hook_event_name": "SubagentStop",
    "session_id": "S_sub",
    "agent_id": "agent-test",
    "transcript_path": "/nonexistent/parent.jsonl",
    "agent_transcript_path": "/nonexistent/subagent.jsonl",
    "stop_hook_active": false,
    "last_assistant_message": $msg
  }'
}

# Case 8: SubagentStop with labelled long message -> allow
check "SubagentStop labelled message -> allow" 0 "$(run "$(subagentstop_payload "${LONG_TEXT} (verified) claim")")"

# Case 9: SubagentStop with unlabelled long message -> block (exit 2)
check "SubagentStop unlabelled message -> block" 2 "$(run "$(subagentstop_payload "${LONG_TEXT}")")"

# Case 10: SubagentStop with (inferred) label -> allow
check "SubagentStop inferred label -> allow" 0 "$(run "$(subagentstop_payload "${LONG_TEXT} (inferred) claim")")"

# Case 11: SubagentStop with (guess) label -> allow
check "SubagentStop guess label -> allow" 0 "$(run "$(subagentstop_payload "${LONG_TEXT} (guess) claim")")"

# Case 12: SubagentStop with short message (< 200 chars) -> allow regardless of labels
check "SubagentStop short message -> allow" 0 "$(run "$(subagentstop_payload "Short subagent reply.")")"

# Regression: parent transcript is compliant (has a label in its text), but
# last_assistant_message is NOT compliant — must still BLOCK.
# This proves the script reads last_assistant_message, not transcript_path.
COMPLIANT_TRANSCRIPT=$(mk_transcript "${LONG_TEXT} (verified) parent content")
check "SubagentStop: compliant parent but non-compliant last_assistant_message -> block" 2 "$(
  jq -n --arg tp "$COMPLIANT_TRANSCRIPT" --arg msg "${LONG_TEXT}" '{
    "hook_event_name": "SubagentStop",
    "session_id": "S_reg",
    "agent_id": "agent-reg",
    "transcript_path": $tp,
    "agent_transcript_path": "/nonexistent/subagent.jsonl",
    "stop_hook_active": false,
    "last_assistant_message": $msg
  }' | bash "$HOOK" >/dev/null 2>&1; echo $?
)"

# ── Loop-scoped warn-demotion (PR1) ─────────────────────────────────────────
LONG_TEXT2=$(printf '%200s' | tr ' ' 'y')  # distinct filler from LONG_TEXT above

# Case D1: loop active+incomplete, Stop, would-block text -> exit 0, stdout
# carries additionalContext AND the discipline-warn(loop) prefix. Also asserts
# the emitted stdout is VALID JSON with the expected shape (not just a
# substring match) — a broken jq emission must fail this test, not pass by
# substring luck (pairs with the fail-toward-blocking restructure below).
reset_loop() { rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"; }
reset_loop; T=$(mk_loop_transcript 1 "$LONG_TEXT2"); write_progress S1 in-progress 0
run_capture "$(loop_payload "$T" S1)"
check "loop active+incomplete -> exit 0" 0 "$RC_OUT"
case "$OUT_OUT" in *additionalContext*) d1_ctx=1 ;; *) d1_ctx=0 ;; esac
check "loop active+incomplete -> stdout has additionalContext" 1 "$d1_ctx"
case "$OUT_OUT" in *"discipline-warn(loop)"*) d1_warn=1 ;; *) d1_warn=0 ;; esac
check "loop active+incomplete -> warn message tagged discipline-warn(loop)" 1 "$d1_warn"
d1_shape=$(printf '%s' "$OUT_OUT" | jq -e '.hookSpecificOutput.hookEventName == "Stop"' 2>/dev/null)
check "loop active+incomplete -> stdout is valid JSON with hookEventName=Stop" "true" "$d1_shape"

# Case D2: no loop invocation in transcript, Stop -> exit 2 (unchanged).
reset_loop; T=$(mk_transcript "$LONG_TEXT2")
check "no loop invocation -> exit 2 unchanged" 2 "$(run "$(payload "$T")")"

# Case D3: loop complete (marker == invocations, session-owned), Stop -> exit 2.
reset_loop; T=$(mk_loop_transcript 1 "$LONG_TEXT2"); write_progress S1 complete 1
check "loop complete (not re-armed, owned) -> exit 2" 2 "$(run "$(loop_payload "$T" S1)")"

# Case D3b (ownership conjunct coverage — G1): progress.json lives at THIS
# session's resolved path (S1's dir) but its session_id FIELD names a
# different session, status=complete, marker==invocations (not re-armed by
# the marker check alone). The completed-loop exemption in
# als_loop_active_incomplete requires ALS_SESSION == session_id; without that
# conjunct, a foreign session's stale complete record would silently demote
# an unrelated active session. Expect: still ACTIVE -> exit 0 warn (the
# exemption does NOT apply when the file's session_id doesn't match).
reset_loop; T=$(mk_loop_transcript 1 "$LONG_TEXT2"); dir=$(file_dir S1); mkdir -p "$dir"
printf '{"schema_version":1,"status":"complete","session_id":"OTHER-SESSION","completed_marker":1}' > "$dir/progress.json"
run_capture "$(loop_payload "$T" S1)"
check "foreign-owned complete progress.json -> still exit 0 (ownership required for exemption)" 0 "$RC_OUT"
case "$OUT_OUT" in *additionalContext*) d3b_ctx=1 ;; *) d3b_ctx=0 ;; esac
check "foreign-owned complete progress.json -> additionalContext present (demoted, not blocked)" 1 "$d3b_ctx"

# Case D4: unreadable/absent transcript -> unchanged existing early-allow (exit 0).
reset_loop
check "unreadable transcript -> exit 0 unchanged" 0 "$(run "$(loop_payload "$TMP/nope.jsonl" S1)")"

# Case D5: corrupt progress.json + invocation present, Stop -> exit 0 warn.
# (Documented pairing: loop_state_guard blocks this same stop separately via
# als_gate_no_transcript/other gates — check_confidence_labels.sh only judges
# label presence, and per the predicate contract an unreadable/corrupt
# progress.json with invocations>0 still reads as active -> warn here.)
reset_loop; T=$(mk_loop_transcript 1 "$LONG_TEXT2"); dir=$(file_dir S1); mkdir -p "$dir"
printf '{not valid json' > "$dir/progress.json"
run_capture "$(loop_payload "$T" S1)"
check "corrupt progress.json + invocation present -> exit 0 warn" 0 "$RC_OUT"
case "$OUT_OUT" in *additionalContext*) d5_ctx=1 ;; *) d5_ctx=0 ;; esac
check "corrupt progress.json + invocation present -> additionalContext present" 1 "$d5_ctx"

# Case D6: re-arm (status=complete but invocations > completed_marker), Stop -> exit 0 warn.
reset_loop; T=$(mk_loop_transcript 2 "$LONG_TEXT2"); write_progress S1 complete 1
run_capture "$(loop_payload "$T" S1)"
check "re-arm (invocations>marker) -> exit 0 warn" 0 "$RC_OUT"
case "$OUT_OUT" in *additionalContext*) d6_ctx=1 ;; *) d6_ctx=0 ;; esac
check "re-arm -> additionalContext present" 1 "$d6_ctx"

# Case D7: SubagentStop with loop active, unlabelled long last_assistant_message
# -> exit 2 (workers stay block-enforced; demotion branch is Stop-only).
reset_loop; T=$(mk_loop_transcript 1 "$LONG_TEXT2"); write_progress S1 in-progress 0
SUB_PAYLOAD=$(jq -n --arg msg "$LONG_TEXT2" --arg tp "$T" --arg c "$CWD" '{
  "hook_event_name": "SubagentStop",
  "session_id": "S1",
  "transcript_path": $tp,
  "cwd": $c,
  "stop_hook_active": false,
  "last_assistant_message": $msg
}')
check "SubagentStop with loop active -> exit 2 (block-enforced)" 2 "$(run "$SUB_PAYLOAD")"

# Case D8: demoted-path log line matches would_block=1 warned=1 blocked=0.
reset_loop; : > "$CLAUDE_DISCIPLINE_LOG"; T=$(mk_loop_transcript 1 "$LONG_TEXT2"); write_progress S1 in-progress 0
run "$(loop_payload "$T" S1)" >/dev/null 2>&1
case "$(cat "$CLAUDE_DISCIPLINE_LOG" 2>/dev/null)" in
  *"would_block=1 warned=1 blocked=0"*) d8_match=1 ;;
  *) d8_match=0 ;;
esac
check "demoted-path log line: would_block=1 warned=1 blocked=0" 1 "$d8_match"

# Case D9: a compliant (labelled) turn in an active loop -> exit 0 with NO
# additionalContext output (no warn spam on a passing turn).
reset_loop; T=$(mk_loop_transcript 1 "${LONG_TEXT2} (verified) claim"); write_progress S1 in-progress 0
run_capture "$(loop_payload "$T" S1)"
check "compliant turn in loop -> exit 0" 0 "$RC_OUT"
case "$OUT_OUT" in *additionalContext*) d9_ctx=1 ;; *) d9_ctx=0 ;; esac
check "compliant turn in loop -> NO additionalContext (no warn spam)" 0 "$d9_ctx"

# ── event= telemetry token ──────────────────────────────────────────────
# Every log line this hook writes carries which hook_event_name produced
# it, so discipline.log consumers can distinguish Stop from SubagentStop
# without re-deriving it from surrounding context.

# Stop payload, unlabelled long text (blocked path) -> log line carries event=Stop.
: > "$CLAUDE_DISCIPLINE_LOG"
T=$(mk_transcript "$LONG_TEXT")
run "$(payload "$T")" >/dev/null 2>&1
case "$(cat "$CLAUDE_DISCIPLINE_LOG" 2>/dev/null)" in
  *"hook=confidence_labels event=Stop"*) evt_stop_match=1 ;;
  *) evt_stop_match=0 ;;
esac
check "Stop payload -> log line carries event=Stop" 1 "$evt_stop_match"

# SubagentStop payload, unlabelled long message (blocked path) -> log line
# carries event=SubagentStop.
: > "$CLAUDE_DISCIPLINE_LOG"
run "$(subagentstop_payload "${LONG_TEXT}")" >/dev/null 2>&1
case "$(cat "$CLAUDE_DISCIPLINE_LOG" 2>/dev/null)" in
  *"hook=confidence_labels event=SubagentStop"*) evt_sub_match=1 ;;
  *) evt_sub_match=0 ;;
esac
check "SubagentStop payload -> log line carries event=SubagentStop" 1 "$evt_sub_match"

# ── blocked-path stderr message content ─────────────────────────────────
# The block message is meant to be actionable (names the rule, gives a
# worked example), not just a generic "add labels" line — pin its content,
# not only the exit code, so a regression to a vague message is caught.
T=$(mk_transcript "$LONG_TEXT")
run_stderr "$(payload "$T")"
check "blocked path -> exit 2" 2 "$RC_ERR"
case "$ERR_ERR" in *"[discipline-block]"*) msg_tag=1 ;; *) msg_tag=0 ;; esac
check "blocked path -> stderr contains [discipline-block]" 1 "$msg_tag"
case "$ERR_ERR" in *"Rule (CLAUDE.md)"*) msg_rule=1 ;; *) msg_rule=0 ;; esac
check "blocked path -> stderr contains Rule (CLAUDE.md)" 1 "$msg_rule"

# ── Headless-run exemption (CODERAILS_HEADLESS_RUN=1) ────────────────────────
# Dashboard-spawned `claude -p` runs set this env var so the discipline text
# gates don't displace the run's answer with a repair turn. Gate fires before
# stdin is even read (cheap skip-gate first).

# Case H1: CODERAILS_HEADLESS_RUN=1 + a payload that would otherwise BLOCK
# (unlabelled long text) -> exit 0.
: > "$CLAUDE_DISCIPLINE_LOG"
T=$(mk_transcript "$LONG_TEXT")
check "headless + would-block payload -> exit 0" 0 "$(CODERAILS_HEADLESS_RUN=1 run "$(payload "$T")")"

# Case H2: same headless run -> log line records skipped=headless.
case "$(cat "$CLAUDE_DISCIPLINE_LOG" 2>/dev/null)" in
  *"skipped=headless"*) h2_match=1 ;;
  *) h2_match=0 ;;
esac
check "headless run -> log line records skipped=headless" 1 "$h2_match"

# Case H3: WITHOUT the flag, the same payload still blocks (exit 2) — existing
# behaviour unchanged.
T=$(mk_transcript "$LONG_TEXT")
check "no headless flag, would-block payload -> exit 2 unchanged" 2 "$(run "$(payload "$T")")"

# Case H4: CODERAILS_HEADLESS_RUN set to something other than "1" -> no exemption,
# still blocks (exact-match gate, not a truthy check).
T=$(mk_transcript "$LONG_TEXT")
check "CODERAILS_HEADLESS_RUN=0 -> not exempt, exit 2" 2 "$(CODERAILS_HEADLESS_RUN=0 run "$(payload "$T")")"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
