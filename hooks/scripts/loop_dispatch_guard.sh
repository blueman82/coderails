#!/bin/bash
# PreToolUse hook (Agent) — Phase 2.7 dispatch-time enforcement. Mirrors
# loop_state_guard.sh's work-unit-count + loop-scope-evals check (see that
# file's gate_loop_evals_required), but fires BEFORE an implementation-unit
# worker is spawned instead of at loop completion. loop_state_guard.sh alone
# left a gap: a >=3-work-unit loop could dispatch every worker before
# evals.json ever existed, defeating the freeze-before-build discipline —
# the completion-time gate only ever caught it after the work was already
# done.
#
# Scope: this gate only inspects `Agent` dispatches whose subagent_type is
# coderails:loop-worker (the sole implementation-unit type per
# skills/agentic-loop/SKILL.md Phase 3/3a — confirmed by direct read, not
# assumed). Every other subagent_type (scouts, auditors, wiki-writer,
# generic, review agents, etc.) is out of scope and always allowed —
# narrowing to the one type this gate is meant to govern.
#
# Reuses the shared work-unit counter (als_read_work_units) and evals-result
# reader (als_read_loop_evals_result) from lib/loop_state_common.sh verbatim
# — same counting scheme and same GO/VERIFICATION_LEVEL0/NO-GO/UNJUSTIFIED/
# UNSTAMPED/ABSENT vocabulary loop_state_guard.sh already uses at
# completion, so the two gates can never disagree on what "graded" means.
#
# PreToolUse block contract (AGENTS.md "Hook script conventions"): emit
# hookSpecificOutput.permissionDecision:"deny" JSON to stdout, then exit 0 —
# never exit 2 in a PreToolUse hook (exit 2 is the Stop-hook contract
# loop_state_guard.sh uses; a different hook family, different contract).
#
# Fail-open posture (mirrors loop_state_guard.sh's own choices, not a new
# policy): no progress.json -> allow (no loop registered yet, or this
# dispatch predates Phase -2's stub write — nothing to gate against). Any
# read/parse failure inside the shared helpers already resolves to their
# own fail-open defaults (0 work units / ABSENT evals), so this hook adds
# no additional failure handling on top of what those helpers already do.

. "$(dirname "$0")/lib/loop_state_common.sh"

IFS= read -r -d '' -t 5 input || true

tool_name=$(printf '%s' "$input" | jq -r '.tool_name // empty' 2>/dev/null)
[ "$tool_name" = "Agent" ] || exit 0

subagent_type=$(printf '%s' "$input" | jq -r '.tool_input.subagent_type // empty' 2>/dev/null)
[ "$subagent_type" = "coderails:loop-worker" ] || exit 0

session_id=$(als_sanitise_session_id "$(printf '%s' "$input" | jq -r '.session_id // "?"' 2>/dev/null)")
cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null)
[ -z "$cwd" ] && cwd="$PWD"

als_path=$(als_resolve_path "$cwd" "$session_id")
[ -n "$als_path" ] && [ -f "$als_path" ] || exit 0

als_read_work_units "$als_path"
prior_count="$ALS_WORK_UNIT_COUNT"
next_dispatch_ordinal=$((prior_count + 1))

# Only the 3rd-or-later implementation-unit dispatch is gated (mirrors
# loop_state_guard.sh's own >= 3 threshold at completion) — a loop still
# below the threshold when this dispatch fires is exactly the 1-2-unit case
# Phase 2.7 never required a frozen evals.json for in the first place.
if [ "$next_dispatch_ordinal" -lt 3 ]; then
  als_log "hook=loop_dispatch_guard session=$session_id subagent_type=$subagent_type prior_units=$prior_count dispatch_ordinal=$next_dispatch_ordinal evals=skipped-below-threshold blocked=0"
  exit 0
fi

loop_dir=$(dirname "$als_path")
als_read_loop_evals_result "$loop_dir"

case "$ALS_LOOP_EVALS_RESULT" in
  GO|VERIFICATION_LEVEL0)
    als_log "hook=loop_dispatch_guard session=$session_id subagent_type=$subagent_type prior_units=$prior_count dispatch_ordinal=$next_dispatch_ordinal evals=$ALS_LOOP_EVALS_RESULT blocked=0"
    exit 0
    ;;
esac

als_log "hook=loop_dispatch_guard session=$session_id subagent_type=$subagent_type prior_units=$prior_count dispatch_ordinal=$next_dispatch_ordinal evals=$ALS_LOOP_EVALS_RESULT blocked=1"
reason="[loop-dispatch-guard] Blocked: this would be the #$next_dispatch_ordinal implementation-unit (coderails:loop-worker) dispatch in this loop (prior_units=$prior_count), but no frozen, graded loop-scope evals.json was found at:
  $loop_dir/evals.json
Phase 2.7c (freeze loop-scope evals via /coderails:task-evals) must run and be graded GO (or a justified verification_level-0 exemption) before a 3rd-or-later implementation-unit worker is dispatched — evals must be frozen BEFORE build, not checked only at loop completion. Current evals.json state: $ALS_LOOP_EVALS_RESULT."
jq -n --arg r "$reason" '{
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "deny",
    permissionDecisionReason: $r
  }
}'
exit 0
