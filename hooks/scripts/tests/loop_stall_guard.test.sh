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
# Build a transcript where the loop was started via the SLASH-COMMAND form
# (/coderails:agentic-loop) — a user-role message whose content is a STRING
# carrying <command-name>, NOT an assistant Skill tool_use. This is how a
# human-invoked loop actually appears; the tool_use form only covers loops the
# assistant invokes programmatically. Followed by a final assistant text message.
mk_slash_transcript() { # command_name final_text -> path
  local cmd="$1" final="$2" out="$TMP/slash_${RANDOM}.jsonl"
  jq -cn --arg c "<command-message>agentic-loop</command-message>
<command-name>${cmd}</command-name>
<command-args>build this, crack on</command-args>" \
    '{type:"user",message:{role:"user",content:$c}}' > "$out"
  if [ -n "$final" ]; then
    jq -cn --arg t "$final" '{type:"assistant",message:{content:[{type:"text",text:$t}]}}' >> "$out"
  fi
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
run_env() { env "$1" bash -c "echo \"\$1\" | bash \"\$2\" >/dev/null 2>&1; echo \$?" _ "$2" "$GUARD"; }  # extra_env payload -> exit code
check() { if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"; else printf 'FAIL - %s (expected exit %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi; }
reset() { rm -rf "$CLAUDE_AGENTIC_LOOP_DIR"; }
progress_file() { printf '%s/progress.json' "$(file_dir "$1")"; }   # session_id -> progress.json path
counter() { jq -r --arg c "$2" '.loop_stop_counts[$c] // 0' "$(progress_file "$1")" 2>/dev/null; }   # session_id category
write_retro() { # session_id content -> writes retro.json beside progress.json
  local dir; dir=$(file_dir "$1")
  mkdir -p "$dir"
  printf '%s' "$2" > "$dir/retro.json"
}
# Overwrites progress.json (written by write_file) with an added top-level
# work_units field, given as a raw JSON fragment (object or array literal).
# Keeps schema_version/status/session_id from the prior write_file call.
write_work_units() { # session_id status work_units_json_fragment
  local dir; dir=$(file_dir "$1")
  mkdir -p "$dir"
  jq -n --arg s "$1" --arg st "$2" --argjson wu "$3" \
    '{schema_version:1, status:$st, session_id:$s, completed_marker:0, work_units:$wu}' \
    > "$dir/progress.json"
}
# grep -c exits 1 on zero matches even though it correctly prints "0" — count()
# always exits 0 and prints just the count, so a zero-match assertion doesn't
# need an `|| echo 0` fallback (mirrors loop_state_guard.test.sh's own count()).
count() { grep -c "$1" "$2" 2>/dev/null; true; }

# A minimal PATH containing every coreutil the guard/lib needs, but NOT jq —
# used to prove the hook fails open (never blocks) when jq is unavailable.
NOJQ_BIN="$TMP/nojq-bin"
mkdir -p "$NOJQ_BIN"
for _t in bash sh dirname grep sleep tail printf mv rm cat sed awk date mkdir env basename cut tr paste; do
  _p=$(command -v "$_t" 2>/dev/null)
  [ -n "$_p" ] && ln -sf "$_p" "$NOJQ_BIN/$_t"
done

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
# (retro.json required alongside from Task 2's als_gate_retro_on_complete —
# this fixture is testing declaration-category matching, not the retro gate,
# so it supplies a valid retro to keep exercising the ORIGINAL behaviour.)
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — all PRs merged"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
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
# (retro.json supplied so this "complete" fixture clears Task 2's retro gate —
# this test is about counter independence, not the retro gate itself.)
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — all PRs merged"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
run x "$(payload "$T" S1)" >/dev/null
check "distinct category counted separately (complete)" 1 "$(counter S1 complete)"
check "untouched category stays 0 (hard-stop)" 0 "$(counter S1 hard-stop)"

# Malformed progress.json must not crash the hook or block the stop; counter write is skipped.
reset; T=$(mk_transcript 1 "Work paused.
LOOP-STOP: hard-stop — malformed fixture"); dir=$(file_dir S1); mkdir -p "$dir"
printf '{not valid json' > "$dir/progress.json"
check "malformed progress.json -> still allow (declared)" 0 "$(run x "$(payload "$T" S1)")"

# No-clobber: an arbitrary nested field alongside the counter must survive
# byte-semantically after a valid declaration — this is THE property the
# hook-owned-counter design exists for, encoded as a standing regression guard.
reset; T=$(mk_transcript 1 "Work paused.
LOOP-STOP: approval-gate — need human ok"); dir=$(file_dir S1); mkdir -p "$dir"
jq -n '{schema_version:1,status:"in-progress",session_id:"S1",completed_marker:0,
        custom_field:{nested:[1,2,3]},work_units:[{id:"A",status:"done"},{id:"B",status:"pending"}]}' \
  > "$dir/progress.json"
before=$(jq -S 'del(.loop_stop_counts)' "$dir/progress.json")
run x "$(payload "$T" S1)" >/dev/null
after=$(jq -S 'del(.loop_stop_counts)' "$dir/progress.json")
check "no-clobber: unrelated keys survive byte-identical" "$before" "$after"
check "no-clobber: counter still incremented" 1 "$(counter S1 approval-gate)"

# jq absent — the counter path must be non-fatal BY DESIGN (command -v guard in
# bump_loop_stop_count), not merely because transcript extraction happens to fail
# open too. Run with a PATH that has every coreutil except jq.
reset; T=$(mk_transcript 1 "Work paused.
LOOP-STOP: hard-stop — testing jq absence"); write_file in-progress S1 0
check "jq absent -> still allow (fail-open by design)" 0 "$(run_env "PATH=$NOJQ_BIN" "$(payload "$T" S1)")"

# Multi-declaration tie-break — two LOOP-STOP lines in one message: the LAST
# one's category is counted (SKILL.md defines the declaration as the turn's
# ENDING line, so only the final one reflects the turn's actual outcome).
reset; T=$(mk_transcript 1 "LOOP-STOP: hard-stop — first, ignore this one
LOOP-STOP: complete — actually this one, the loop is done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
run x "$(payload "$T" S1)" >/dev/null
check "multi-declaration: last category wins (complete)" 1 "$(counter S1 complete)"
check "multi-declaration: first category NOT counted (hard-stop)" 0 "$(counter S1 hard-stop)"

# Slash-command loop registration — a loop started via /coderails:agentic-loop
# (the human-invoked form: a user-role command-name message, NOT an assistant
# Skill tool_use) must still be detected as an active loop, so the anti-stall
# guard engages and the hook-owned counter increments. This is the real-world
# case the null-counter bug hit: the whole loop ran off a slash invocation, the
# gate saw invocations=0, exited early, and bump_loop_stop_count was never
# reached. The tool_use-only fixtures above never exercised this path.
reset; T=$(mk_slash_transcript "/coderails:agentic-loop" "Work paused.
LOOP-STOP: awaiting-input — waiting on the user's plan confirmation"); write_file in-progress S1 0
check "slash-command loop -> declaration allowed (not treated as non-loop)" 0 "$(run x "$(payload "$T" S1)")"
check "slash-command loop -> counter increments" 1 "$(counter S1 awaiting-input)"

# Bare slash form (/agentic-loop, unscoped) must also register.
reset; T=$(mk_slash_transcript "/agentic-loop" "All done.
LOOP-STOP: complete — all PRs merged"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
run x "$(payload "$T" S1)" >/dev/null
check "bare slash-command loop -> counter increments" 1 "$(counter S1 complete)"

# A slash command for a DIFFERENT skill must NOT be mistaken for a loop
# (guards against an over-broad command-name match).
reset; T=$(mk_slash_transcript "/coderails:prep" "no declaration here"); write_file in-progress S1 0
check "non-loop slash command -> allow (not a loop)" 0 "$(run x "$(payload "$T" S1)")"

# Multiple command-name tags in ONE user message, loop tag NOT first — the
# scan must catch EVERY tag, not just the first, or a non-loop command ahead of
# the loop command would undercount to 0 and re-hide the null-counter bug.
reset
T="$TMP/multitag_${RANDOM}.jsonl"
jq -cn --arg c "<command-name>/coderails:prep</command-name>
<command-name>/coderails:agentic-loop</command-name>" \
  '{type:"user",message:{role:"user",content:$c}}' > "$T"
jq -cn --arg t "Work paused.
LOOP-STOP: hard-stop — multi-tag message" \
  '{type:"assistant",message:{content:[{type:"text",text:$t}]}}' >> "$T"
write_file in-progress S1 0
run x "$(payload "$T" S1)" >/dev/null
check "multi command-name tags: loop tag not first still counts" 1 "$(counter S1 hard-stop)"

# Unwritable progress dir (chmod 555) — degrades safely: stop still allowed,
# and jq's redirect never opens the tmp file, so no leftover .tmp.
reset; T=$(mk_transcript 1 "Work paused.
LOOP-STOP: hard-stop — testing unwritable dir"); dir=$(file_dir S1); mkdir -p "$dir"
write_file in-progress S1 0
chmod 555 "$dir"
rc=$(run x "$(payload "$T" S1)")
tmp_leak=$(find "$dir" -name '*.tmp' 2>/dev/null | wc -l | tr -d ' ')
chmod 755 "$dir"   # restore so the trap's rm -rf can clean up
check "unwritable progress dir -> still allow" 0 "$rc"
check "unwritable progress dir -> no .tmp leak" 0 "$tmp_leak"

# ALS_PATH under a nonexistent directory — als_resolve_path computes a path
# whose parent was never created; the [-f] guard in bump_loop_stop_count
# returns before ever attempting a write. Stop still allowed, nothing created.
reset; T=$(mk_transcript 1 "Work paused.
LOOP-STOP: hard-stop — testing nonexistent progress dir")
# Deliberately skip write_file/mkdir — CLAUDE_AGENTIC_LOOP_DIR/state itself doesn't exist.
check "nonexistent progress dir -> still allow" 0 "$(run x "$(payload "$T" S1)")"

# =====================================================================
# Malformed-line tolerance: one bad JSONL line must not collapse extraction
# to empty and must not collapse the invocation count to 0 either. A
# malformed line inserted between a valid loop-Skill line and the final
# valid LOOP-STOP text must still be detected as active AND the declaration
# must still extract.
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
reset; : > "$CLAUDE_DISCIPLINE_LOG"; T=$(mk_malformed_transcript 1 "Work paused.
LOOP-STOP: awaiting-input — waiting on the user's plan confirmation"); write_file in-progress S1 0
check "malformed line + valid LOOP-STOP tag -> still allow (declaration still extracts)" 0 "$(run x "$(payload "$T" S1)")"
# Discriminates "allowed because declared=1" (the correct path: the guard
# reached the declaration gate with a nonzero invocation count) from
# "allowed because invocations read as 0 and the guard exited early via the
# not-a-loop path" — an exit code of 0 alone does not distinguish these two
# very different reasons for allowing. als_gate_require_active_loop's own log
# line only fires on invocations=0; gate_loop_stop_declared's declared=1 line
# only fires once the count is correctly nonzero and the declaration was found.
check "malformed line + valid LOOP-STOP tag -> reached declaration gate (declared=1), not misdetected as no-loop" 1 \
  "$(count 'hook=loop_stall_guard.*declared=1' "$CLAUDE_DISCIPLINE_LOG")"
check "malformed line + valid LOOP-STOP tag -> NOT misdetected as invocations=0 (not a loop)" 0 \
  "$(count 'invocations=0 active=0' "$CLAUDE_DISCIPLINE_LOG")"

# =====================================================================
# Direct unit tests for als_count_invocations' INPUT-SHAPE contract. These
# assert the integer stdout for slash-command edge cases that are awkward to
# reach through the full guard (which also needs a LOOP-STOP declaration and a
# progress.json to observe). Source the lib in a subshell so its globals/env
# don't leak into the guard tests above.
mk_line() { jq -cn --arg c "$1" '{type:"user",message:{role:"user",content:$c}}'; }   # string-content user msg
inv_count() { ( . "$(cd "$(dirname "$0")/.." && pwd)/lib/loop_state_common.sh"; als_count_invocations "$1" ); }

# Gap: a user message with ARRAY content (tool_result) that QUOTES a command-name
# tag must NOT count — the select(type=="string") guard is what keeps Form 2 from
# firing on the bulk of the transcript (every tool_result turn is array-content).
U="$TMP/arr_${RANDOM}.jsonl"
jq -cn '{type:"user",message:{role:"user",content:[{type:"tool_result",content:"see <command-name>/coderails:agentic-loop</command-name>"}]}}' > "$U"
check "array-content user msg quoting the tag -> not counted (0)" 0 "$(inv_count "$U")"

# Gap: trailing whitespace INSIDE the tag must still count — the anchored
# loop_name test would otherwise fail on the padded capture, re-hiding the bug.
U="$TMP/ws_${RANDOM}.jsonl"; mk_line "<command-name>/coderails:agentic-loop  </command-name>" > "$U"
check "trailing-whitespace tag -> still counts (1)" 1 "$(inv_count "$U")"

# Lock-in: mixed-form (slash + assistant Skill tool_use for the same loop) counts
# 2 by design — documented no-dedup decision; matches the pre-existing behavior
# of two Skill tool_uses. A future 'unique' that silently changed the ordinal
# would fail here.
U="$TMP/mixed_${RANDOM}.jsonl"
mk_line "<command-name>/coderails:agentic-loop</command-name>" > "$U"
printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:agentic-loop"}}]}}' >> "$U"
check "mixed slash+tool_use for one loop -> counts 2 (no cross-form dedup)" 2 "$(inv_count "$U")"

# =====================================================================
# als_gate_retro_on_complete — retro-presence gate on a `complete` LOOP-STOP.
# retro.json lives BESIDE progress.json, i.e. in the same session dir
# (write_retro is defined up with the other fixture helpers, since two
# pre-existing "complete" fixtures above now need it too).
# NOT `rc=$(run_capture_stderr ...)` — that would run the function in a
# subshell (command substitution), so the STDERR_OUT global it sets would
# vanish with the subshell and never reach the caller (same pitfall
# als_count_invocations' header comment documents for its own reason-tag).
# Call it directly; it sets both RC_OUT and STDERR_OUT in THIS shell.
run_capture_stderr() { # payload -> sets $RC_OUT and $STDERR_OUT (no subshell)
  local errfile="$TMP/stderr_${RANDOM}.txt"
  echo "$1" | bash "$GUARD" >/dev/null 2>"$errfile"
  RC_OUT=$?
  STDERR_OUT=$(cat "$errfile" 2>/dev/null)
  rm -f "$errfile"
}

# (a) complete declared, retro.json absent -> block, stderr mentions retro.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
run_capture_stderr "$(payload "$T" S1)"
check "complete + no retro.json -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *[Rr]etro*) retro_mentioned=1 ;; *) retro_mentioned=0 ;; esac
check "complete + no retro.json -> stderr mentions retro" 1 "$retro_mentioned"
check "complete + no retro.json -> complete counter NOT bumped" 0 "$(counter S1 complete)"

# (b) complete declared, valid {"schema_version":1} retro.json beside progress.json
# -> allow AND loop_stop_counts.complete bumped (block-before-bump: a passing
# gate must still let the pre-existing counter logic run).
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
check "complete + valid retro.json -> allow" 0 "$(run x "$(payload "$T" S1)")"
check "complete + valid retro.json -> counter bumped" 1 "$(counter S1 complete)"

# (c) complete declared, retro.json present but not valid JSON -> block.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 'not-json'
check "complete + malformed retro.json -> block" 2 "$(run x "$(payload "$T" S1)")"
check "complete + malformed retro.json -> complete counter NOT bumped" 0 "$(counter S1 complete)"

# (d) complete declared, retro.json valid JSON, schema_version 2 (the
# loop-cost-miner bump) -> allow. The gate is forward-compatible
# (schema_version >= 1), so 2 (and any future bump) is accepted without
# needing another gate edit.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":2}'
check "complete + schema_version 2 retro.json -> allow" 0 "$(run x "$(payload "$T" S1)")"
check "complete + schema_version 2 retro.json -> counter bumped" 1 "$(counter S1 complete)"

# (d2) complete declared, retro.json valid JSON, schema_version 99 (an
# arbitrary future bump) -> allow. Proves the gate is genuinely >=1
# forward-compatible, not secretly still an exact {1,2} allowlist.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":99}'
check "complete + schema_version 99 retro.json -> allow (forward-compatible)" 0 "$(run x "$(payload "$T" S1)")"
check "complete + schema_version 99 retro.json -> counter bumped" 1 "$(counter S1 complete)"

# (d3) complete declared, retro.json valid JSON but schema_version 0 -> still
# block. Negative control: forward-compatibility (>=1) must not have
# degraded into fail-never — a retro with no real schema_version is still
# rejected.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":0}'
check "complete + schema_version 0 retro.json -> block" 2 "$(run x "$(payload "$T" S1)")"
check "complete + schema_version 0 retro.json -> complete counter NOT bumped" 0 "$(counter S1 complete)"

# (d4) complete declared, retro.json valid JSON but schema_version ABSENT
# entirely -> still block. Same negative-control intent as (d3), covering
# the missing-key case rather than an explicit 0.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"not_schema_version":1}'
check "complete + absent schema_version retro.json -> block" 2 "$(run x "$(payload "$T" S1)")"
check "complete + absent schema_version retro.json -> complete counter NOT bumped" 0 "$(counter S1 complete)"

# (d5) complete declared, retro.json valid JSON but schema_version is a
# NON-NUMERIC value (a string) -> still block. Rounds out the >=1 negative
# controls: 0 (d3), absent (d4), and now wrong-type.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":"abc"}'
check "complete + non-numeric schema_version retro.json -> block" 2 "$(run x "$(payload "$T" S1)")"
check "complete + non-numeric schema_version retro.json -> complete counter NOT bumped" 0 "$(counter S1 complete)"

# (e) non-complete category (hard-stop) with no retro.json -> allow; the gate
# fires ONLY on a `complete` declaration.
reset; T=$(mk_transcript 1 "Work paused.
LOOP-STOP: hard-stop — x"); write_file in-progress S1 0
check "hard-stop + no retro.json -> allow (gate is complete-only)" 0 "$(run x "$(payload "$T" S1)")"

# (f) stop_hook_active=true short-circuits BEFORE the retro gate even runs —
# complete + no retro.json must still allow.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
check "stop_hook_active + complete + no retro.json -> allow (short-circuit precedes gate)" 0 \
  "$(run x "$(payload "$T" S1 true)")"

# (g2) MIXED-CASE BLOCK (the Critical bug) — loop_stall_guard's own category
# extraction is case-INSENSITIVE (grep -oiE) and preserves the model's original
# casing, so a model writing "Complete" or "COMPLETE" still declares the loop
# done per the outer stall-guard's vocab match. The retro gate must treat those
# the same as lowercase "complete" — a case-sensitive compare here would let
# capitalisation alone bypass the entire retro-presence requirement.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: Complete — done"); write_file in-progress S1 0
check "mixed-case Complete + no retro.json -> block" 2 "$(run x "$(payload "$T" S1)")"
# bump_loop_stop_count keys on the RAW extracted category (unnormalized), so a
# regression that let the block fall through to the bump would write under the
# literal "Complete" key, not lowercase "complete" — assert against the key
# that would actually receive the write.
check "mixed-case Complete + no retro.json -> Complete counter NOT bumped" 0 "$(counter S1 Complete)"

reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: COMPLETE — done"); write_file in-progress S1 0
check "all-caps COMPLETE + no retro.json -> block" 2 "$(run x "$(payload "$T" S1)")"
check "all-caps COMPLETE + no retro.json -> COMPLETE counter NOT bumped" 0 "$(counter S1 COMPLETE)"

# (g3) mixed-case allow — proves normalization doesn't break the happy path
# for a non-lowercase declaration paired with a valid retro.json.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: Complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
check "mixed-case Complete + valid retro.json -> allow" 0 "$(run x "$(payload "$T" S1)")"

# =====================================================================
# als_gate_work_units_on_complete — deferral gate on a `complete` LOOP-STOP.
# work_units lives INSIDE progress.json (write_work_units overwrites the file
# written by write_file, adding the field). Every fixture below supplies a
# valid retro.json first (write_retro) so the PRE-EXISTING retro gate never
# fires first and masks this gate as a no-op (see the file-header note on
# als_gate_retro_on_complete for why retro.json is required for "complete").
# To discriminate the block SOURCE from the retro gate's, every BLOCK
# assertion below checks stderr names the offending unit id, not just "retro".

# (h1) object, one pending unit + complete -> BLOCK, stderr names that id,
# complete counter NOT bumped.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{"wu1":{"status":"pending"}}'
run_capture_stderr "$(payload "$T" S1)"
check "work_units: one pending -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *wu1*) wu1_named=1 ;; *) wu1_named=0 ;; esac
check "work_units: one pending -> stderr names wu1" 1 "$wu1_named"
check "work_units: one pending -> complete counter NOT bumped" 0 "$(counter S1 complete)"

# (h2) object, all done + complete -> ALLOW, counter bumped.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{"wu1":{"status":"done"},"wu2":{"status":"done"}}'
check "work_units: all done -> allow" 0 "$(run x "$(payload "$T" S1)")"
check "work_units: all done -> counter bumped" 1 "$(counter S1 complete)"

# (h3) dropped + non-empty reason -> ALLOW.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{"wu1":{"status":"dropped","dropped_reason":"superseded by wu2"}}'
check "work_units: dropped + reason -> allow" 0 "$(run x "$(payload "$T" S1)")"

# (h4) dropped + no reason key at all -> BLOCK.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{"wu1":{"status":"dropped"}}'
run_capture_stderr "$(payload "$T" S1)"
check "work_units: dropped + no reason -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *wu1*) wu1_named=1 ;; *) wu1_named=0 ;; esac
check "work_units: dropped + no reason -> stderr names wu1" 1 "$wu1_named"

# (h5) dropped + empty-string reason -> BLOCK.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{"wu1":{"status":"dropped","dropped_reason":""}}'
check "work_units: dropped + empty-string reason -> block" 2 "$(run x "$(payload "$T" S1)")"

# (h5b) dropped + whitespace-only reason -> BLOCK.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{"wu1":{"status":"dropped","dropped_reason":"   "}}'
check "work_units: dropped + whitespace-only reason -> block" 2 "$(run x "$(payload "$T" S1)")"

# (h6) absent work_units -> ALLOW (fail-open; write_file never sets the field).
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
check "work_units: absent field -> allow" 0 "$(run x "$(payload "$T" S1)")"

# (h7) empty object {} -> ALLOW.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{}'
check "work_units: empty object -> allow" 0 "$(run x "$(payload "$T" S1)")"

# (h8) mixed done + pending -> BLOCK naming ONLY the pending id.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{"wu1":{"status":"done"},"wu2":{"status":"pending"}}'
run_capture_stderr "$(payload "$T" S1)"
check "work_units: mixed done+pending -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *wu2*) wu2_named=1 ;; *) wu2_named=0 ;; esac
check "work_units: mixed done+pending -> stderr names wu2" 1 "$wu2_named"
case "$STDERR_OUT" in *wu1*) wu1_named=1 ;; *) wu1_named=0 ;; esac
check "work_units: mixed done+pending -> stderr does NOT name wu1 (done)" 0 "$wu1_named"

# (h9) in-progress and blocked statuses -> BLOCK (two sub-cases).
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{"wu1":{"status":"in-progress"}}'
check "work_units: in-progress status -> block" 2 "$(run x "$(payload "$T" S1)")"

reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{"wu1":{"status":"blocked"}}'
check "work_units: blocked status -> block" 2 "$(run x "$(payload "$T" S1)")"

# (h10) hard-stop + pending unit -> ALLOW (complete-only gate; mirrors the
# retro gate's own case (e)). No retro.json needed — the retro gate is also
# complete-only, so a hard-stop clears both gates by not triggering either.
reset; T=$(mk_transcript 1 "Work paused.
LOOP-STOP: hard-stop — x"); write_file in-progress S1 0
write_work_units S1 in-progress '{"wu1":{"status":"pending"}}'
check "work_units: hard-stop + pending -> allow (gate is complete-only)" 0 "$(run x "$(payload "$T" S1)")"

# (h11) jq absent + pending + complete -> ALLOW (fail-open, mirrors NOJQ_BIN
# usage in the retro-gate style: no jq means the gate itself never runs, and
# the whole guard falls back to fail-open behaviour upstream).
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{"wu1":{"status":"pending"}}'
check "work_units: jq absent -> allow (fail-open)" 0 "$(run_env "PATH=$NOJQ_BIN" "$(payload "$T" S1)")"

# (h12) mixed-case "Complete" + pending -> BLOCK (case-insensitive fire, same
# requirement as the retro gate's (g2)).
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: Complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{"wu1":{"status":"pending"}}'
check "work_units: mixed-case Complete + pending -> block" 2 "$(run x "$(payload "$T" S1)")"

# (h13) malformed progress.json + complete -> ALLOW (fail-open; write_work_units
# always emits valid JSON, so overwrite with a raw non-JSON file directly).
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
dir=$(file_dir S1); printf 'not-json' > "$dir/progress.json"
check "work_units: malformed progress.json -> allow" 0 "$(run x "$(payload "$T" S1)")"

# (h14) ARRAY-shaped work_units + pending -> BLOCK (defensive tolerance for
# the legacy/wrong shape; uses .id since array entries carry their own id).
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '[{"id":"wu1","status":"pending"}]'
run_capture_stderr "$(payload "$T" S1)"
check "work_units: array-shaped + pending -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *wu1*) wu1_named=1 ;; *) wu1_named=0 ;; esac
check "work_units: array-shaped + pending -> stderr names wu1" 1 "$wu1_named"

# (h16) dropped_reason is a NUMBER (not a string) -> BLOCK. jq's gsub throws on
# a non-string input; the type guard must catch this BEFORE gsub touches it,
# treating a non-string reason as absent (not terminal) rather than letting
# the whole jq -r pipeline die and offenders come back empty (fail-open bypass
# of the gate's only escape hatch).
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{"wu1":{"status":"dropped","dropped_reason":42}}'
run_capture_stderr "$(payload "$T" S1)"
check "work_units: dropped_reason is a number -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *wu1*) wu1_named=1 ;; *) wu1_named=0 ;; esac
check "work_units: dropped_reason is a number -> stderr names wu1" 1 "$wu1_named"
check "work_units: dropped_reason is a number -> complete counter NOT bumped" 0 "$(counter S1 complete)"

# (h17) dropped_reason is a BOOLEAN -> BLOCK.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{"wu1":{"status":"dropped","dropped_reason":true}}'
run_capture_stderr "$(payload "$T" S1)"
check "work_units: dropped_reason is a boolean -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *wu1*) wu1_named=1 ;; *) wu1_named=0 ;; esac
check "work_units: dropped_reason is a boolean -> stderr names wu1" 1 "$wu1_named"

# (h18) dropped_reason is an ARRAY -> BLOCK.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{"wu1":{"status":"dropped","dropped_reason":["x"]}}'
run_capture_stderr "$(payload "$T" S1)"
check "work_units: dropped_reason is an array -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *wu1*) wu1_named=1 ;; *) wu1_named=0 ;; esac
check "work_units: dropped_reason is an array -> stderr names wu1" 1 "$wu1_named"

# (h19) dropped_reason is an OBJECT -> BLOCK.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{"wu1":{"status":"dropped","dropped_reason":{"a":1}}}'
run_capture_stderr "$(payload "$T" S1)"
check "work_units: dropped_reason is an object -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *wu1*) wu1_named=1 ;; *) wu1_named=0 ;; esac
check "work_units: dropped_reason is an object -> stderr names wu1" 1 "$wu1_named"

# (h20) dropped_reason is explicit JSON null (distinct from the key being
# absent entirely, h4) -> BLOCK. Already correctly blocks pre-fix (the `// ""`
# upstream of gsub catches null), so this is a regression guard, not proof of
# the number/bool/array/object bug.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{"wu1":{"status":"dropped","dropped_reason":null}}'
check "work_units: dropped_reason is explicit null -> block" 2 "$(run x "$(payload "$T" S1)")"

# (h21) COMPOUNDING CASE — a dropped_reason:42 unit AND a separate pending
# unit in the SAME file -> BLOCK, naming BOTH units. Pre-fix, the type error
# on wu1 kills the whole jq -r pipeline, so offenders comes back completely
# empty and even wu2's plain "pending" status (which needs no gsub at all)
# goes unchecked — a compounding fail-open, not just a missed reason check.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{"wu1":{"status":"dropped","dropped_reason":42},"wu2":{"status":"pending"}}'
run_capture_stderr "$(payload "$T" S1)"
check "work_units: compounding (bad reason + pending) -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *wu1*) wu1_named=1 ;; *) wu1_named=0 ;; esac
check "work_units: compounding -> stderr names wu1" 1 "$wu1_named"
case "$STDERR_OUT" in *wu2*) wu2_named=1 ;; *) wu2_named=0 ;; esac
check "work_units: compounding -> stderr names wu2" 1 "$wu2_named"
check "work_units: compounding -> complete counter NOT bumped" 0 "$(counter S1 complete)"

# (h22) REGRESSION — dropped + a real non-empty STRING reason -> still ALLOW.
# Proves the type guard didn't break the legitimate escape hatch.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{"wu1":{"status":"dropped","dropped_reason":"superseded by wu2, see PR #200"}}'
check "work_units: dropped + real string reason -> allow (escape hatch intact)" 0 "$(run x "$(payload "$T" S1)")"
check "work_units: dropped + real string reason -> counter bumped" 1 "$(counter S1 complete)"

# (h23) ARRAY-shaped entry MISSING .id -> BLOCK, stderr names it by its array
# INDEX ("[0]"), not the uninformative literal "null".
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '[{"status":"pending"}]'
run_capture_stderr "$(payload "$T" S1)"
check "work_units: array entry missing .id -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *'[0]'*) idx_named=1 ;; *) idx_named=0 ;; esac
check "work_units: array entry missing .id -> stderr names it by index [0]" 1 "$idx_named"
case "$STDERR_OUT" in *'"null"'*|*': null'*) literal_null=1 ;; *) literal_null=0 ;; esac
check "work_units: array entry missing .id -> stderr does NOT name it literal null" 0 "$literal_null"

# (h24) VALUE-TYPE-GUARD — a unit whose VALUE is a scalar STRING (not an
# object) -> BLOCK, stderr names it. Pre-fix, .value.status on a string value
# throws "Cannot index string with string \"status\"" inside the jq -r
# pipeline, killing it entirely: offenders collapses to "", and
# `[ -n "$offenders" ] || return 0` fails the whole gate OPEN even though this
# unit obviously isn't done/dropped. A non-object value cannot be proven
# terminal, so it must block, same shape as the dropped_reason type-guard.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{"wu1":"pending"}'
run_capture_stderr "$(payload "$T" S1)"
check "work_units: scalar string value -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *wu1*) wu1_named=1 ;; *) wu1_named=0 ;; esac
check "work_units: scalar string value -> stderr names wu1" 1 "$wu1_named"
check "work_units: scalar string value -> complete counter NOT bumped" 0 "$(counter S1 complete)"

# (h25) VALUE-TYPE-GUARD — a unit whose VALUE is a scalar NUMBER -> BLOCK.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{"wu1":42}'
check "work_units: scalar number value -> block" 2 "$(run x "$(payload "$T" S1)")"

# (h26) VALUE-TYPE-GUARD — a unit whose VALUE is JSON null -> BLOCK.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{"wu1":null}'
check "work_units: null value -> block" 2 "$(run x "$(payload "$T" S1)")"

# (h27) THE BLINDING CASE — one malformed scalar-value unit (wu1) alongside a
# genuinely pending object-value unit (wu2), SAME file -> BLOCK naming BOTH.
# This is the exact fail-open this fix closes: pre-fix, wu1's .value.status
# throws and kills the whole pipeline, so wu2's real "pending" status (which
# needs no type guard at all) goes completely unchecked too — one bad scalar
# entry blinds the gate to every other unit in the file.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{"wu1":"whatever","wu2":{"status":"pending"}}'
run_capture_stderr "$(payload "$T" S1)"
check "work_units: blinding case (scalar + pending) -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *wu1*) wu1_named=1 ;; *) wu1_named=0 ;; esac
check "work_units: blinding case -> stderr names wu1" 1 "$wu1_named"
case "$STDERR_OUT" in *wu2*) wu2_named=1 ;; *) wu2_named=0 ;; esac
check "work_units: blinding case -> stderr names wu2" 1 "$wu2_named"
check "work_units: blinding case -> complete counter NOT bumped" 0 "$(counter S1 complete)"

# (h28) CRITICAL REGRESSION — one malformed scalar-value unit (wu1) alongside
# a genuinely DONE object-value unit (wu2) -> BLOCK naming ONLY wu1. Proves
# the malformed entry doesn't blind evaluation of the valid one (wu2 must
# still read back as done, not swept into the block by association), and that
# the fix doesn't over-block a legitimately finished unit.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{"wu1":"whatever","wu2":{"status":"done"}}'
run_capture_stderr "$(payload "$T" S1)"
check "work_units: malformed + done sibling -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *wu1*) wu1_named=1 ;; *) wu1_named=0 ;; esac
check "work_units: malformed + done sibling -> stderr names wu1" 1 "$wu1_named"
case "$STDERR_OUT" in *wu2*) wu2_named=1 ;; *) wu2_named=0 ;; esac
check "work_units: malformed + done sibling -> stderr does NOT name wu2" 0 "$wu2_named"

# (h29) ARRAY branch — a scalar entry alongside an object entry -> BLOCK
# naming both; the scalar is named by its array INDEX (fallback), same as
# h23's missing-.id case.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '[{"status":"pending"},"scalar"]'
run_capture_stderr "$(payload "$T" S1)"
check "work_units: array scalar entry -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *'[0]'*) idx0_named=1 ;; *) idx0_named=0 ;; esac
check "work_units: array scalar entry -> stderr names the pending object [0]" 1 "$idx0_named"
case "$STDERR_OUT" in *'[1]'*) idx_named=1 ;; *) idx_named=0 ;; esac
check "work_units: array scalar entry -> stderr names the scalar by index [1]" 1 "$idx_named"

