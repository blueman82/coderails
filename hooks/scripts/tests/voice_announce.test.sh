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
reset() { rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"; rm -f "$SAY_LOG"; }

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
say_call_count() {
  local i=0 n
  while [ "$i" -lt 20 ]; do
    n=$([ -f "$SAY_LOG" ] && wc -l < "$SAY_LOG" | tr -d ' ' || echo 0)
    [ "$n" -gt 0 ] && break
    sleep 0.1
    i=$((i+1))
  done
  echo "${n:-0}"
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

# ── Path 2: approval/awaiting ─────────────────────────────────────────────
reset; T=$(mk_transcript 1 "Work paused.
LOOP-STOP: approval-gate — need human ok"); write_file in-progress S1 0
rc=$(run "$STUB_PATH" "$(payload "$T" S1)")
check "approval-gate: hook exits 0" 0 "$rc"
check "approval-gate: exactly one say call" 1 "$(say_call_count)"
check "approval-gate: phrase mentions waiting" 1 "$(grep -qiE 'wait' "$SAY_LOG" && echo 1 || echo 0)"

reset; T=$(mk_transcript 1 "Still waiting.
LOOP-STOP: awaiting-input — need the plan confirmed"); write_file in-progress S1 0
rc=$(run "$STUB_PATH" "$(payload "$T" S1)")
check "awaiting-input: hook exits 0" 0 "$rc"
check "awaiting-input: exactly one say call" 1 "$(say_call_count)"
check "awaiting-input: phrase mentions waiting" 1 "$(grep -qiE 'wait' "$SAY_LOG" && echo 1 || echo 0)"

# ── Path 3: stall (active loop, no valid declaration) ─────────────────────
reset; T=$(mk_transcript 1 "Here is a status update with no declaration."); write_file in-progress S1 0
rc=$(run "$STUB_PATH" "$(payload "$T" S1)")
check "stall: hook exits 0" 0 "$rc"
check "stall: exactly one say call" 1 "$(say_call_count)"
check "stall: phrase mentions stall" 1 "$(grep -qiE 'stall|stuck' "$SAY_LOG" && echo 1 || echo 0)"

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
check "debounce: different kind still speaks (2 calls total)" 2 "$(say_call_count)"

# ── jq absent -> fail-open: hook exits 0, no say call ─────────────────────
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — all PRs merged"); write_file in-progress S1 0
rc=$(run "$NOJQ_BIN:$PATH" "$(payload "$T" S1)")
check "jq absent -> still allow (fail-open)" 0 "$rc"
check "jq absent -> zero say calls" 0 "$(say_call_count)"

# ── Non-blocking: hook returns fast even though `say` sleeps 3s ───────────
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — all PRs merged"); write_file in-progress S1 0
start=$(date +%s)
rc=$(run "$SLOW_PATH" "$(payload "$T" S1)")
end=$(date +%s)
elapsed=$((end - start))
check "non-blocking: hook exits 0 despite slow say" 0 "$rc"
check "non-blocking: hook returns in well under 3s" 1 "$([ "$elapsed" -lt 2 ] && echo 1 || echo 0)"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
