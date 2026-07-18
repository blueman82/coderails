#!/bin/bash
# Behavioural test for crack_on_prose_gate.sh — feeds synthetic Stop payloads
# with fixture transcripts and asserts the prose-question contract:
#   flag stamped for this session + final assistant message asking the user a
#   question (terminal "?", first-person-modal line, or second-person request
#   phrase) -> BLOCK (exit 2, [crack-on-block] on stderr);
#   no flag, other sessions, declarative reports, self-answered rhetorical
#   questions, or questions only inside code/quotes -> ALLOW (exit 0).
# Also asserts the per-turn block cap (the infinite-loop terminator), its
# reset on a new turn, the counter-write fail-open, headless exemption, and
# Stop-only scoping.
set -u
HOOK="$(cd "$(dirname "$0")/.." && pwd)/crack_on_prose_gate.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fails=0

# Isolate flag/counter/log writes from the real ~/.claude, and defang the
# transcript-flush retry backoff so the suite runs fast.
export CLAUDE_AGENTIC_LOOP_DIR="$TMP/loopdir"
export CLAUDE_DISCIPLINE_LOG="$TMP/discipline.log"
export CLAUDE_HOOK_SLEEP_S=0
export CLAUDE_HOOK_MAX_ATTEMPTS=2

check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

stamp_flag() { # session_id
  mkdir -p "$CLAUDE_AGENTIC_LOOP_DIR/$1"
  date > "$CLAUDE_AGENTIC_LOOP_DIR/$1/crack_on_active"
}

mk_transcript() { # file final_assistant_text
  # -c is load-bearing: transcripts are JSONL and the hook's per-line
  # tolerant parse (jq -R fromjson?) drops any pretty-printed multi-line value.
  jq -nc --arg t "$2" \
    '{"type":"assistant","message":{"content":[{"type":"text","text":$t}]}}' > "$1"
}

stop_payload() { # session_id transcript_path stop_hook_active(true|false)
  jq -n --arg sid "$1" --arg tp "$2" --argjson sha "$3" \
    '{"hook_event_name":"Stop","session_id":$sid,"transcript_path":$tp,"stop_hook_active":$sha}'
}

run_stop() { # payload -> BLOCK|ALLOW (stderr captured for inspection)
  printf '%s' "$1" | bash "$HOOK" >/dev/null 2>"$TMP/stderr.last"
  if [ $? -eq 2 ]; then echo BLOCK; else echo ALLOW; fi
}

# Convenience: one-shot classify of a text for a session (fresh turn).
classify() { # session_id text -> BLOCK|ALLOW
  local t="$TMP/t-$1.jsonl"
  mk_transcript "$t" "$2"
  run_stop "$(stop_payload "$1" "$t" false)"
}

# --- Baseline: no flag -> even a naked question is allowed ---
check "no flag: terminal question -> allow" ALLOW \
  "$(classify sess-noflag "Should I proceed with option A or option B?")"

# --- POSITIVE: flag + question forms -> block ---
stamp_flag sess-q
check "flag: terminal '?' question -> block" BLOCK \
  "$(classify sess-q "I compared both hooks. Should I proceed with option A or option B?")"
check "block reason reaches stderr" yes \
  "$(grep -q '\[crack-on-block\]' "$TMP/stderr.last" && echo yes || echo no)"

stamp_flag sess-q2
check "flag: 'Want me to verify ...?' -> block" BLOCK \
  "$(classify sess-q2 "The gate only covers the tool. Want me to verify that against the actual hook config?")"

stamp_flag sess-q3
check "flag: 'Let me know which ...' (no ?) -> block" BLOCK \
  "$(classify sess-q3 "Both designs are written up above. Let me know which option you prefer.")"

stamp_flag sess-q4
check "flag: 'Do you want me to run ...' (no ?) -> block" BLOCK \
  "$(classify sess-q4 "The migration is staged. Do you want me to run it now or park it.")"

stamp_flag sess-q5
check "flag: 'Which would you prefer?' -> block" BLOCK \
  "$(classify sess-q5 "A uses the counter, B uses stop_hook_active. Which would you prefer?")"

stamp_flag sess-q6
check "flag: question before trailing DNV section -> block" BLOCK \
  "$(classify sess-q6 "$(printf 'Should I flip the flag to default-on?\n\n## Did Not Verify\n- (unverifiable: user intent) rollout preference')")"

stamp_flag sess-q7
check "flag: terminal question wrapped in closing quote -> block" BLOCK \
  "$(classify sess-q7 "$(printf 'Two candidates survived review.\nShall I merge the first one?"')")"

stamp_flag sess-q8
check "flag: 'awaiting your decision' -> block" BLOCK \
  "$(classify sess-q8 "Both PRs are green and parked. Awaiting your decision on the merge order.")"

# --- NEGATIVE: legitimate turn-ends must pass ---
stamp_flag sess-ok1
check "flag: declarative report -> allow" ALLOW \
  "$(classify sess-ok1 "I built the gate, wired hooks.json, and all 45 tests pass. (verified)")"

stamp_flag sess-ok2
check "flag: self-answered rhetorical question -> allow" ALLOW \
  "$(classify sess-ok2 "Should I have used a regex here? No — a regex cannot enumerate variable names, so the gate keys on position instead. Fix shipped and verified.")"

stamp_flag sess-ok3
check "flag: question only inside fenced code -> allow" ALLOW \
  "$(classify sess-ok3 "$(printf 'The fixture asserts the deny text:\n```\nShould I proceed?\n```\nAll suites green.')")"

stamp_flag sess-ok4
check "flag: message ending WITH a fenced code question -> allow" ALLOW \
  "$(classify sess-ok4 "$(printf 'The eval prompt is frozen verbatim below.\n```\nWhich option do you want?\n```')")"

