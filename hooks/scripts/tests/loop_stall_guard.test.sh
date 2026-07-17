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

# SECURITY REGRESSION GUARD (reproduced full bypass, all three complete-only
# gates): a valid-JSON but NON-OBJECT scalar line (e.g. bare `42`) in the
# transcript, alongside a genuine agentic-loop invocation and an active,
# incomplete loop with NO LOOP-STOP declaration at all, must still BLOCK via
# the ordinary "no declaration" path — exactly like a clean transcript would.
# Before the als_count_invocations fix, this scalar line crashed its stage-2
# jq ("Cannot index number with string \"type\""), collapsing invocations to
# 0, which made als_gate_require_active_loop treat the whole session as "not
# a loop" and exit 0 (allow) — bypassing retro/work_units/proof gates alike,
# since none of them were ever reached. This drives that exact class through
# the REAL Stop-hook entry point (not a direct function call), because the
# bug lived in the shared invocation-counting path every gate depends on.
mk_scalar_line_transcript() { # n_invocations -> path (bare 42 line inserted after invocation, no final text)
  local n="$1" out="$TMP/scalarline_${RANDOM}.jsonl" i=0
  : > "$out"
  while [ "$i" -lt "$n" ]; do
    printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:agentic-loop"}}]}}' >> "$out"
    i=$((i+1))
  done
  printf '%s\n' '42' >> "$out"
  printf '%s' "$out"
}
reset; T=$(mk_scalar_line_transcript 1); write_file in-progress S1 0
check "SECURITY: scalar-line (42) transcript + active loop + no declaration -> block (not bypassed)" 2 "$(run x "$(payload "$T" S1)")"

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

# =====================================================================
# als_gate_proofs_on_complete — proof gate on a `complete` LOOP-STOP.
# proof.json lives BESIDE progress.json, same dir as retro.json. Every
# fixture below supplies a valid retro.json (write_retro) AND either omits
# work_units or marks them all-done (write_work_units ... done), so the two
# earlier gates never mask this one — mirrors the work_units block's own
# discipline against the retro gate.
write_proof() { # session_id proofs_json_fragment [schema_version]
  local dir; dir=$(file_dir "$1")
  mkdir -p "$dir"
  jq -n --argjson p "$2" --argjson sv "${3:-1}" '{schema_version:$sv, proofs:$p}' > "$dir/proof.json"
}
write_proof_raw() { # session_id raw_content -> writes proof.json verbatim (for malformed-JSON fixtures)
  local dir; dir=$(file_dir "$1")
  mkdir -p "$dir"
  printf '%s' "$2" > "$dir/proof.json"
}
# Appends a Bash tool_use (assistant) + its paired tool_result (user) to a
# transcript file. is_error: "true"/"false"/"null" (bare token, unquoted in
# the jq --argjson so null becomes JSON null, not the string "null").
# run_in_background: "true"/"false" — a real backgrounded launch DOES get an
# immediate paired tool_result with is_error:false (harness text like
# "Command running in background with ID: ..."), so this helper appends that
# realistic paired result too, same as the foreground path. This is what
# makes the bg-exclusion fixture actually exercise the
# run_in_background filter: without a matching non-error result present, a
# gate that forgot the filter would still block via the "no matching
# execution" path, not because it correctly excluded the bg launch.
append_bash_call() { # transcript cmd is_error run_in_background
  local t="$1" cmd="$2" is_error="$3" bg="${4:-false}" tool_id="tu_${RANDOM}${RANDOM}"
  jq -cn --arg id "$tool_id" --arg cmd "$cmd" --argjson bg "$bg" \
    '{type:"assistant",message:{content:[{type:"tool_use",id:$id,name:"Bash",input:{command:$cmd,run_in_background:$bg}}]}}' >> "$t"
  if [ "$bg" = "true" ]; then
    jq -cn --arg id "$tool_id" \
      '{type:"user",message:{content:[{type:"tool_result",tool_use_id:$id,is_error:false,content:"Command running in background with ID: xyz"}]}}' >> "$t"
  else
    jq -cn --arg id "$tool_id" --argjson err "$is_error" \
      '{type:"user",message:{content:[{type:"tool_result",tool_use_id:$id,is_error:$err}]}}' >> "$t"
  fi
}
# Appends a Bash tool_use with NO paired tool_result at all (interrupted call).
append_bash_call_no_result() { # transcript cmd
  local t="$1" cmd="$2" tool_id="tu_${RANDOM}${RANDOM}"
  jq -cn --arg id "$tool_id" --arg cmd "$cmd" \
    '{type:"assistant",message:{content:[{type:"tool_use",id:$id,name:"Bash",input:{command:$cmd,run_in_background:false}}]}}' >> "$t"
}
# Appends a single line that is VALID JSON but NOT an object (e.g. a bare
# number) — must survive the fromjson? stage same as a real record, then be
# skipped inert by the select(type=="object") guard rather than aborting the
# whole jq program when its .type is accessed.
append_raw_json_line() { # transcript raw_json
  printf '%s\n' "$2" >> "$1"
}
# Standard complete-declaration transcript base: N loop invocations + final
# LOOP-STOP: complete text. Bash calls are appended to this via append_bash_call
# BEFORE the final text line is written, matching real transcript order (tool
# calls happen during the turn, before the ending LOOP-STOP line).
mk_complete_base() { # -> path (transcript with 1 loop invocation, no final text yet)
  local out="$TMP/proof_${RANDOM}.jsonl"
  printf '%s\n' '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Skill","input":{"skill":"coderails:agentic-loop"}}]}}' > "$out"
  printf '%s' "$out"
}
append_complete_declaration() { # transcript -> appends the final LOOP-STOP: complete text line
  jq -cn --arg t "All done.
LOOP-STOP: complete — done" '{type:"assistant",message:{content:[{type:"text",text:$t}]}}' >> "$1"
}
# Sets up the standard fixture scaffold for a proof-gate test: resets state,
# writes retro.json + all-work-units-done, returns the transcript path via
# the PROOF_T global (bash functions can't return strings cleanly).
proof_fixture_reset() { # session_id
  reset
  PROOF_T=$(mk_complete_base)
  write_file in-progress "$1" 0
  write_retro "$1" '{"schema_version":1}'
}

# (1) one proof whose cmd never appears in the transcript -> BLOCK, stderr
# names the id with (unexecuted), counter not bumped.
proof_fixture_reset S1
write_proof S1 '[{"id":"P1","cmd":"echo hello-never-run"}]'
append_complete_declaration "$PROOF_T"
run_capture_stderr "$(payload "$PROOF_T" S1)"
check "proof: unexecuted cmd -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *"P1"*"unexecuted"*) p1_named=1 ;; *) p1_named=0 ;; esac
check "proof: unexecuted cmd -> stderr names P1(unexecuted)" 1 "$p1_named"
check "proof: unexecuted cmd -> complete counter NOT bumped" 0 "$(counter S1 complete)"

# (2) all proofs executed with is_error false -> ALLOW, counter bumped.
proof_fixture_reset S1
write_proof S1 '[{"id":"P1","cmd":"echo ok-run"}]'
append_bash_call "$PROOF_T" "echo ok-run" false
append_complete_declaration "$PROOF_T"
check "proof: all satisfied -> allow" 0 "$(run x "$(payload "$PROOF_T" S1)")"
check "proof: all satisfied -> counter bumped" 1 "$(counter S1 complete)"

# (3) proof executed, is_error true -> BLOCK, stderr names id with (failed).
proof_fixture_reset S1
write_proof S1 '[{"id":"P1","cmd":"false-cmd"}]'
append_bash_call "$PROOF_T" "false-cmd" true
append_complete_declaration "$PROOF_T"
run_capture_stderr "$(payload "$PROOF_T" S1)"
check "proof: failed execution -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *"P1"*"failed"*) p1_named=1 ;; *) p1_named=0 ;; esac
check "proof: failed execution -> stderr names P1(failed)" 1 "$p1_named"

# (4) absent proof.json -> ALLOW (fail-open).
proof_fixture_reset S1
append_complete_declaration "$PROOF_T"
check "proof: absent proof.json -> allow (fail-open)" 0 "$(run x "$(payload "$PROOF_T" S1)")"

# (5) THE ANTI-GAMING FLAGSHIP — proof.json entry has "status":"pass" but its
# cmd is absent from the transcript -> BLOCK. The self-written pass must not
# rescue it.
proof_fixture_reset S1
write_proof S1 '[{"id":"P1","cmd":"echo self-written-pass","status":"pass"}]'
append_complete_declaration "$PROOF_T"
run_capture_stderr "$(payload "$PROOF_T" S1)"
check "proof: status=pass but cmd never ran -> block (anti-gaming)" 2 "$RC_OUT"
case "$STDERR_OUT" in *"P1"*"unexecuted"*) p1_named=1 ;; *) p1_named=0 ;; esac
check "proof: status=pass but cmd never ran -> stderr names P1(unexecuted)" 1 "$p1_named"

# (6) malformed proof.json (invalid JSON) -> BLOCK.
proof_fixture_reset S1
write_proof_raw S1 'not-valid-json{'
append_complete_declaration "$PROOF_T"
check "proof: malformed proof.json -> block" 2 "$(run x "$(payload "$PROOF_T" S1)")"

# (7) schema_version 0 / missing / non-numeric -> BLOCK; schema_version 2
# (forward-compat) with satisfied proofs -> ALLOW.
proof_fixture_reset S1
write_proof S1 '[{"id":"P1","cmd":"echo v0"}]' 0
append_bash_call "$PROOF_T" "echo v0" false
append_complete_declaration "$PROOF_T"
check "proof: schema_version 0 -> block" 2 "$(run x "$(payload "$PROOF_T" S1)")"

proof_fixture_reset S1
write_proof_raw S1 '{"proofs":[{"id":"P1","cmd":"echo missing-sv"}]}'
append_bash_call "$PROOF_T" "echo missing-sv" false
append_complete_declaration "$PROOF_T"
check "proof: schema_version missing -> block" 2 "$(run x "$(payload "$PROOF_T" S1)")"