# (h30) REGRESSION — all-object, all-done (object branch) still ALLOWS. The
# value-type guard must not break the ordinary happy path.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
write_work_units S1 in-progress '{"wu1":{"status":"done"},"wu2":{"status":"done"}}'
check "work_units: value-guard regression, all-object all-done -> allow" 0 "$(run x "$(payload "$T" S1)")"
check "work_units: value-guard regression, all-object all-done -> counter bumped" 1 "$(counter S1 complete)"

# (h15) NEGATIVE CONTROL — prove the must-BLOCK assertions above actually
# discriminate: a category never bumped must not read back as bumped.
# Mirrors the retro gate's own (g) negative control below, scoped to this
# gate's fixtures (h1's session was blocked, so its counter must read 0, not
# some stale nonzero value from an earlier reset).
wu_neg_actual="$(counter S1 nonexistent-category-wu)"
if [ "$wu_neg_actual" = "1" ]; then
  echo "FAIL - work_units negative control did not fail as expected (bug in test design)"
  fails=$((fails+1))
else
  echo "ok   - work_units negative control correctly reports mismatch (expected bumped=1, got $wu_neg_actual for an uncounted category)"
fi

# (g) NEGATIVE CONTROL — prove case (b)'s counter assertion actually
# discriminates: re-checking against a category that was never bumped must
# NOT match the "bumped" expectation. Verified with a plain bash comparison
# (not check(), so a correctly-failing control doesn't fail the suite) so the
# mismatch is self-evident and the file still exits 0 overall.
neg_actual="$(counter S1 nonexistent-category)"
if [ "$neg_actual" = "1" ]; then
  echo "FAIL - negative control did not fail as expected (bug in test design)"
  fails=$((fails+1))
