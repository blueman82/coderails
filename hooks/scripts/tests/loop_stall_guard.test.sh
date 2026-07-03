#!/bin/bash
# Behavioural test for loop_stall_guard.sh — feeds synthetic Stop payloads with
# fixture transcripts (an agentic-loop invocation + a final assistant message) and
# asserts exit codes for every gate. State lives under a temp dir, never the repo.
set -u
GUARD="$(cd "$(dirname "$0")/.." && pwd)/loop_stall_guard.sh"
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
    # jq builds a valid assistant text entry with arbitrary body text.
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
run() { echo "$2" | bash "$GUARD" >/dev/null 2>&1; echo $?; }
check() { if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"; else printf 'FAIL - %s (expected exit %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi; }
reset() { rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"; }
progress_file() { printf '%s/progress.json' "$(file_dir "$1")"; }   # session_id -> progress.json path
counter() { jq -r --arg c "$2" '.loop_stop_counts[$c] // 0' "$(progress_file "$1")" 2>/dev/null; }   # session_id category

# als_gate_no_transcript — no transcript file.
check "no transcript -> allow" 0 "$(run x "$(payload "$TMP/nope.jsonl" S1)")"

# als_gate_require_active_loop — non-loop skill only -> allow.
reset; T=$(mk_other_transcript)
check "non-loop skill -> allow" 0 "$(run x "$(payload "$T" S1)")"

# als_gate_loop_complete — complete, not re-armed, owned -> allow (no tag needed).
reset; T=$(mk_transcript 1 ""); write_file complete S1 1
check "complete off-switch -> allow" 0 "$(run x "$(payload "$T" S1)")"

# gate_loop_stop_declared — active, incomplete, last message carries a valid LOOP-STOP tag -> allow.
reset; T=$(mk_transcript 1 "Work paused.
LOOP-STOP: awaiting-input — waiting on the user's plan confirmation"); write_file in-progress S1 0
check "valid LOOP-STOP tag -> allow" 0 "$(run x "$(payload "$T" S1)")"

# gate_loop_stop_declared — complete category tag is also accepted.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — all PRs merged"); write_file in-progress S1 0
check "complete tag -> allow" 0 "$(run x "$(payload "$T" S1)")"

# block_missing_declaration — active, incomplete, NO tag -> block.
reset; T=$(mk_transcript 1 "Here is a status update with no declaration."); write_file in-progress S1 0
check "no declaration -> block" 2 "$(run x "$(payload "$T" S1)")"

# block_missing_declaration — tag present but category OUTSIDE the vocab -> block.
reset; T=$(mk_transcript 1 "LOOP-STOP: paused — taking a break"); write_file in-progress S1 0
check "out-of-vocab category -> block" 2 "$(run x "$(payload "$T" S1)")"

# als_gate_stop_loop — already blocked this turn: would-block case allowed via loop-guard.
reset; T=$(mk_transcript 1 "no declaration here"); write_file in-progress S1 0
check "stop_hook_active -> allow" 0 "$(run x "$(payload "$T" S1 true)")"

# Hook-owned counter — a valid LOOP-STOP declaration increments loop_stop_counts.<category>
# by exactly 1, starting from a fixture with no loop_stop_counts key at all (initialisation).
reset; T=$(mk_transcript 1 "Work paused.
LOOP-STOP: awaiting-input — waiting on the user's plan confirmation"); write_file in-progress S1 0
run x "$(payload "$T" S1)" >/dev/null
check "counter initialises missing key to 1" 1 "$(counter S1 awaiting-input)"

# A second declaration of the SAME category accumulates (2), proving increment not overwrite.
run x "$(payload "$T" S1)" >/dev/null
check "counter accumulates on repeat -> 2" 2 "$(counter S1 awaiting-input)"

# A different category in the same fixture increments independently, other counts untouched.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — all PRs merged"); write_file in-progress S1 0
run x "$(payload "$T" S1)" >/dev/null
check "distinct category counted separately (complete)" 1 "$(counter S1 complete)"
check "untouched category stays 0 (hard-stop)" 0 "$(counter S1 hard-stop)"

# Malformed progress.json must not crash the hook or block the stop; counter write is skipped.
reset; T=$(mk_transcript 1 "Work paused.
LOOP-STOP: hard-stop — malformed fixture"); dir=$(file_dir S1); mkdir -p "$dir"
printf '{not valid json' > "$dir/progress.json"
check "malformed progress.json -> still allow (declared)" 0 "$(run x "$(payload "$T" S1)")"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