proof_fixture_reset S1
write_proof_raw S1 '{"schema_version":"abc","proofs":[{"id":"P1","cmd":"echo nonnum-sv"}]}'
append_bash_call "$PROOF_T" "echo nonnum-sv" false
append_complete_declaration "$PROOF_T"
check "proof: schema_version non-numeric -> block" 2 "$(run x "$(payload "$PROOF_T" S1)")"

proof_fixture_reset S1
write_proof S1 '[{"id":"P1","cmd":"echo v2"}]' 2
append_bash_call "$PROOF_T" "echo v2" false
append_complete_declaration "$PROOF_T"
check "proof: schema_version 2 (forward-compat) + satisfied -> allow" 0 "$(run x "$(payload "$PROOF_T" S1)")"

# (8) empty proofs array -> ALLOW.
proof_fixture_reset S1
write_proof S1 '[]'
append_complete_declaration "$PROOF_T"
check "proof: empty proofs array -> allow" 0 "$(run x "$(payload "$PROOF_T" S1)")"

# (9) cmd appears ONLY as a run_in_background tool_use (is_error false) ->
# BLOCK (bg launch is not an outcome).
proof_fixture_reset S1
write_proof S1 '[{"id":"P1","cmd":"long-running-thing"}]'
append_bash_call "$PROOF_T" "long-running-thing" false true
append_complete_declaration "$PROOF_T"
run_capture_stderr "$(payload "$PROOF_T" S1)"
check "proof: cmd only ran in background -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *"P1"*"unexecuted"*) p1_named=1 ;; *) p1_named=0 ;; esac
check "proof: cmd only ran in background -> stderr names P1(unexecuted)" 1 "$p1_named"

# (10) same cmd twice: first is_error true, last false -> ALLOW (last
# decides). And the reverse: first false, last true -> BLOCK.
proof_fixture_reset S1
write_proof S1 '[{"id":"P1","cmd":"flaky-then-fixed"}]'
append_bash_call "$PROOF_T" "flaky-then-fixed" true
append_bash_call "$PROOF_T" "flaky-then-fixed" false
append_complete_declaration "$PROOF_T"
check "proof: failed-then-fixed (last decides) -> allow" 0 "$(run x "$(payload "$PROOF_T" S1)")"

proof_fixture_reset S1
write_proof S1 '[{"id":"P1","cmd":"passed-then-broke"}]'
append_bash_call "$PROOF_T" "passed-then-broke" false
append_bash_call "$PROOF_T" "passed-then-broke" true
append_complete_declaration "$PROOF_T"
run_capture_stderr "$(payload "$PROOF_T" S1)"
check "proof: passed-then-broke (last decides) -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *"P1"*"failed"*) p1_named=1 ;; *) p1_named=0 ;; esac
check "proof: passed-then-broke -> stderr names P1(failed)" 1 "$p1_named"

# (11) echo-gaming: transcript contains Bash `echo "<the exact cmd>"` (and
# also a command that merely CONTAINS the cmd as substring) -> BLOCK
# (exact-match holds).
proof_fixture_reset S1
write_proof S1 '[{"id":"P1","cmd":"run-the-real-thing"}]'
append_bash_call "$PROOF_T" 'echo "run-the-real-thing"' false
append_bash_call "$PROOF_T" 'run-the-real-thing --with-extra-args' false
append_complete_declaration "$PROOF_T"
run_capture_stderr "$(payload "$PROOF_T" S1)"
check "proof: echo-gaming + substring-only -> block (exact-match holds)" 2 "$RC_OUT"
case "$STDERR_OUT" in *"P1"*"unexecuted"*) p1_named=1 ;; *) p1_named=0 ;; esac
check "proof: echo-gaming + substring-only -> stderr names P1(unexecuted)" 1 "$p1_named"

# (12) is_error null on the matching result -> ALLOW (deliberate tolerance).
proof_fixture_reset S1
write_proof S1 '[{"id":"P1","cmd":"echo null-is-error"}]'
append_bash_call "$PROOF_T" "echo null-is-error" null
append_complete_declaration "$PROOF_T"
check "proof: is_error null on match -> allow (deliberate tolerance)" 0 "$(run x "$(payload "$PROOF_T" S1)")"

# (13) proof with missing/empty/non-string cmd -> BLOCK naming its id.
proof_fixture_reset S1
write_proof_raw S1 '{"schema_version":1,"proofs":[{"id":"P1"}]}'
append_complete_declaration "$PROOF_T"
run_capture_stderr "$(payload "$PROOF_T" S1)"
check "proof: missing cmd -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *"P1"*) p1_named=1 ;; *) p1_named=0 ;; esac
check "proof: missing cmd -> stderr names P1" 1 "$p1_named"

proof_fixture_reset S1
write_proof S1 '[{"id":"P2","cmd":""}]'
append_complete_declaration "$PROOF_T"
run_capture_stderr "$(payload "$PROOF_T" S1)"
check "proof: empty-string cmd -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *"P2"*) p2_named=1 ;; *) p2_named=0 ;; esac
check "proof: empty-string cmd -> stderr names P2" 1 "$p2_named"

proof_fixture_reset S1
write_proof S1 '[{"id":"P3","cmd":"   "}]'
append_complete_declaration "$PROOF_T"
check "proof: whitespace-only cmd -> block" 2 "$(run x "$(payload "$PROOF_T" S1)")"

proof_fixture_reset S1
write_proof S1 '[{"id":"P4","cmd":42}]'
append_complete_declaration "$PROOF_T"
run_capture_stderr "$(payload "$PROOF_T" S1)"
check "proof: non-string (number) cmd -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *"P4"*) p4_named=1 ;; *) p4_named=0 ;; esac
check "proof: non-string (number) cmd -> stderr names P4" 1 "$p4_named"

# (14) proof.cmd with leading/trailing whitespace vs identical trimmed
# transcript command -> ALLOW (trim applies both sides).
proof_fixture_reset S1
write_proof S1 '[{"id":"P1","cmd":"  echo padded  "}]'
append_bash_call "$PROOF_T" "echo padded" false
append_complete_declaration "$PROOF_T"
check "proof: padded proof.cmd vs trimmed transcript cmd -> allow (trim both sides)" 0 "$(run x "$(payload "$PROOF_T" S1)")"

# (15) two proofs, one satisfied one unexecuted -> BLOCK naming ONLY the
# unexecuted one.
proof_fixture_reset S1
write_proof S1 '[{"id":"P1","cmd":"echo satisfied-one"},{"id":"P2","cmd":"echo never-ran"}]'
append_bash_call "$PROOF_T" "echo satisfied-one" false
append_complete_declaration "$PROOF_T"
run_capture_stderr "$(payload "$PROOF_T" S1)"
check "proof: one satisfied one unexecuted -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *"P2"*"unexecuted"*) p2_named=1 ;; *) p2_named=0 ;; esac
check "proof: mixed -> stderr names P2(unexecuted)" 1 "$p2_named"
case "$STDERR_OUT" in *"P1"*) p1_named=1 ;; *) p1_named=0 ;; esac
check "proof: mixed -> stderr does NOT name satisfied P1" 0 "$p1_named"

# (16) tool_use with NO tool_result at all (interrupted) as the only match
# -> BLOCK.
proof_fixture_reset S1
write_proof S1 '[{"id":"P1","cmd":"interrupted-call"}]'
append_bash_call_no_result "$PROOF_T" "interrupted-call"
append_complete_declaration "$PROOF_T"
run_capture_stderr "$(payload "$PROOF_T" S1)"
check "proof: interrupted call (no tool_result) -> block" 2 "$RC_OUT"
case "$STDERR_OUT" in *"P1"*"unexecuted"*) p1_named=1 ;; *) p1_named=0 ;; esac
check "proof: interrupted call -> stderr names P1(unexecuted)" 1 "$p1_named"

# (17) non-object proofs entry (e.g. a bare string in the array) -> BLOCK
# (cannot be verified -> fails closed, not open).
proof_fixture_reset S1
write_proof_raw S1 '{"schema_version":1,"proofs":["just-a-string"]}'
append_complete_declaration "$PROOF_T"
check "proof: non-object proofs entry -> block (fails closed)" 2 "$(run x "$(payload "$PROOF_T" S1)")"

# (18) a valid-JSON but NON-OBJECT transcript line (e.g. a bare `42`)
# alongside an otherwise-satisfied proof -> ALLOW. Without the
# select(type=="object") guard, this line's own .type access throws inside
# the jq program, collapsing $verdicts to empty and blocking a legitimate
# complete on offenders=jq_error — exactly the "one malformed line collapses
# the whole scan" failure the gate's header explicitly rules out.
#
# Calls als_gate_proofs_on_complete directly (mirrors inv_count's existing
# direct-call pattern below) to isolate the assertion to just this gate's own
# defence, independent of any other function's behaviour on the same
# transcript. This was NOT merely a convenience choice: als_count_invocations
# (called first via als_gate_require_active_loop, before this gate ever runs)
# ORIGINALLY had an identical unguarded .type access on the same transcript
# shape, and a bare `42` line crashed its own pipeline too — collapsing
# invocations to 0 and exiting the whole guard via the "not a loop" path
# before als_gate_proofs_on_complete was ever reached, at the time this test
# was first written. als_count_invocations has SINCE been fixed with the same
# select(type=="object") guard (see its own header) — the SECURITY REGRESSION
# GUARD test above (search "scalar-line") now drives this exact non-object-line
# class through the REAL Stop-hook entry point end-to-end and asserts the
# correct outcome there too. This direct-call test remains as an independent
# unit-level check of this gate's own guard, not because the full pipeline is
# unreachable anymore.
proof_gate_direct() { # session_id proof_dir transcript -> exit code of als_gate_proofs_on_complete alone
  (
    . "$(cd "$(dirname "$0")/.." && pwd)/lib/loop_state_common.sh"
    ALS_PATH="$2/progress.json"
    als_gate_proofs_on_complete complete loop_stall_guard "$1" "$3"
  )
  echo $?
}
reset
dir=$(file_dir S1); mkdir -p "$dir"
printf '{"schema_version":1,"proofs":[{"id":"P1","cmd":"echo still-satisfied"}]}' > "$dir/proof.json"
T="$TMP/directcall_${RANDOM}.jsonl"
: > "$T"
append_raw_json_line "$T" '42'
append_bash_call "$T" "echo still-satisfied" false
check "proof (direct call): non-object transcript line (bare 42) -> allow (stray line skipped, not fatal)" 0 "$(proof_gate_direct S1 "$dir" "$T")"