stamp_flag sess-ok5
check "flag: question only in inline backticks -> allow" ALLOW \
  "$(classify sess-ok5 "The deny reason is \`should I proceed?\` verbatim. Shipped and logged.")"

stamp_flag sess-ok6
check "flag: question only in a blockquote -> allow" ALLOW \
  "$(classify sess-ok6 "$(printf '> Should I proceed with A or B?\nThat was the question the old gate missed. The new gate catches it.')")"

stamp_flag sess-ok7
check "flag: report + DNV + declarative LOOP-STOP ending -> allow" ALLOW \
  "$(classify sess-ok7 "$(printf 'Merged PR #1, evals GO. (verified)\n\n## Did Not Verify\n- (unverifiable: prod-only) launchd timing\n\nLOOP-STOP: complete — all units shipped')")"

stamp_flag sess-ok8
check "flag: mid-report question mark followed by prose -> allow" ALLOW \
  "$(classify sess-ok8 "$(printf 'The reviewer asked: is the counter turn-scoped? It is — the reset keys on stop_hook_active.\nEverything is merged and green.')")"

# --- Session isolation: another session's flag never blocks this one ---
stamp_flag sess-here
check "other session (no flag): question -> allow" ALLOW \
  "$(classify sess-elsewhere "Should I proceed with option A or option B?")"

# --- Loop termination: per-turn cap, then release valve, then reset ---
stamp_flag sess-cap
CAPT="$TMP/t-cap.jsonl"
mk_transcript "$CAPT" "Should I proceed with A or B?"
check "cap: attempt 1 (fresh turn) -> block" BLOCK "$(run_stop "$(stop_payload sess-cap "$CAPT" false)")"
check "cap: counter file records 1" 1 "$(cat "$CLAUDE_AGENTIC_LOOP_DIR/sess-cap/prose_question_blocks")"
check "cap: attempt 2 (rephrase) -> block" BLOCK "$(run_stop "$(stop_payload sess-cap "$CAPT" true)")"
check "cap: attempt 3 (rephrase) -> block" BLOCK "$(run_stop "$(stop_payload sess-cap "$CAPT" true)")"
check "cap: attempt 4 -> ALLOW (release valve)" ALLOW "$(run_stop "$(stop_payload sess-cap "$CAPT" true)")"
check "cap: release valve logged capped=1" yes \
  "$(grep -q 'hook=crack_on_prose_gate .*session=sess-cap .*capped=1' "$CLAUDE_DISCIPLINE_LOG" && echo yes || echo no)"
check "cap: new turn resets the counter -> block again" BLOCK "$(run_stop "$(stop_payload sess-cap "$CAPT" false)")"
check "cap: counter back to 1 after reset" 1 "$(cat "$CLAUDE_AGENTIC_LOOP_DIR/sess-cap/prose_question_blocks")"

# --- Counter-write failure fails OPEN (termination beats enforcement) ---
stamp_flag sess-badcount
mkdir -p "$CLAUDE_AGENTIC_LOOP_DIR/sess-badcount/prose_question_blocks" # dir blocks the write
BADT="$TMP/t-badcount.jsonl"
mk_transcript "$BADT" "Should I proceed with A or B?"
check "unwritable counter: question -> allow (fail-open)" ALLOW \
  "$(run_stop "$(stop_payload sess-badcount "$BADT" false)")"
check "fail-open logged err=count_write_failed" yes \
  "$(grep -q 'session=sess-badcount .*err=count_write_failed' "$CLAUDE_DISCIPLINE_LOG" && echo yes || echo no)"

# --- Headless exemption: no interactive human to protect ---
stamp_flag sess-headless
HT="$TMP/t-headless.jsonl"
mk_transcript "$HT" "Should I proceed with A or B?"
check "CODERAILS_HEADLESS_RUN=1 -> allow" ALLOW \
  "$(printf '%s' "$(stop_payload sess-headless "$HT" false)" | CODERAILS_HEADLESS_RUN=1 bash "$HOOK" >/dev/null 2>/dev/null; [ $? -eq 2 ] && echo BLOCK || echo ALLOW)"

# --- Scoping: Stop-only, and degenerate payloads stand aside ---
stamp_flag sess-scope
ST="$TMP/t-scope.jsonl"
mk_transcript "$ST" "Should I proceed with A or B?"
check "SubagentStop event -> allow (out of scope)" ALLOW \
  "$(printf '%s' "$(jq -n --arg sid sess-scope --arg tp "$ST" '{"hook_event_name":"SubagentStop","session_id":$sid,"transcript_path":$tp,"last_assistant_message":"Should I proceed?"}')" | bash "$HOOK" >/dev/null 2>/dev/null; [ $? -eq 2 ] && echo BLOCK || echo ALLOW)"
check "missing transcript -> allow" ALLOW \
  "$(run_stop "$(stop_payload sess-scope "$TMP/nonexistent.jsonl" false)")"
check "no session_id -> allow" ALLOW \
  "$(printf '%s' "$(jq -n --arg tp "$ST" '{"hook_event_name":"Stop","transcript_path":$tp}')" | bash "$HOOK" >/dev/null 2>/dev/null; [ $? -eq 2 ] && echo BLOCK || echo ALLOW)"
check "empty stdin exits 0" 0 "$(printf '' | bash "$HOOK" >/dev/null 2>/dev/null; echo $?)"

# --- Audit trail: a block writes a blocked=1 log line ---
check "block logged with hook=crack_on_prose_gate blocked=1" yes \
  "$(grep -q 'hook=crack_on_prose_gate .*session=sess-q .*blocked=1' "$CLAUDE_DISCIPLINE_LOG" && echo yes || echo no)"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
