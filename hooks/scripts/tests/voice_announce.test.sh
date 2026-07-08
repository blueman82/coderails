#!/bin/bash
# Behavioural test for voice_announce.sh — feeds synthetic Stop payloads with
# fixture transcripts (an agentic-loop invocation + a final assistant message)
# and asserts on a stub `say`'s recorded argv, plus exit codes and timing.
# State lives under a temp dir, never the repo — same conventions as
# loop_stall_guard.test.sh (its closest sibling).
set -u
HOOK="$(cd "$(dirname "$0")/.." && pwd)/voice_announce.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_AGENTIC_LOOP_DIR="$TMP/state"
export CLAUDE_DISCIPLINE_LOG="$TMP/discipline.log"
export CLAUDE_HOOK_MAX_ATTEMPTS=1   # no flush-race retry sleeps in tests
CWD="/work/project"
SLUG="-work-project"
file_dir() { printf '%s/%s/%s' "$CLAUDE_AGENTIC_LOOP_DIR" "$SLUG" "$1"; }   # session_id -> dir
fails=0

# Build a transcript: N agentic-loop Skill invocations, then a final assistant
# text message with the given body ("" = no final text message).
mk_transcript() { # n_invocations final_text -> path
  local n="$1" final="$2" out="$TMP/t_${RANDOM}.jsonl" i=0
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
mk_other_transcript() {
  local out="$TMP/other_${RANDOM}.jsonl"
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:prep"}}]}}' > "$out"
  printf '%s' "$out"
}
payload() { # transcript session_id [stop_hook_active]
  printf '{"transcript_path":"%s","session_id":"%s","cwd":"%s","stop_hook_active":%s}' \
    "$1" "$2" "$CWD" "${3:-false}"
}
write_file() { # status session_id completed_marker
  local dir; dir=$(file_dir "$2")
  mkdir -p "$dir"
  printf '{"schema_version":1,"status":"%s","session_id":"%s","completed_marker":%s}' "$1" "$2" "$3" > "$dir/progress.json"
}
check() { if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"; else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi; }
reset() { rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"; rm -f "$SAY_LOG" "$CLAUDE_DISCIPLINE_LOG"; }

# --- Stub `say` on PATH: records its argv (one call per line) to SAY_LOG. ---
STUB_BIN="$TMP/stub-bin"
mkdir -p "$STUB_BIN"
SAY_LOG="$TMP/say.log"
cat > "$STUB_BIN/say" <<'EOF'
#!/bin/bash
echo "$*" >> "$SAY_LOG"
EOF
chmod +x "$STUB_BIN/say"
export SAY_LOG
STUB_PATH="$STUB_BIN:$PATH"

# --- A second stub `say` that sleeps 3s before recording, to prove the hook
# itself returns fast (backgrounded/detached) despite a slow `say`. ---
SLOW_BIN="$TMP/slow-bin"
mkdir -p "$SLOW_BIN"
cat > "$SLOW_BIN/say" <<'EOF'
#!/bin/bash
sleep 3
echo "$*" >> "$SAY_LOG"
EOF
chmod +x "$SLOW_BIN/say"
SLOW_PATH="$SLOW_BIN:$PATH"

# run: invoke the hook with a given PATH and payload, capture exit code.
run() { # path payload -> exit code
  env PATH="$1" bash -c 'echo "$1" | bash "$2" >/dev/null 2>&1; echo $?' _ "$2" "$HOOK"
}

# The hook backgrounds `say` and returns before it necessarily runs, so poll
# briefly for the stub's async write rather than racing it.
#
# Optional arg = the expected call count to wait for. When given, poll until
# the count REACHES that value (not merely becomes >0). This matters when an
# assertion expects >1 call: two backgrounded `say` writes can land in
# separate poll ticks, and a plain ">0 -> break" returns after the first
# write, reading a low count under load (the flaky "expected 2, got 1"). With
# an explicit target the poll waits for the second write. When no arg is given
# the old ">0 -> break" behaviour is kept, which is correct for the 0- and
# 1-call assertions (0-call ones exhaust the poll and return 0 either way).
# The returned count is the ACTUAL line count, so an over-count (more writes
# than want) is still rejected by check's exact equality. Residual: a write
# landing strictly after the tick that first satisfies want is not seen (the
# poll has already broken) — same blind spot the old >0-break had, not a new one.
say_call_count() {
  local want="${1:-}" i=0 n
  while [ "$i" -lt 20 ]; do
    n=$([ -f "$SAY_LOG" ] && wc -l < "$SAY_LOG" | tr -d ' ' || echo 0)
    if [ -n "$want" ]; then
      [ "$n" -ge "$want" ] && break
    else
      [ "$n" -gt 0 ] && break
    fi
    sleep 0.1
    i=$((i+1))
  done
  echo "${n:-0}"
}

# Last discipline-log line for hook=voice_announce (best-effort poll: the log
# write is synchronous in the hook itself, so no race with say_call_count's
# async wait is needed, but a tiny poll costs nothing and matches the style).
last_voice_log_line() {
  grep 'hook=voice_announce' "$CLAUDE_DISCIPLINE_LOG" 2>/dev/null | tail -1
}

# A minimal PATH containing every coreutil the hook/lib needs, but NOT jq —
# proves fail-open (never blocks, never invokes say) when jq is unavailable.
NOJQ_BIN="$TMP/nojq-bin"
mkdir -p "$NOJQ_BIN"
for _t in bash sh dirname grep sleep tail printf mv rm cat sed awk date mkdir env basename cut tr paste mktemp wc; do
  _p=$(command -v "$_t" 2>/dev/null)
  [ -n "$_p" ] && ln -sf "$_p" "$NOJQ_BIN/$_t"
done

# ── Path 1: complete ──────────────────────────────────────────────────────
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — all PRs merged"); write_file in-progress S1 0
rc=$(run "$STUB_PATH" "$(payload "$T" S1)")
check "complete: hook exits 0" 0 "$rc"
check "complete: exactly one say call" 1 "$(say_call_count)"
check "complete: phrase mentions completion" 1 "$(grep -qi 'complete' "$SAY_LOG" && echo 1 || echo 0)"
check "complete: phrase does NOT say stall" 0 "$(grep -qiE 'stall|stuck' "$SAY_LOG" && echo 1 || echo 0)"
check "complete: phrase does NOT say waiting" 0 "$(grep -qiE 'wait' "$SAY_LOG" && echo 1 || echo 0)"

# ── Path 2: approval/awaiting ─────────────────────────────────────────────
reset; T=$(mk_transcript 1 "Work paused.
LOOP-STOP: approval-gate — need human ok"); write_file in-progress S1 0
rc=$(run "$STUB_PATH" "$(payload "$T" S1)")
check "approval-gate: hook exits 0" 0 "$rc"
check "approval-gate: exactly one say call" 1 "$(say_call_count)"
check "approval-gate: phrase mentions waiting" 1 "$(grep -qiE 'wait' "$SAY_LOG" && echo 1 || echo 0)"
check "approval-gate: phrase does NOT say complete" 0 "$(grep -qiE 'complete' "$SAY_LOG" && echo 1 || echo 0)"
check "approval-gate: phrase does NOT say stall" 0 "$(grep -qiE 'stall|stuck' "$SAY_LOG" && echo 1 || echo 0)"

reset; T=$(mk_transcript 1 "Still waiting.
LOOP-STOP: awaiting-input — need the plan confirmed"); write_file in-progress S1 0
rc=$(run "$STUB_PATH" "$(payload "$T" S1)")
check "awaiting-input: hook exits 0" 0 "$rc"
check "awaiting-input: exactly one say call" 1 "$(say_call_count)"
check "awaiting-input: phrase mentions waiting" 1 "$(grep -qiE 'wait' "$SAY_LOG" && echo 1 || echo 0)"

# ── Path: hard-stop (in-vocab but had NO announce arm — item 1) ──────────
reset; T=$(mk_transcript 1 "Stopping here.
LOOP-STOP: hard-stop — unrecoverable error"); write_file in-progress S1 0
rc=$(run "$STUB_PATH" "$(payload "$T" S1)")
check "hard-stop: hook exits 0" 0 "$rc"
check "hard-stop: exactly one say call" 1 "$(say_call_count)"
check "hard-stop: phrase mentions a stop" 1 "$(grep -qiE 'stop' "$SAY_LOG" && echo 1 || echo 0)"
check "hard-stop: phrase does NOT say stall" 0 "$(grep -qiE 'stall|stuck' "$SAY_LOG" && echo 1 || echo 0)"
check "hard-stop: phrase does NOT say complete" 0 "$(grep -qiE 'complete' "$SAY_LOG" && echo 1 || echo 0)"

# ── Path 3: stall (active loop, no valid declaration) ─────────────────────
reset; T=$(mk_transcript 1 "Here is a status update with no declaration."); write_file in-progress S1 0
rc=$(run "$STUB_PATH" "$(payload "$T" S1)")
check "stall: hook exits 0" 0 "$rc"
check "stall: exactly one say call" 1 "$(say_call_count)"
check "stall: phrase mentions stall" 1 "$(grep -qiE 'stall|stuck' "$SAY_LOG" && echo 1 || echo 0)"
check "stall: phrase does NOT say complete" 0 "$(grep -qiE 'complete' "$SAY_LOG" && echo 1 || echo 0)"
check "stall: phrase does NOT say waiting" 0 "$(grep -qiE 'wait' "$SAY_LOG" && echo 1 || echo 0)"

# Out-of-vocab category also counts as "no valid declaration" -> stall path.
reset; T=$(mk_transcript 1 "LOOP-STOP: paused — taking a break"); write_file in-progress S1 0
rc=$(run "$STUB_PATH" "$(payload "$T" S1)")
check "out-of-vocab declaration: still stall path" 1 "$(say_call_count)"

# ── Non-loop silence: every non-loop case must produce ZERO say calls ─────
reset
run "$STUB_PATH" "$(payload "$TMP/nope.jsonl" S1)" >/dev/null
check "no transcript -> zero say calls" 0 "$(say_call_count)"

reset; T=$(mk_other_transcript)
run "$STUB_PATH" "$(payload "$T" S1)" >/dev/null
check "non-loop skill -> zero say calls" 0 "$(say_call_count)"

reset; T=$(mk_transcript 1 ""); write_file complete S1 1
run "$STUB_PATH" "$(payload "$T" S1)" >/dev/null
check "loop complete off-switch -> zero say calls" 0 "$(say_call_count)"

reset; T=$(mk_transcript 1 "no declaration here"); write_file in-progress S1 0
run "$STUB_PATH" "$(payload "$T" S1 true)" >/dev/null
check "stop_hook_active -> zero say calls" 0 "$(say_call_count)"

# ── Debounce: an immediate repeat of the SAME announcement must not re-speak ──
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — all PRs merged"); write_file in-progress S1 0
run "$STUB_PATH" "$(payload "$T" S1)" >/dev/null
run "$STUB_PATH" "$(payload "$T" S1)" >/dev/null
check "debounce: immediate repeat suppressed (still 1 call)" 1 "$(say_call_count)"

# A DIFFERENT category right after must still speak (debounce is per-kind, not global).
reset; T1=$(mk_transcript 1 "Here is a status update with no declaration."); write_file in-progress S1 0
run "$STUB_PATH" "$(payload "$T1" S1)" >/dev/null
T2=$(mk_transcript 1 "All done.
LOOP-STOP: complete — all PRs merged")
run "$STUB_PATH" "$(payload "$T2" S1)" >/dev/null
check "debounce: different kind still speaks (2 calls total)" 2 "$(say_call_count 2)"

# Debounce EXPIRY (item 7): CLAUDE_VOICE_DEBOUNCE_SECONDS=0 means the window
# never suppresses — an immediate repeat of the SAME kind still speaks again.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — all PRs merged"); write_file in-progress S1 0
CLAUDE_VOICE_DEBOUNCE_SECONDS=0 run "$STUB_PATH" "$(payload "$T" S1)" >/dev/null
CLAUDE_VOICE_DEBOUNCE_SECONDS=0 run "$STUB_PATH" "$(payload "$T" S1)" >/dev/null
check "debounce expiry (window=0): repeat still speaks (2 calls)" 2 "$(say_call_count 2)"

# say_call_count contract: the want-arg poll returns the ACTUAL count, so an
# over-count (more writes than want) is still rejected by check's exact
# equality — the wait target must never mask a spurious extra say call. Seed
# SAY_LOG with 3 lines and assert say_call_count 2 reports 3 (not a clamped 2).
reset; printf 'a\nb\nc\n' > "$SAY_LOG"
check "say_call_count returns true count (over-count not masked by want target)" 3 "$(say_call_count 2)"
reset

# Debounce EXPIRY via a stale marker: a marker timestamped far in the past
# (older than the debounce window) must not suppress a fresh announcement.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — all PRs merged"); write_file in-progress S1 0
dir=$(file_dir S1); mkdir -p "$dir"
printf '1' > "$dir/voice_announce_complete.last"   # epoch second 1 -> ancient
run "$STUB_PATH" "$(payload "$T" S1)" >/dev/null
check "debounce expiry (stale marker): still speaks" 1 "$(say_call_count)"

# ── jq absent -> fail-open: hook exits 0, no say call ─────────────────────
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — all PRs merged"); write_file in-progress S1 0
rc=$(run "$NOJQ_BIN:$PATH" "$(payload "$T" S1)")
check "jq absent -> still allow (fail-open)" 0 "$rc"
check "jq absent -> zero say calls" 0 "$(say_call_count)"

# ── Extract failure (item 2): the loop is registered (invocation count > 0,
# so als_gate_require_active_loop passes) but the transcript has NO assistant
# TEXT message at all — e.g. the turn only did tool calls, or the flush race
# hasn't landed the final text yet. als_stable_last_text legitimately returns
# empty here (no parse error, just nothing to find). This must NOT be misread
# as a stall — empty extraction announces NOTHING, with a distinct log reason.
reset; T="$TMP/notext_$RANDOM.jsonl"
printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:agentic-loop"}}]}}' > "$T"
write_file in-progress S1 0
rc=$(run "$STUB_PATH" "$(payload "$T" S1)")
check "extract failure: hook exits 0" 0 "$rc"
check "extract failure: zero say calls (not misread as stall)" 0 "$(say_call_count)"
check "extract failure: log reason=extract_failed" 1 "$(last_voice_log_line | grep -qE 'reason=extract_failed' && echo 1 || echo 0)"

# ── say binary absent (item 3): announce() must not log announced=1 before
# checking say exists. On a say-less PATH, exit 0, no crash, and the log
# carries a distinct reason rather than a false announced=1.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — all PRs merged"); write_file in-progress S1 0
NOSAY_BIN="$TMP/nosay-bin"; mkdir -p "$NOSAY_BIN"
for _t in bash sh dirname grep sleep tail printf mv rm cat sed awk date mkdir env basename cut tr paste mktemp wc jq; do
  _p=$(command -v "$_t" 2>/dev/null)
  [ -n "$_p" ] && ln -sf "$_p" "$NOSAY_BIN/$_t"
done
rc=$(run "$NOSAY_BIN" "$(payload "$T" S1)")
check "say absent: hook exits 0" 0 "$rc"
check "say absent: log reason=no_say_binary (not announced=1)" 1 "$(last_voice_log_line | grep -qE 'reason=no_say_binary' && echo 1 || echo 0)"
check "say absent: log does NOT claim announced=1" 0 "$(last_voice_log_line | grep -qE 'announced=1' && echo 1 || echo 0)"

# ── Debounce marker write failure (item 4): an unwritable state dir must not
# silently disable debouncing while the log still claims a normal announcement.
# Fail-open direction is to still SPEAK (audible spam beats a silently dead
# feature) but the log must carry a distinct reason.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — all PRs merged"); write_file in-progress S1 0
dir=$(file_dir S1)
chmod 555 "$dir"
rc=$(run "$STUB_PATH" "$(payload "$T" S1)")
chmod 755 "$dir"   # restore so cleanup can proceed
check "debounce write failure: hook exits 0" 0 "$rc"
check "debounce write failure: still announces (fail-open to speak)" 1 "$(say_call_count)"
check "debounce write failure: log reason=debounce_write_failed" 1 "$(last_voice_log_line | grep -qE 'reason=debounce_write_failed' && echo 1 || echo 0)"

# ── Non-blocking: hook returns fast even though `say` sleeps 3s ───────────
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — all PRs merged"); write_file in-progress S1 0
start=$(date +%s)
rc=$(run "$SLOW_PATH" "$(payload "$T" S1)")
end=$(date +%s)
elapsed=$((end - start))
check "non-blocking: hook exits 0 despite slow say" 0 "$rc"
check "non-blocking: hook returns in well under 3s" 1 "$([ "$elapsed" -lt 2 ] && echo 1 || echo 0)"

# ── Malformed-line tolerance: a bad JSONL line alongside a genuine valid
# LOOP-STOP declaration must still announce the CORRECT kind, not silently
# fall back to reason=extract_failed. A whole-slurp parse would abort on the
# bad line and collapse extraction to empty (indistinguishable from "no text
# yet") — this test pins per-line tolerance instead.
mk_malformed_transcript() { # n_invocations final_text -> path (malformed line inserted before final text)
  local n="$1" final="$2" out="$TMP/malformed_${RANDOM}.jsonl" i=0
  : > "$out"
  while [ "$i" -lt "$n" ]; do
    printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:agentic-loop"}}]}}' >> "$out"
    i=$((i+1))
  done
  printf '%s\n' '{"type":"assistant", THIS IS NOT VALID JSON' >> "$out"
  if [ -n "$final" ]; then
    jq -cn --arg t "$final" '{type:"assistant",message:{content:[{type:"text",text:$t}]}}' >> "$out"
  fi
  printf '%s' "$out"
}
reset; T=$(mk_malformed_transcript 1 "All done.
LOOP-STOP: complete — all PRs merged"); write_file in-progress S1 0
rc=$(run "$STUB_PATH" "$(payload "$T" S1)")
check "malformed line + valid declaration: hook exits 0" 0 "$rc"
check "malformed line + valid declaration: exactly one say call" 1 "$(say_call_count)"
check "malformed line + valid declaration: announces correct kind (complete)" 1 "$(grep -qi 'complete' "$SAY_LOG" && echo 1 || echo 0)"
check "malformed line + valid declaration: NOT misread as extract_failed" 0 \
  "$(last_voice_log_line | grep -qE 'reason=extract_failed' && echo 1 || echo 0)"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