# ---------------------------------------------------------------------
# Additional regression/negative controls beyond the 17 mandatory tests.

# hard-stop + unexecuted proof -> ALLOW (gate is complete-only, mirrors the
# retro/work_units gates' own case (e)/(h10)).
reset; T=$(mk_transcript 1 "Work paused.
LOOP-STOP: hard-stop — x"); write_file in-progress S1 0
write_proof S1 '[{"id":"P1","cmd":"echo never-ran"}]'
check "proof: hard-stop + unexecuted -> allow (gate is complete-only)" 0 "$(run x "$(payload "$T" S1)")"

# jq absent -> ALLOW (fail-open, mirrors NOJQ_BIN usage for the sibling gates).
proof_fixture_reset S1
write_proof S1 '[{"id":"P1","cmd":"echo never-ran"}]'
append_complete_declaration "$PROOF_T"
check "proof: jq absent -> allow (fail-open)" 0 "$(run_env "PATH=$NOJQ_BIN" "$(payload "$PROOF_T" S1)")"

# Missing id falls back to P<index> — first entry with no id gets "P0".
proof_fixture_reset S1
write_proof_raw S1 '{"schema_version":1,"proofs":[{"cmd":"echo no-id-here"}]}'
append_complete_declaration "$PROOF_T"
run_capture_stderr "$(payload "$PROOF_T" S1)"
case "$STDERR_OUT" in *"P0"*"unexecuted"*) p0_named=1 ;; *) p0_named=0 ;; esac
check "proof: missing id falls back to P0" 1 "$p0_named"

# Non-string id falls back to P<index> too.
proof_fixture_reset S1
write_proof_raw S1 '{"schema_version":1,"proofs":[{"id":42,"cmd":"echo numeric-id"}]}'
append_complete_declaration "$PROOF_T"
run_capture_stderr "$(payload "$PROOF_T" S1)"
case "$STDERR_OUT" in *"P0"*"unexecuted"*) p0_named=1 ;; *) p0_named=0 ;; esac
check "proof: non-string id falls back to P0" 1 "$p0_named"

# .proofs null -> ALLOW (treated same as absent field).
proof_fixture_reset S1
write_proof_raw S1 '{"schema_version":1,"proofs":null}'
append_complete_declaration "$PROOF_T"
check "proof: proofs is null -> allow (nothing to prove)" 0 "$(run x "$(payload "$PROOF_T" S1)")"

# .proofs present but not an array (an object) -> BLOCK (malformed shape).
proof_fixture_reset S1
write_proof_raw S1 '{"schema_version":1,"proofs":{"id":"P1","cmd":"echo x"}}'
append_complete_declaration "$PROOF_T"
check "proof: proofs is an object, not an array -> block (malformed shape)" 2 "$(run x "$(payload "$PROOF_T" S1)")"

# =====================================================================
# MERGE-BLOCKER FIX — proof-count cap (fail-closed, checked before any
# transcript mining). Uses jq to generate N proofs programmatically rather
# than a hand-written literal.
mk_n_proofs() { # n -> JSON array literal of N satisfiable-shaped proofs, each cmd unique
  jq -cn --argjson n "$1" '[ range(0; $n) | {id: "P\(.)", cmd: "echo proof-\(.)"} ]'
}

# 101 proofs -> BLOCK, stderr names the count and the cap.
proof_fixture_reset S1
write_proof S1 "$(mk_n_proofs 101)"
append_complete_declaration "$PROOF_T"
run_capture_stderr "$(payload "$PROOF_T" S1)"
check "proof: 101 proofs -> block (exceeds cap)" 2 "$RC_OUT"
case "$STDERR_OUT" in *"101"*"100"*) cap_named=1 ;; *) cap_named=0 ;; esac
check "proof: 101 proofs -> stderr names the count (101) and the cap (100)" 1 "$cap_named"

# Exactly 100 proofs, all satisfied -> ALLOW (cap is exclusive: >100 blocks,
# ==100 is within bounds).
proof_fixture_reset S1
write_proof S1 "$(mk_n_proofs 100)"
i=0
while [ "$i" -lt 100 ]; do
  append_bash_call "$PROOF_T" "echo proof-$i" false
  i=$((i+1))
done
append_complete_declaration "$PROOF_T"
check "proof: exactly 100 satisfied proofs -> allow (cap is inclusive at 100)" 0 "$(run x "$(payload "$PROOF_T" S1)")"

# TIMING EVIDENCE for the O(proofs + executions) fix: 100 proofs (the cap)
# against 500 Bash calls in the transcript (the O(n x m) pre-fix shape would
# have been 100 x 500 = 50,000 comparisons; post-fix it's O(100 + 500)).
# Asserted as a wall-clock bound, not just "it completes" — a regression back
# to the linear rescan would still complete at this N, just slower; the
# threshold is generous (5s, well under the 15s hooks.json timeout) so this
# is a regression trip-wire, not a tight perf assertion.
proof_fixture_reset S1
write_proof S1 "$(mk_n_proofs 100)"
i=0
while [ "$i" -lt 500 ]; do
  append_bash_call "$PROOF_T" "echo filler-call-$i" false
  i=$((i+1))
done
i=0
while [ "$i" -lt 100 ]; do
  append_bash_call "$PROOF_T" "echo proof-$i" false
  i=$((i+1))
done
append_complete_declaration "$PROOF_T"
t0=$(date +%s)
rc=$(run x "$(payload "$PROOF_T" S1)")
t1=$(date +%s)
elapsed=$((t1 - t0))
check "proof: 100 proofs x 500 filler calls -> allow (still satisfied)" 0 "$rc"
if [ "$elapsed" -lt 5 ]; then
  printf 'ok   - proof: 100 proofs x 500 calls completed in %ss (< 5s bound)\n' "$elapsed"
else
  printf 'FAIL - proof: 100 proofs x 500 calls took %ss (>= 5s bound, possible O(n x m) regression)\n' "$elapsed"
  fails=$((fails+1))
fi

# =====================================================================
# Hardening: .id / .tool_use_id must be non-empty STRINGS to be usable as a
# match key (closes a null==null / missing-key forged-match class). A
# tool_use with a non-string or empty id is excluded from $executions
# entirely (its command can never be matched), and a tool_result with a
# non-string or empty tool_use_id is excluded from $results (can never pair).

# tool_use.id missing entirely -> the execution is unusable -> proof reads
# unexecuted even though a same-named command exists elsewhere with a result.
proof_fixture_reset S1
write_proof S1 '[{"id":"P1","cmd":"echo no-id-exec"}]'
jq -cn '{type:"assistant",message:{content:[{type:"tool_use",name:"Bash",input:{command:"echo no-id-exec",run_in_background:false}}]}}' >> "$PROOF_T"
append_complete_declaration "$PROOF_T"
run_capture_stderr "$(payload "$PROOF_T" S1)"
check "proof: tool_use missing .id -> block (execution unusable)" 2 "$RC_OUT"
case "$STDERR_OUT" in *"P1"*"unexecuted"*) p1_named=1 ;; *) p1_named=0 ;; esac
check "proof: tool_use missing .id -> stderr names P1(unexecuted)" 1 "$p1_named"

# tool_result.tool_use_id missing entirely -> the result is unusable -> a
# matched execution with no usable result reads unexecuted, not satisfied.
proof_fixture_reset S1
write_proof S1 '[{"id":"P1","cmd":"echo no-id-result"}]'
tid="tu_${RANDOM}${RANDOM}"
jq -cn --arg id "$tid" --arg cmd "echo no-id-result" '{type:"assistant",message:{content:[{type:"tool_use",id:$id,name:"Bash",input:{command:$cmd,run_in_background:false}}]}}' >> "$PROOF_T"
jq -cn '{type:"user",message:{content:[{type:"tool_result",is_error:false}]}}' >> "$PROOF_T"
append_complete_declaration "$PROOF_T"
run_capture_stderr "$(payload "$PROOF_T" S1)"
check "proof: tool_result missing .tool_use_id -> block (result unusable, reads unexecuted)" 2 "$RC_OUT"
case "$STDERR_OUT" in *"P1"*"unexecuted"*) p1_named=1 ;; *) p1_named=0 ;; esac
check "proof: tool_result missing .tool_use_id -> stderr names P1(unexecuted)" 1 "$p1_named"

# =====================================================================
# proof_disposition — disposition-gated absence. Grandfathered on
# progress.json's OWN schema_version (< 2, absent, or non-numeric keeps the
# pre-existing fail-open-on-absent-proof.json behaviour untouched); at
# schema_version >= 2, an absent proof.json now requires a recorded
# proof_disposition ("none: <reason>" allows, anything else or absent/null
# blocks) — see als_gate_proofs_on_complete's own header for the full
# rationale. write_progress_raw writes progress.json VERBATIM (mirrors
# write_proof_raw's idiom) so these fixtures can set schema_version and
# proof_disposition independently of write_file's hardcoded schema_version:1.
write_progress_raw() { # session_id raw_content -> writes progress.json verbatim
  local dir; dir=$(file_dir "$1")
  mkdir -p "$dir"
  printf '%s' "$2" > "$dir/progress.json"
}
# Direct-call harness, same shape as proof_gate_direct above: isolates the
# assertion to als_gate_proofs_on_complete alone, independent of the retro/
# work_units gates that would otherwise also need satisfying via the full
# loop_stall_guard.sh pipeline for a bare "complete" declaration.
proof_disposition_gate_direct() { # session_id proof_dir transcript -> exit code
  (
    . "$(cd "$(dirname "$0")/.." && pwd)/lib/loop_state_common.sh"
    ALS_PATH="$2/progress.json"
    als_gate_proofs_on_complete complete loop_stall_guard "$1" "$3"
  )
  echo $?
}
EMPTY_T="$TMP/pd_empty_${RANDOM}.jsonl"; : > "$EMPTY_T"