else
  echo "ok   - negative control correctly reports mismatch (expected bumped=1, got $neg_actual for an uncounted category)"
fi

# ─── Log injection: a newline in a unit id must not forge a log line ─────────
# The gate logs the offending unit ids. A newline in an id would otherwise write
# a second, attacker-chosen line into the discipline log — e.g. a fabricated
# "work_units_gate=passed" record with its own timestamp — corrupting the audit
# trail the dashboard reads. Enforcement was never affected; the log was.
inj_log="$TMP/inject.log"
inj_state="$TMP/inject_progress.json"
jq -n '{schema_version:1, work_units:{"evil\n2026-01-01T00:00:00+00:00 hook=loop_stall_guard session=forged work_units_gate=passed":{status:"pending"}}}' > "$inj_state"
(
  # shellcheck disable=SC1090
  . "$(cd "$(dirname "$0")/.." && pwd)/lib/loop_state_common.sh" 2>/dev/null
  ALS_PATH="$inj_state" LOG_FILE="$inj_log" \
    als_gate_work_units_on_complete "complete" "loop_stall_guard" "s"
) >/dev/null 2>&1
# A forged record is a line that STARTS with a timestamp and carries the
# attacker's payload — i.e. a line the log reader would parse as its own entry.
# The payload text surviving as escaped data on the gate's own single line is
# the fix working, not the injection: it is quoted, not executed.
# NB: grep -c prints 0 AND exits 1 on no-match, so `|| echo 0` would append a
# second 0 and make the count unparseable. Count lines instead.
inj_forged=$(grep -E '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[^ ]* hook=loop_stall_guard session=forged' "$inj_log" 2>/dev/null | wc -l | tr -d ' ')
inj_lines=$(wc -l < "$inj_log" 2>/dev/null | tr -d " ")
if [ "$inj_forged" -eq 0 ] && [ "$inj_lines" -eq 1 ]; then
  echo "ok   - newline in unit id cannot forge a log line (1 line, no forged record)"
else
  echo "FAIL - log injection: forged=$inj_forged lines=$inj_lines (expected forged=0 lines=1)"
  fails=$((fails+1))
fi

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