# (A) schema_version:2, proof.json absent, proof_disposition absent -> BLOCK.
# The core fix: silent skip becomes impossible once a loop opts into the new
# progress.json schema. Verified at freeze time against the UNMODIFIED gate
# on origin/main@024f393 that this exact fixture returns 0 (fail-open, the
# bug this case exists to close) — see wu2-evals.json assertion A's
# negative_control.
reset
write_progress_raw S1 '{"schema_version":2,"session_id":"S1","status":"in-progress"}'
check "proof_disposition: schema_version 2, no proof.json, no disposition -> block (core fix)" \
  2 "$(proof_disposition_gate_direct S1 "$(file_dir S1)" "$EMPTY_T")"

# (A2) schema_version:2, proof.json absent, proof_disposition:null (explicit
# JSON null, not merely absent) -> BLOCK, same as absent.
reset
write_progress_raw S1 '{"schema_version":2,"session_id":"S1","status":"in-progress","proof_disposition":null}'
check "proof_disposition: schema_version 2, no proof.json, disposition explicit null -> block" \
  2 "$(proof_disposition_gate_direct S1 "$(file_dir S1)" "$EMPTY_T")"

# (A3) schema_version:2, proof.json absent, proof_disposition is a non-none,
# non-empty string ("frozen") -> BLOCK. A disposition value that is not
# "none: ..." promises a proof.json that isn't there.
reset
write_progress_raw S1 '{"schema_version":2,"session_id":"S1","status":"in-progress","proof_disposition":"frozen"}'
check "proof_disposition: schema_version 2, no proof.json, disposition=frozen -> block" \
  2 "$(proof_disposition_gate_direct S1 "$(file_dir S1)" "$EMPTY_T")"

# (B) schema_version:2, proof.json absent, proof_disposition starts with
# "none" -> ALLOW. A recorded, visible decision to skip is permitted.
reset
write_progress_raw S1 '{"schema_version":2,"session_id":"S1","status":"in-progress","proof_disposition":"none: no executable surface"}'
check "proof_disposition: schema_version 2, no proof.json, disposition=none:<reason> -> allow" \
  0 "$(proof_disposition_gate_direct S1 "$(file_dir S1)" "$EMPTY_T")"

# (B2) exact-string "none" (no colon/reason) also allows -- "starts with
# none" is the rule, not "matches the none:<reason> shape exactly".
reset
write_progress_raw S1 '{"schema_version":2,"session_id":"S1","status":"in-progress","proof_disposition":"none"}'
check "proof_disposition: schema_version 2, no proof.json, disposition=\"none\" bare -> allow" \
  0 "$(proof_disposition_gate_direct S1 "$(file_dir S1)" "$EMPTY_T")"

# (B3) a value that merely STARTS WITH the letters "none" but is not the
# bare word or a "none:"-prefixed reason must BLOCK, not allow -- the rule
# is "is 'none' or starts with 'none:'", not "starts with the substring
# none". "nonexistent" is the adversarial case: a model typo or a
# hallucinated field value that happens to start with "none" must not be
# read as the recorded skip decision.
reset
write_progress_raw S1 '{"schema_version":2,"session_id":"S1","status":"in-progress","proof_disposition":"nonexistent"}'
check "proof_disposition: schema_version 2, no proof.json, disposition=\"nonexistent\" -> block (not a none-match)" \
  2 "$(proof_disposition_gate_direct S1 "$(file_dir S1)" "$EMPTY_T")"

# (C) grandfathering: schema_version 1 / absent / non-numeric, proof.json
# absent, no proof_disposition -> ALLOW, preserving the pre-existing
# behaviour for every progress.json written before this change, including
# live sibling loops mid-flight right now.
reset
write_progress_raw S1 '{"schema_version":1,"session_id":"S1","status":"in-progress"}'
check "proof_disposition: grandfathered schema_version 1, no proof.json -> allow (compat)" \
  0 "$(proof_disposition_gate_direct S1 "$(file_dir S1)" "$EMPTY_T")"

reset
write_progress_raw S1 '{"session_id":"S1","status":"in-progress"}'
check "proof_disposition: grandfathered (schema_version key absent entirely), no proof.json -> allow (compat)" \
  0 "$(proof_disposition_gate_direct S1 "$(file_dir S1)" "$EMPTY_T")"

reset
write_progress_raw S1 '{"schema_version":"x","session_id":"S1","status":"in-progress"}'
check "proof_disposition: grandfathered (schema_version non-numeric), no proof.json -> allow (compat)" \
  0 "$(proof_disposition_gate_direct S1 "$(file_dir S1)" "$EMPTY_T")"

# Same three grandfather fixtures, but re-run with schema_version forced to 2
# and no disposition, to prove the grandfathering is keyed on the
# schema_version threshold and not on some other property (e.g. a missing
# work_units field) shared by these minimal fixtures.
reset
write_progress_raw S1 '{"schema_version":2,"session_id":"S1","status":"in-progress"}'
check "proof_disposition: same minimal fixture but schema_version 2 -> block (not grandfathered)" \
  2 "$(proof_disposition_gate_direct S1 "$(file_dir S1)" "$EMPTY_T")"

# Absent, malformed, and legitimate sv<2 progress.json must each log a
# DIFFERENT proof_gate suffix rather than one identical
# "allowed_no_proof_grandfathered" line, so logs alone can tell the three
# apart (e.g. to audit whether every live loop has moved to sv>=2 yet).
proof_disposition_gate_logged() { # session_id proof_dir transcript log_file -> exit code, writes to $4
  (
    . "$(cd "$(dirname "$0")/.." && pwd)/lib/loop_state_common.sh"
    ALS_PATH="$2/progress.json" LOG_FILE="$4"
    als_gate_proofs_on_complete complete loop_stall_guard "$1" "$3"
  )
  echo $?
}

reset
lg="$TMP/pd_grandfather_absent.log"
proof_disposition_gate_logged S1 "$(file_dir S1)" "$EMPTY_T" "$lg" >/dev/null
check "proof_disposition log: progress.json absent -> grandfathered_progress_absent" \
  1 "$(grep -c 'proof_gate=allowed_no_proof_grandfathered_progress_absent' "$lg")"

reset
mkdir -p "$(file_dir S1)"
printf '{not valid json' > "$(file_dir S1)/progress.json"
lg="$TMP/pd_grandfather_malformed.log"
proof_disposition_gate_logged S1 "$(file_dir S1)" "$EMPTY_T" "$lg" >/dev/null
check "proof_disposition log: progress.json malformed -> grandfathered_progress_malformed" \
  1 "$(grep -c 'proof_gate=allowed_no_proof_grandfathered_progress_malformed' "$lg")"

reset
write_progress_raw S1 '{"schema_version":1,"session_id":"S1","status":"in-progress"}'
lg="$TMP/pd_grandfather_sv1.log"
proof_disposition_gate_logged S1 "$(file_dir S1)" "$EMPTY_T" "$lg" >/dev/null
check "proof_disposition log: progress.json schema_version 1 -> grandfathered_sv_lt2" \
  1 "$(grep -c 'proof_gate=allowed_no_proof_grandfathered_sv_lt2' "$lg")"

# (D) proof.json PRESENT overrides everything above: existing
# validation/execution-mining behaviour is completely unchanged by this fix,
# regardless of schema_version or proof_disposition (even a self-contradictory
# proof_disposition:"none: x" sitting beside an actual proof.json).
reset
dir=$(file_dir S1); mkdir -p "$dir"
write_progress_raw S1 '{"schema_version":2,"session_id":"S1","status":"in-progress","proof_disposition":"none: x"}'
printf '{"schema_version":1,"proofs":[{"id":"P1","cmd":"echo d-satisfied"}]}' > "$dir/proof.json"
D_T="$TMP/pd_d_${RANDOM}.jsonl"; : > "$D_T"
append_bash_call "$D_T" "echo d-satisfied" false
check "proof_disposition: proof.json present + satisfied, disposition=none (contradictory) -> allow (file wins)" \
  0 "$(proof_disposition_gate_direct S1 "$dir" "$D_T")"

reset
dir=$(file_dir S1); mkdir -p "$dir"
write_progress_raw S1 '{"schema_version":2,"session_id":"S1","status":"in-progress","proof_disposition":"none: x"}'
printf '{"schema_version":1,"proofs":[{"id":"P1","cmd":"echo d-unsatisfied"}]}' > "$dir/proof.json"
D_T2="$TMP/pd_d2_${RANDOM}.jsonl"; : > "$D_T2"
check "proof_disposition: proof.json present + UNSATISFIED, disposition=none -> block (presence still fully verifies)" \
  2 "$(proof_disposition_gate_direct S1 "$dir" "$D_T2")"

# =====================================================================
# Hardening: bg-exclusion polarity flip. run_in_background must be EXACTLY
# `false` (or absent, defaulting to false) to count as foreground; any
# truthy-ish value, INCLUDING a schema-dodging STRING "true", now excludes
# the call as background (fails toward unexecuted, not toward satisfied).
proof_fixture_reset S1
write_proof S1 '[{"id":"P1","cmd":"echo string-bg-dodge"}]'
tid="tu_${RANDOM}${RANDOM}"
jq -cn --arg id "$tid" --arg cmd "echo string-bg-dodge" '{type:"assistant",message:{content:[{type:"tool_use",id:$id,name:"Bash",input:{command:$cmd,run_in_background:"true"}}]}}' >> "$PROOF_T"
jq -cn --arg id "$tid" '{type:"user",message:{content:[{type:"tool_result",tool_use_id:$id,is_error:false}]}}' >> "$PROOF_T"
append_complete_declaration "$PROOF_T"
run_capture_stderr "$(payload "$PROOF_T" S1)"
check "proof: run_in_background as STRING \"true\" -> block (schema-dodge fails toward unexecuted)" 2 "$RC_OUT"
case "$STDERR_OUT" in *"P1"*"unexecuted"*) p1_named=1 ;; *) p1_named=0 ;; esac
check "proof: run_in_background string dodge -> stderr names P1(unexecuted)" 1 "$p1_named"

# Regression: run_in_background exactly `false` still counts as foreground.
proof_fixture_reset S1
write_proof S1 '[{"id":"P1","cmd":"echo explicit-false-bg"}]'
append_bash_call "$PROOF_T" "echo explicit-false-bg" false false
append_complete_declaration "$PROOF_T"
check "proof: run_in_background explicit false -> allow (foreground regression check)" 0 "$(run x "$(payload "$PROOF_T" S1)")"

# =====================================================================
# proof_count numeric-validation fail-closed: a proof.json whose .proofs
# length jq cannot read (simulated via a file that disappears between the
# earlier presence check and this read) must block, not silently allow via
# the old `[ -n "$x" ] || return 0` conflation. Simulated directly by making
# proof.json valid-shaped JSON but with .proofs as a value whose length jq
# CAN compute (a string, which has string length, not proof count) --
# proves the numeric guard fires even when jq itself doesn't error.
# (Already covered structurally by the "proofs is an object" test above for
# the non-array case; this is the arithmetic-guard's own regression check.)
reset
dir=$(file_dir S1); mkdir -p "$dir"
write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
T=$(mk_complete_base)
append_complete_declaration "$T"
printf '{"schema_version":1,"proofs":[]}' > "$dir/proof.json"
check "proof: proof_count regression, empty array -> allow" 0 "$(run x "$(payload "$T" S1)")"

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

# =====================================================================
# als_gate_cost_report_on_complete (als_report_cost_on_complete) — a REPORT,
# never a gate: it must never block, only print a systemMessage on stdout (or
# stay silent) once the retro/work_units/proof gates above have already
# passed. Captures STDOUT (not stderr) since systemMessage is a stdout JSON
# emission — run_capture_stderr above only ever inspects stderr, so it cannot
# see this hook's output; a separate capture helper is required.
run_capture_stdout() { # payload -> sets $RC_OUT and $STDOUT_OUT (no subshell)
  local outfile="$TMP/stdout_${RANDOM}.txt"
  echo "$1" | bash "$GUARD" >"$outfile" 2>/dev/null
  RC_OUT=$?
  STDOUT_OUT=$(cat "$outfile" 2>/dev/null)
  rm -f "$outfile"
}
# Extracts .systemMessage from a stdout blob that may be empty or non-JSON;
# jq -e failing (empty stdout, or JSON with no such key) yields "".
system_message() { printf '%s' "$1" | jq -r '.systemMessage // empty' 2>/dev/null; }

# (row 1) complete + schema_version>=2 + populated .cost -> ALLOW, PRINT a
# systemMessage carrying the USD total, token total, and a staleness age
# computed from prices_as_of vs today.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
STALE_DATE=$(date -u -v-5d +%Y-%m-%d 2>/dev/null || date -u -d '5 days ago' +%Y-%m-%d 2>/dev/null)
write_retro S1 "$(jq -cn --arg d "$STALE_DATE" '{schema_version:2, cost:{total_usd_estimate:12.34, total_tokens:56789, prices_as_of:$d, per_model:{}}}')"
run_capture_stdout "$(payload "$T" S1)"
check "cost-report row1: populated cost -> allow" 0 "$RC_OUT"
msg=$(system_message "$STDOUT_OUT")
case "$msg" in *"12.34"*) usd_present=1 ;; *) usd_present=0 ;; esac
check "cost-report row1: systemMessage names the USD total (12.34)" 1 "$usd_present"
case "$msg" in *"56789"*) tok_present=1 ;; *) tok_present=0 ;; esac
check "cost-report row1: systemMessage names the token total (56789)" 1 "$tok_present"
case "$msg" in *"5 days old"*) age_present=1 ;; *) age_present=0 ;; esac
check "cost-report row1: systemMessage names staleness (5 days old)" 1 "$age_present"
check "cost-report row1: complete counter still bumped (report never blocks the counter path)" 1 "$(counter S1 complete)"

# (row 2) complete + legacy schema_version 1 (no .cost field at all, the
# pre-cost-miner shape) -> ALLOW, SILENT — must NOT be confused with row 4
# (sv>=2, cost absent), which prints. schema_version is the discriminator,
# not cost-presence, since both rows 2 and 4 have .cost absent.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":1}'
run_capture_stdout "$(payload "$T" S1)"
check "cost-report row2: legacy sv1, no cost -> allow" 0 "$RC_OUT"
check "cost-report row2: legacy sv1, no cost -> silent (no systemMessage)" "" "$(system_message "$STDOUT_OUT")"

# (row 3) complete + sv>=2 + .cost == {} (miner ran, failed open) -> ALLOW,
# PRINT "cost unavailable ..." with NO fabricated dollar figure.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":2, "cost":{}}'
run_capture_stdout "$(payload "$T" S1)"
check "cost-report row3: sv2 + cost=={} -> allow" 0 "$RC_OUT"
msg=$(system_message "$STDOUT_OUT")
case "$msg" in *"cost unavailable"*"miner"*) unavailable_msg=1 ;; *) unavailable_msg=0 ;; esac
check "cost-report row3: systemMessage says cost unavailable (miner returned no data)" 1 "$unavailable_msg"
case "$msg" in *'$'[0-9]*) fabricated=1 ;; *) fabricated=0 ;; esac
check "cost-report row3: systemMessage has NO fabricated \$ figure" 0 "$fabricated"

# (row 4) complete + sv>=2 + .cost ABSENT entirely (teardown skipped the
# cost-mining sub-step) -> ALLOW, PRINT "cost not recorded" — a message
# DISTINCT from row 3's "cost unavailable (miner returned no data)".
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":2}'
run_capture_stdout "$(payload "$T" S1)"
check "cost-report row4: sv2 + cost absent -> allow" 0 "$RC_OUT"
msg4=$(system_message "$STDOUT_OUT")
case "$msg4" in *"not recorded"*) not_recorded_msg=1 ;; *) not_recorded_msg=0 ;; esac
check "cost-report row4: systemMessage says cost not recorded" 1 "$not_recorded_msg"
check "cost-report row3 vs row4: messages are textually distinct" 1 "$([ "$msg4" != "$msg" ] && echo 1 || echo 0)"

# (row 4b) complete + sv>=2 + .cost is a NON-EMPTY object but MISSING
# total_usd_estimate (partial miner output / schema drift) -> ALLOW, PRINT a
# message that says the cost data is present but incomplete. Must NOT
# silently return nothing (that would relocate the exact bug this PR exists
# to fix from model-omission to hook-omission), and must NOT fabricate a $
# figure. Message must be textually distinct from both row3's "cost
# unavailable (miner returned no data)" and row4's "cost not recorded".
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":2, "cost":{"total_tokens":123}}'
run_capture_stdout "$(payload "$T" S1)"
check "cost-report row4b: sv2 + cost missing total_usd_estimate -> allow" 0 "$RC_OUT"
msg4b=$(system_message "$STDOUT_OUT")
check "cost-report row4b: systemMessage is emitted (not silent)" 1 "$([ -n "$msg4b" ] && echo 1 || echo 0)"
case "$msg4b" in *'$'[0-9]*) fabricated4b=1 ;; *) fabricated4b=0 ;; esac
check "cost-report row4b: systemMessage has NO fabricated \$ figure" 0 "$fabricated4b"
case "$msg4b" in *"incomplete"*) incomplete_msg4b=1 ;; *) incomplete_msg4b=0 ;; esac
check "cost-report row4b: systemMessage says cost incomplete" 1 "$incomplete_msg4b"
check "cost-report row4b vs row3: messages are textually distinct" 1 "$([ "$msg4b" != "$msg" ] && echo 1 || echo 0)"
check "cost-report row4b vs row4: messages are textually distinct" 1 "$([ "$msg4b" != "$msg4" ] && echo 1 || echo 0)"

# (row 4c) complete + sv>=2 + .cost is a NON-EMPTY object but MISSING
# total_tokens (the sibling missing-field case) -> ALLOW, PRINT a distinct
# incomplete-cost message, no fabricated $ figure.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":2, "cost":{"total_usd_estimate":9.99}}'
run_capture_stdout "$(payload "$T" S1)"
check "cost-report row4c: sv2 + cost missing total_tokens -> allow" 0 "$RC_OUT"
msg4c=$(system_message "$STDOUT_OUT")
check "cost-report row4c: systemMessage is emitted (not silent)" 1 "$([ -n "$msg4c" ] && echo 1 || echo 0)"
case "$msg4c" in *'$'[0-9]*) fabricated4c=1 ;; *) fabricated4c=0 ;; esac
check "cost-report row4c: systemMessage has NO fabricated \$ figure" 0 "$fabricated4c"
case "$msg4c" in *"incomplete"*) incomplete_msg4c=1 ;; *) incomplete_msg4c=0 ;; esac
check "cost-report row4c: systemMessage says cost incomplete" 1 "$incomplete_msg4c"

# (row 5) non-complete category (e.g. hard-stop) -> SKIP, silent, no matter
# what .cost looks like on a stale retro from an earlier declaration.
reset; T=$(mk_transcript 1 "Work paused.
LOOP-STOP: hard-stop — pausing"); write_file in-progress S1 0
write_retro S1 '{"schema_version":2, "cost":{"total_usd_estimate":99.99,"total_tokens":1,"prices_as_of":"2026-01-01"}}'
run_capture_stdout "$(payload "$T" S1)"
check "cost-report row5: non-complete category -> allow" 0 "$RC_OUT"
check "cost-report row5: non-complete category -> silent" "" "$(system_message "$STDOUT_OUT")"

# (row 6) jq absent -> SKIP, silent (mirrors the existing NOJQ_BIN idiom used
# for the sibling gates above).
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":2, "cost":{"total_usd_estimate":1.23,"total_tokens":10,"prices_as_of":"2026-01-01"}}'
rc_nojq=$(run_env "PATH=$NOJQ_BIN" "$(payload "$T" S1)")
check "cost-report row6: jq absent -> allow (fail-open)" 0 "$rc_nojq"

# --- Negative controls -------------------------------------------------
# These exist so a stubbed-to-no-op or a stubbed-to-blocking reporter cannot
# pass this suite silently — a gate that never emits and never blocks proves
# nothing on its own.

# (a) Fails if the reporter is stubbed to a no-op: row 1's content assertions
# above (usd/token/staleness all present) already require real emission —
# restated here as an explicit non-empty-message assertion so the intent is
# unambiguous on its own.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":2, "cost":{"total_usd_estimate":7.5,"total_tokens":42,"prices_as_of":"2026-01-01"}}'
run_capture_stdout "$(payload "$T" S1)"
msg_noop_check=$(system_message "$STDOUT_OUT")
check "negative control: reporter is NOT a no-op (systemMessage non-empty on row1)" 1 "$([ -n "$msg_noop_check" ] && echo 1 || echo 0)"

# (b) Fails if the reporter is made to block. This must AGGREGATE REAL exit
# codes, not restate a literal: `check "..." 0 0` compares 0 to 0, calls no
# code, and passes under every implementation including a fully blocking one
# — a "negative control" that can never fail is a false assurance parading as
# the proof that the gate is real. Re-drive each row and sum the actual codes.
neverblock_sum=0
nb_row() { # <retro-json>
  reset; local t; t=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
  write_retro S1 "$1"
  run_capture_stdout "$(payload "$t" S1)"
  neverblock_sum=$((neverblock_sum + RC_OUT))
}
nb_row '{"schema_version":2, "cost":{"total_usd_estimate":7.5,"total_tokens":42,"prices_as_of":"2026-01-01"}}'
nb_row '{"schema_version":1}'
nb_row '{"schema_version":2, "cost":{}}'
nb_row '{"schema_version":2}'
nb_row '{"schema_version":2, "cost":{"total_tokens":123}}'
nb_row '{"schema_version":2, "cost":{"total_usd_estimate":"not-a-number","total_tokens":1,"prices_as_of":"2026-06-24"}}'
check "negative control: reporter never exits non-zero (summed real exit codes)" 0 "$neverblock_sum"

# Date-math fail-open: a malformed prices_as_of must not crash the hook or
# block the stop — it must fall back to printing the RAW prices_as_of string
# instead of a computed "N days old" age.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":2, "cost":{"total_usd_estimate":3.14,"total_tokens":100,"prices_as_of":"not-a-date"}}'
run_capture_stdout "$(payload "$T" S1)"
check "cost-report: malformed prices_as_of -> allow (date math fails open)" 0 "$RC_OUT"
msg_baddate=$(system_message "$STDOUT_OUT")
case "$msg_baddate" in *"not-a-date"*) raw_fallback=1 ;; *) raw_fallback=0 ;; esac
check "cost-report: malformed prices_as_of -> raw string falls back into the message" 1 "$raw_fallback"
case "$msg_baddate" in *"days old"*) computed_age=1 ;; *) computed_age=0 ;; esac
check "cost-report: malformed prices_as_of -> no fabricated 'days old' age computed" 0 "$computed_age"

# USD display rounding: the miner stores full float precision, which reads as
# noise in a one-line terminal report. Round to 2dp for display.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":2, "cost":{"total_usd_estimate":64.45735454999999,"total_tokens":93987957,"prices_as_of":"2026-06-24"}}'
run_capture_stdout "$(payload "$T" S1)"
msg_round=$(system_message "$STDOUT_OUT")
case "$msg_round" in *'$64.46'*) rounded=1 ;; *) rounded=0 ;; esac
check "cost-report: float-noise USD is rounded to 2dp for display" 1 "$rounded"
case "$msg_round" in *"45735454"*) raw_float=1 ;; *) raw_float=0 ;; esac
check "cost-report: raw float precision does not leak into the message" 0 "$raw_float"

# Anti-fabrication guard on the rounding path. `printf '%.2f'` does NOT fail on
# a non-numeric input — it silently prints 0.00 (verified). Rounding a garbage
# value would therefore FABRICATE "$0.00" from unusable data, which is the
# exact failure class this reporter exists to prevent. A non-numeric USD must
# print RAW (visibly wrong) rather than rounded (plausibly fabricated).
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":2, "cost":{"total_usd_estimate":"not-a-number","total_tokens":42,"prices_as_of":"2026-06-24"}}'
run_capture_stdout "$(payload "$T" S1)"
check "cost-report: non-numeric USD -> allow (never blocks)" 0 "$RC_OUT"
msg_nan=$(system_message "$STDOUT_OUT")
case "$msg_nan" in *'$0.00'*) fabricated=1 ;; *) fabricated=0 ;; esac
check "cost-report: non-numeric USD is NOT fabricated into \$0.00" 0 "$fabricated"
case "$msg_nan" in *"not-a-number"*) raw_shown=1 ;; *) raw_shown=0 ;; esac
check "cost-report: non-numeric USD falls back to the raw value" 1 "$raw_shown"

# Date-laundering guard. `date -j -f %Y-%m-%d` does NOT reject trailing
# garbage — it silently accepts "2026-06-24FORGED" and parses the leading
# date (verified). Without a strict shape check, a corrupt prices_as_of
# renders a confident "N days old" computed from an untrustworthy value:
# fabricated precision, the same failure class as the $0.00 guard above.
# Only an exact YYYY-MM-DD may reach the date math; anything else prints raw.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":2, "cost":{"total_usd_estimate":1,"total_tokens":2,"prices_as_of":"2026-06-24FORGED"}}'
run_capture_stdout "$(payload "$T" S1)"
check "cost-report: trailing-garbage date -> allow (never blocks)" 0 "$RC_OUT"
msg_launder=$(system_message "$STDOUT_OUT")
case "$msg_launder" in *"days old"*) laundered=1 ;; *) laundered=0 ;; esac
check "cost-report: trailing-garbage date does NOT fabricate a 'days old' age" 0 "$laundered"
case "$msg_launder" in *"2026-06-24FORGED"*) raw_kept=1 ;; *) raw_kept=0 ;; esac
check "cost-report: trailing-garbage date falls back to the raw string" 1 "$raw_kept"

# A clean date must STILL compute the age — the guard must not be so strict
# that it breaks the happy path it exists to protect.
reset; T=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":2, "cost":{"total_usd_estimate":1,"total_tokens":2,"prices_as_of":"2026-06-24"}}'
run_capture_stdout "$(payload "$T" S1)"
msg_clean=$(system_message "$STDOUT_OUT")
case "$msg_clean" in *"days old"*) still_computes=1 ;; *) still_computes=0 ;; esac
check "cost-report: a clean YYYY-MM-DD still computes the staleness age" 1 "$still_computes"

# Audit trail. Every sibling gate in this file logs its outcome via als_log
# (retro=3 calls, work_units=2, proofs=10); the reporter must too, per
# AGENTS.md's hook-script conventions. This matters most on the SILENT paths:
# a path that emits nothing to the human AND leaves no log line is
# indistinguishable from a broken one during an audit — which is precisely
# the failure class this reporter exists to close.
#
# The log records the outcome CLASS only, never the message body: the body
# interpolates retro.json-derived values, and als_log's newline sanitisation
# is a backstop, not a licence to widen what reaches the log.
cost_log_case() { # <retro-json> -> echoes the logged cost_report= class
  local lg="$TMP/costlog_${RANDOM}.txt"; : > "$lg"
  local st="$TMP/costlog_state_${RANDOM}.json"
  local rt; rt="$(dirname "$st")/retro.json"
  echo '{"schema_version":1,"status":"complete"}' > "$st"
  printf '%s' "$1" > "$rt"
  (
    # shellcheck disable=SC1090
    . "$(cd "$(dirname "$0")/.." && pwd)/lib/loop_state_common.sh" 2>/dev/null
    ALS_PATH="$st" LOG_FILE="$lg" \
      als_report_cost_on_complete "complete" "loop_stall_guard" "s"
  ) >/dev/null 2>&1
  grep -o 'cost_report=[a-z_0-9]*' "$lg" 2>/dev/null | head -1
}

check "cost-report log: populated cost -> cost_report=reported" \
  "cost_report=reported" \
  "$(cost_log_case '{"schema_version":2,"cost":{"total_usd_estimate":1,"total_tokens":2,"prices_as_of":"2026-06-24"}}')"
check "cost-report log: miner failed open -> cost_report=miner_failed_open" \
  "cost_report=miner_failed_open" \
  "$(cost_log_case '{"schema_version":2,"cost":{}}')"
check "cost-report log: cost absent -> cost_report=cost_absent" \
  "cost_report=cost_absent" \
  "$(cost_log_case '{"schema_version":2}')"
check "cost-report log: incomplete cost -> cost_report=cost_incomplete" \
  "cost_report=cost_incomplete" \
  "$(cost_log_case '{"schema_version":2,"cost":{"total_tokens":9}}')"
# The silent legacy path MUST still leave a trace — silence + no log is the
# indistinguishable-from-broken case above.
check "cost-report log: legacy sv1 silent path is still logged" \
  "cost_report=skipped_legacy_or_bad_sv" \
  "$(cost_log_case '{"schema_version":1}')"


# No retro-derived VALUE may reach the log — only the outcome class.
leak_lg="$TMP/costleak.txt"; : > "$leak_lg"
leak_st="$TMP/costleak_state.json"
echo '{"schema_version":1,"status":"complete"}' > "$leak_st"
printf '%s' '{"schema_version":2,"cost":{"total_usd_estimate":31337.42,"total_tokens":999,"prices_as_of":"2026-06-24"}}' \
  > "$(dirname "$leak_st")/retro.json"
(
  # shellcheck disable=SC1090
  . "$(cd "$(dirname "$0")/.." && pwd)/lib/loop_state_common.sh" 2>/dev/null
  ALS_PATH="$leak_st" LOG_FILE="$leak_lg" \
    als_report_cost_on_complete "complete" "loop_stall_guard" "s"
) >/dev/null 2>&1
leaked=$(grep -c "31337" "$leak_lg" 2>/dev/null); leaked=${leaked:-0}
check "cost-report log: no retro-derived value leaks into the log" 0 "$leaked"

# Non-scalar cost fields. `jq -r` on an array/object emits its PRETTY-PRINTED
# form — real newlines included — which lands inside the human-facing message
# ("Loop cost: $[\n  1,\n  2\n] (...)", verified before the fix). Two reasons
# that must not stand: it smuggles newlines into a report the terminal
# renders, and "$true"/"$[1,2]" is not a dollar figure a human can eyeball,
# so it fails the "visibly-wrong beats plausibly-fabricated" rule rather than
# satisfying it. A wrong-TYPE field is unusable data -> the incomplete path.
nonscalar_msg() { # <retro-json> -> the emitted systemMessage
  reset; local t; t=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
  write_retro S1 "$1"
  run_capture_stdout "$(payload "$t" S1)"
  system_message "$STDOUT_OUT"
}

m_arr=$(nonscalar_msg '{"schema_version":2,"cost":{"total_usd_estimate":[1,2,3],"total_tokens":10,"prices_as_of":"2026-06-24"}}')
case "$m_arr" in *"incomplete"*) arr_ok=1 ;; *) arr_ok=0 ;; esac
check "cost-report: array USD -> incomplete message (not a raw JSON blob)" 1 "$arr_ok"
check "cost-report: array USD -> message is single-line (no smuggled newlines)" 0 "$(printf '%s' "$m_arr" | grep -c '^' | awk '{print $1-1}')"

m_obj=$(nonscalar_msg '{"schema_version":2,"cost":{"total_usd_estimate":{"a":1},"total_tokens":10,"prices_as_of":"2026-06-24"}}')
case "$m_obj" in *"incomplete"*) obj_ok=1 ;; *) obj_ok=0 ;; esac
check "cost-report: object USD -> incomplete message" 1 "$obj_ok"

m_bool=$(nonscalar_msg '{"schema_version":2,"cost":{"total_usd_estimate":true,"total_tokens":10,"prices_as_of":"2026-06-24"}}')
case "$m_bool" in *'$true'*) bool_leaked=1 ;; *) bool_leaked=0 ;; esac
check "cost-report: boolean USD does not render as \"\$true\"" 0 "$bool_leaked"

m_atok=$(nonscalar_msg '{"schema_version":2,"cost":{"total_usd_estimate":1.5,"total_tokens":[9,9],"prices_as_of":"2026-06-24"}}')
case "$m_atok" in *"incomplete"*) atok_ok=1 ;; *) atok_ok=0 ;; esac
check "cost-report: array tokens -> incomplete message" 1 "$atok_ok"
check "cost-report: array tokens -> message is single-line" 0 "$(printf '%s' "$m_atok" | grep -c '^' | awk '{print $1-1}')"

# A non-scalar prices_as_of must not blow up the age path either; the cost
# figure itself is still good, so this must STILL report the cost.
m_apr=$(nonscalar_msg '{"schema_version":2,"cost":{"total_usd_estimate":2.5,"total_tokens":7,"prices_as_of":["x"]}}')
case "$m_apr" in *'$2.50'*) apr_reports=1 ;; *) apr_reports=0 ;; esac
check "cost-report: non-scalar prices_as_of still reports the cost figure" 1 "$apr_reports"
check "cost-report: non-scalar prices_as_of -> message is single-line" 0 "$(printf '%s' "$m_apr" | grep -c '^' | awk '{print $1-1}')"

# Float schema_version. als_gate_retro_on_complete validates schema_version
# with jq's NUMERIC >=, so 2.0 passes the gate and reaches this reporter. If
# the reporter compares in bash instead (string pattern match), the "." trips
# *[!0-9]* and a retro carrying a fully valid cost silently prints NOTHING —
# the exact bug this reporter exists to fix, surviving inside the fix. The
# two validators must agree on what a valid schema_version is. No float
# instance exists in the corpus yet, but schema_version is authored freehand
# by an LLM per prose, not emitted by trusted code.
m_float=$(nonscalar_msg '{"schema_version":2.0,"cost":{"total_usd_estimate":64.46,"total_tokens":93987957,"prices_as_of":"2026-06-24"}}')
check "cost-report: float schema_version 2.0 still reports (the retro gate accepts it, so must this)" 1 \
  "$([ -n "$m_float" ] && echo 1 || echo 0)"
case "$m_float" in *'$64.46'*) float_usd=1 ;; *) float_usd=0 ;; esac
check "cost-report: float schema_version 2.0 reports the real USD figure" 1 "$float_usd"

m_float25=$(nonscalar_msg '{"schema_version":2.5,"cost":{"total_usd_estimate":1.25,"total_tokens":5,"prices_as_of":"2026-06-24"}}')
check "cost-report: float schema_version 2.5 still reports" 1 "$([ -n "$m_float25" ] && echo 1 || echo 0)"

# ...but a float BELOW 2 must still grandfather silently, exactly like sv1 —
# the fix must not widen the gate it is correcting.
m_float19=$(nonscalar_msg '{"schema_version":1.9,"cost":{"total_usd_estimate":1,"total_tokens":1,"prices_as_of":"2026-06-24"}}')
check "cost-report: float schema_version 1.9 is still grandfathered (silent)" "" "$m_float19"

# Control-character neutralisation. jq --arg guarantees the JSON stays
# well-formed, NOT that the decoded string is safe to render: a live ESC
# (0x1B) survives JSON decode and reaches whatever draws the message. The
# harness's own handling is outside this repo and unknowable from here, so
# the hook strips control bytes itself rather than assuming — the same
# posture als_log already takes on its own newlines.
esc_char=$(printf '\033')
m_esc=$(nonscalar_msg "$(jq -cn --arg p "${esc_char}[2J${esc_char}[31mRED" \
  '{schema_version:2, cost:{total_usd_estimate:1.5, total_tokens:3, prices_as_of:$p}}')")
esc_present=$(printf '%s' "$m_esc" | LC_ALL=C grep -c "$esc_char" 2>/dev/null); esc_present=${esc_present:-0}
check "cost-report: ESC byte is stripped from the human-facing message" 0 "$esc_present"
check "cost-report: message with hostile prices_as_of is still emitted (not silenced)" 1 \
  "$([ -n "$m_esc" ] && echo 1 || echo 0)"
case "$m_esc" in *'$1.50'*) esc_usd=1 ;; *) esc_usd=0 ;; esac
check "cost-report: hostile prices_as_of does not suppress the real USD figure" 1 "$esc_usd"

# The stripper must not damage a normal message.
m_norm=$(nonscalar_msg '{"schema_version":2,"cost":{"total_usd_estimate":64.46,"total_tokens":93987957,"prices_as_of":"2026-06-24"}}')
case "$m_norm" in *'Loop cost: $64.46 (93987957 tokens), prices as of 2026-06-24, '*'days old'*) norm_ok=1 ;; *) norm_ok=0 ;; esac
check "cost-report: a normal message survives control-char stripping intact" 1 "$norm_ok"


# =====================================================================
# Price-table staleness NAG (distinct from the plain "N days old" age
# string already asserted above). prices_as_of is unverifiable self-report
# — it measures "days since a human typed a date here", not "are the rates
# still correct" — so past a threshold the reporter must also nudge a
# human to go check the rates, while still never blocking and still never
# suppressing the cost figure. The threshold is a named constant in the
# lib (ALS_PRICE_STALE_DAYS); these tests assert the behavioural boundary and
# read the value from source, never hardcoding it — an earlier revision named
# "30" here and survived the move to 14.

STALE45=$(date -u -v-45d +%Y-%m-%d 2>/dev/null || date -u -d '45 days ago' +%Y-%m-%d 2>/dev/null)
FRESH5=$(date -u -v-5d +%Y-%m-%d 2>/dev/null || date -u -d '5 days ago' +%Y-%m-%d 2>/dev/null)

# Stale (45 days — comfortably past any sane threshold) -> warning present,
# exit 0, and the message must say the DATE is old (never claim the rates
# themselves are wrong — that can't be known from a date alone).
# Deliberately described WITHOUT naming the threshold: an earlier revision of
# these strings said "30" and survived the threshold moving to 14, leaving a
# test whose name asserted one rule while its body tested another. The 45-day
# fixture is past both, so the assertion was never wrong — only its label was,
# which is worse: a misdescribed passing test misleads whoever reads it next.
m_stale=$(nonscalar_msg "$(jq -cn --arg d "$STALE45" '{schema_version:2, cost:{total_usd_estimate:9.99, total_tokens:100, prices_as_of:$d}}')")
case "$m_stale" in *"verify"*"pricing"*) stale_warn=1 ;; *) stale_warn=0 ;; esac
check "staleness nag: well-past-threshold prices_as_of (45d) -> warning present (names verify+pricing)" 1 "$stale_warn"
case "$m_stale" in *"rates are wrong"*|*"rates were wrong"*) claims_rates_wrong=1 ;; *) claims_rates_wrong=0 ;; esac
check "staleness nag: message never claims the RATES are wrong (date-only claim)" 0 "$claims_rates_wrong"
case "$m_stale" in *"9.99"*) stale_cost_present=1 ;; *) stale_cost_present=0 ;; esac
check "staleness nag: the cost figure is still reported alongside the nag" 1 "$stale_cost_present"

# Fresh (5 days, well under the threshold) -> NO staleness nag.
m_fresh=$(nonscalar_msg "$(jq -cn --arg d "$FRESH5" '{schema_version:2, cost:{total_usd_estimate:1.00, total_tokens:5, prices_as_of:$d}}')")
case "$m_fresh" in *"verify"*"pricing"*) fresh_warn=1 ;; *) fresh_warn=0 ;; esac
check "staleness nag: fresh prices_as_of (5 days) -> NO nag" 0 "$fresh_warn"

# Malformed prices_as_of ("not-a-date") must not crash or compute a bogus
# age/nag — reuses the same strict YYYY-MM-DD shape guard the existing age
# computation already relies on.
reset; T_bad=$(mk_transcript 1 "All done.
LOOP-STOP: complete — done"); write_file in-progress S1 0
write_retro S1 '{"schema_version":2, "cost":{"total_usd_estimate":2,"total_tokens":9,"prices_as_of":"not-a-date"}}'
run_capture_stdout "$(payload "$T_bad" S1)"
check "staleness nag: malformed prices_as_of -> allow (exit 0)" 0 "$RC_OUT"
m_bad=$(system_message "$STDOUT_OUT")
case "$m_bad" in *"verify"*"pricing"*) bad_warn=1 ;; *) bad_warn=0 ;; esac
check "staleness nag: malformed prices_as_of -> no bogus nag computed" 0 "$bad_warn"
case "$m_bad" in *"2.00"*) bad_cost_present=1 ;; *) bad_cost_present=0 ;; esac
check "staleness nag: malformed prices_as_of -> cost figure still reported" 1 "$bad_cost_present"

# The threshold must fire on the REAL shipped table, not just on synthetic
# fixtures. This caught a live defect: the nag was first written at 30 days
# while model_prices.json sat at prices_as_of 2026-06-24 (23 days old), so it
# was SILENT on the exact data that motivated building it — a feature that
# existed only inside its own tests. Reads the real table's date rather than
# hardcoding one, so this keeps working after a genuine price bump.
real_prices="$(cd "$(dirname "$0")/.." && pwd)/lib/model_prices.json"
# Read the threshold from the lib's source rather than expecting it in scope:
# this test file drives the guard as a subprocess and never sources the lib at
# top level, so the constant is not a shell variable here.
stale_days=$(grep -oE '^ALS_PRICE_STALE_DAYS=[0-9]+' \
  "$(cd "$(dirname "$0")/.." && pwd)/lib/loop_state_common.sh" 2>/dev/null | grep -oE '[0-9]+$')
# No plausible-looking fallback here, deliberately. If the grep above fails,
# a default of "30" would silently substitute a number that LOOKS like a real
# threshold, and this test would keep passing while measuring nothing — the
# same class of silent-wrong-answer the cost reporter itself exists to stop.
# Skip the check outright instead: an absent assertion is visible in the
# output; a fabricated one is not.
if [ -z "$stale_days" ]; then
  echo "ok   - staleness nag: real-table check SKIPPED (could not read ALS_PRICE_STALE_DAYS from source)"
  stale_days=""
fi
if [ -n "$stale_days" ] && [ -f "$real_prices" ] && command -v jq >/dev/null 2>&1; then
  real_date=$(jq -r '.prices_as_of // empty' "$real_prices" 2>/dev/null)
  case "$real_date" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9])
      real_epoch=$(date -j -f "%Y-%m-%d" "$real_date" +%s 2>/dev/null)
      if [ -n "$real_epoch" ]; then
        real_age=$(( ( $(date +%s) - real_epoch ) / 86400 ))
        m_real=$(nonscalar_msg "$(jq -cn --arg d "$real_date" \
          '{schema_version:2, cost:{total_usd_estimate:1, total_tokens:2, prices_as_of:$d}}')")
        case "$m_real" in *"checks the date only"*) real_nags=1 ;; *) real_nags=0 ;; esac
        # Only assert the nag when the real table is genuinely past the
        # threshold — right after a legitimate price bump it SHOULD be silent,
        # and this test must not then fail spuriously.
        if [ "$real_age" -gt "$stale_days" ]; then
          check "staleness nag: fires on the REAL shipped model_prices.json (${real_age}d old > ${stale_days}d)" 1 "$real_nags"
        else
          check "staleness nag: correctly silent on a freshly-bumped real table (${real_age}d old <= ${stale_days}d)" 0 "$real_nags"
        fi
      fi
      ;;
  esac
fi

# Exact boundary. The comparison is `-gt`, so a table exactly AT the threshold
# is silent and one day past it nags. That is a deliberate choice, not an
# accident — pin it, because an off-by-one here flips silently: the nag would
# either fire a day early forever or (worse) stay quiet a day longer than
# intended, and neither shows up in any other test.
bound_at=$(date -u -v-"${stale_days:-14}"d +%Y-%m-%d 2>/dev/null || date -u -d "${stale_days:-14} days ago" +%Y-%m-%d 2>/dev/null)
bound_past=$(date -u -v-"$(( ${stale_days:-14} + 1 ))"d +%Y-%m-%d 2>/dev/null || date -u -d "$(( ${stale_days:-14} + 1 )) days ago" +%Y-%m-%d 2>/dev/null)
if [ -n "$bound_at" ] && [ -n "$bound_past" ]; then
  m_at=$(nonscalar_msg "$(jq -cn --arg d "$bound_at" '{schema_version:2, cost:{total_usd_estimate:1, total_tokens:2, prices_as_of:$d}}')")
  case "$m_at" in *"checks the date only"*) at_nags=1 ;; *) at_nags=0 ;; esac
  check "staleness nag: exactly AT the threshold -> silent (comparison is -gt, not -ge)" 0 "$at_nags"

  m_past=$(nonscalar_msg "$(jq -cn --arg d "$bound_past" '{schema_version:2, cost:{total_usd_estimate:1, total_tokens:2, prices_as_of:$d}}')")
  case "$m_past" in *"checks the date only"*) past_nags=1 ;; *) past_nags=0 ;; esac
  check "staleness nag: one day PAST the threshold -> nags" 1 "$past_nags"
fi

# Future-dated prices_as_of. Rendered "-10 days old" before this was fixed:
# not a fabrication (no invented figure, nothing blocks) but nonsense to read
# and indistinguishable from a bug at a glance. Must say so plainly, still
# report the cost, and never nag (a future date is not stale).
fut=$(date -u -v+10d +%Y-%m-%d 2>/dev/null || date -u -d '10 days' +%Y-%m-%d 2>/dev/null)
if [ -n "$fut" ]; then
  m_fut=$(nonscalar_msg "$(jq -cn --arg d "$fut" '{schema_version:2, cost:{total_usd_estimate:3.5, total_tokens:7, prices_as_of:$d}}')")
  case "$m_fut" in *"-"[0-9]*" days old"*) neg_days=1 ;; *) neg_days=0 ;; esac
  check "staleness nag: future date does NOT render negative days old" 0 "$neg_days"
  case "$m_fut" in *"future"*) says_future=1 ;; *) says_future=0 ;; esac
  check "staleness nag: future date says so plainly" 1 "$says_future"
  case "$m_fut" in *'$3.50'*) fut_cost=1 ;; *) fut_cost=0 ;; esac
  check "staleness nag: future date still reports the cost figure" 1 "$fut_cost"
  case "$m_fut" in *"checks the date only"*) fut_nags=1 ;; *) fut_nags=0 ;; esac
  check "staleness nag: future date is not treated as stale" 0 "$fut_nags"
fi

# VT/FF must not survive the control-char strip. The original stripper used
# tr -c '[:print:][:space:]', and [:space:] INCLUDES VT (0x0b) and FF (0x0c) —
# so both passed straight through to the terminal, and the follow-up tr only
# mapped \n\r\t, leaving them with no second line of defence. FF clears the
# screen on many terminals. Pre-existing (shipped by PR #204), caught by the
# security pass on this PR, fixed here.
vt=$(printf '\013'); ff=$(printf '\014')
m_vtff=$(nonscalar_msg "$(jq -cn --arg p "2026-06-24${vt}VT${ff}FF" \
  '{schema_version:2, cost:{total_usd_estimate:1.25, total_tokens:4, prices_as_of:$p}}')")
vt_left=$(printf '%s' "$m_vtff" | LC_ALL=C grep -c "$vt" 2>/dev/null); vt_left=${vt_left:-0}
ff_left=$(printf '%s' "$m_vtff" | LC_ALL=C grep -c "$ff" 2>/dev/null); ff_left=${ff_left:-0}
check "control-char strip: VT (0x0b) does not survive into the message" 0 "$vt_left"
check "control-char strip: FF (0x0c) does not survive into the message" 0 "$ff_left"
case "$m_vtff" in *'$1.25'*) vtff_cost=1 ;; *) vtff_cost=0 ;; esac
check "control-char strip: hostile VT/FF prices_as_of still reports the cost" 1 "$vtff_cost"

# The tightened strip must not damage an ordinary message.
m_plain=$(nonscalar_msg '{"schema_version":2,"cost":{"total_usd_estimate":64.46,"total_tokens":93987957,"prices_as_of":"2026-06-24"}}')
case "$m_plain" in *'Loop cost: $64.46 (93987957 tokens), prices as of 2026-06-24, '*) plain_ok=1 ;; *) plain_ok=0 ;; esac
check "control-char strip: an ordinary message survives the tightened strip intact" 1 "$plain_ok"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
