#!/bin/bash
# shellcheck disable=SC1091 # The shared hook library is resolved relative to this installed script.
# PreToolUse hook (Agent) — Phase 2.7 dispatch-time enforcement. Mirrors
# loop_state_guard.sh's work-unit-count + loop-scope-evals check (see that
# file's gate_loop_evals_required), but fires BEFORE an implementation-unit
# worker is spawned instead of at loop completion. loop_state_guard.sh alone
# left a gap: a >=3-work-unit loop could dispatch every worker before
# evals.json ever existed, defeating the freeze-before-build discipline —
# the completion-time gate only ever caught it after the work was already
# done.
#
# Scope: implementation workers only. In-process workers are Agent calls whose
# subagent_type is coderails:loop-worker. Sandboxed workers call this same guard
# from spawn-sandboxed-worker.sh before launching the separate process.
#
# Reuses the shared work-unit counter (als_read_work_units) and evals-result
# reader (als_read_loop_evals_result) from lib/loop_state_common.sh verbatim
# — same counting scheme and same GO/VERIFICATION_LEVEL0/NO-GO/UNJUSTIFIED/
# UNSTAMPED/ABSENT vocabulary loop_state_guard.sh already uses at
# completion, so the two gates can never disagree on what "graded" means.
#
# Threshold semantic: als_read_work_units counts every entry in the
# work_units OBJECT regardless of status — per loop-state.md's Fields table,
# work_units is a PLAN-TIME roster (entries exist with status "pending"
# BEFORE any dispatch, per Phase 1/2.7b), not a dispatch counter. So this
# gate reads work_units as "is this a >=3-unit loop" (loop_state_guard.sh's
# own semantic at completion), never as "is this the Nth dispatch" — a
# 3-unit loop's FIRST implementation-unit dispatch is gated exactly the same
# as its third, because the roster size (not dispatch count) is what decides
# whether Phase 2.7 ever applied to this loop at all.
#
# Ownership check (mirrors loop_state_guard.sh's own session_mismatch
# precedent): evals.json is only trusted when this session owns the
# progress.json it sits beside and carries the same stable loop_id. Revision
# is deliberately not bound at dispatch because begin-wave increments it
# before the worker is spawned; completion binds the final revision.
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
subagent_type=$(printf '%s' "$input" | jq -r '.tool_input.subagent_type // empty' 2>/dev/null)
command=$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null)
is_worker=0
if [ "$tool_name" = "Agent" ] && [ "$subagent_type" = "coderails:loop-worker" ]; then
    is_worker=1
elif [ "$tool_name" = "Bash" ]; then
    case "$command" in
    *scripts/sandbox/spawn-sandboxed-worker.sh*)
        subagent_type="sandboxed-loop-worker"
        is_worker=1
        ;;
    esac
fi
[ "$is_worker" -eq 1 ] || exit 0

session_id=$(als_sanitise_session_id "$(printf '%s' "$input" | jq -r '.session_id // "?"' 2>/dev/null)")
cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null)
[ -z "$cwd" ] && cwd="$PWD"

als_path=$(als_resolve_path "$cwd" "$session_id")
[ -n "$als_path" ] && [ -f "$als_path" ] || {
    ALS_LOOP_EVALS_RESULT="MISSING_STATE"
    unit_count=0
    loop_dir=$(dirname "$als_path")
    state_reason="no owned progress.json was found"
}

if [ -f "$als_path" ]; then
    als_read_file_state "$als_path"
    if [ "$ALS_SESSION" != "$session_id" ]; then
        ALS_LOOP_EVALS_RESULT="FOREIGN_STATE"
        unit_count=0
        loop_dir=$(dirname "$als_path")
        state_reason="progress.json belongs to session '$ALS_SESSION', not '$session_id'"
    elif jq -e '(.graph | type) == "object"' "$als_path" >/dev/null 2>&1 &&
        ! jq -e '(.loop_id | type) == "string" and (.loop_id | length) > 0 and
            (.revision | type) == "number" and (.revision | floor) == .revision' \
            "$als_path" >/dev/null 2>&1; then
        ALS_LOOP_EVALS_RESULT="MISSING_IDENTITY"
        unit_count=0
        loop_dir=$(dirname "$als_path")
        state_reason="graph state is missing a non-blank loop_id or integer revision"
    else
        state_reason=""
    fi
fi

if [ -n "$state_reason" ]; then
    als_log "hook=loop_dispatch_guard session=$session_id subagent_type=$subagent_type state=$ALS_LOOP_EVALS_RESULT blocked=1"
    reason="[loop-dispatch-guard] Blocked: $state_reason. Implementation workers require session-owned loop state before dispatch."
    jq -n --arg r "$reason" '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
    exit 0
fi

als_read_work_units "$als_path"
unit_count="$ALS_WORK_UNIT_COUNT"

# Roster-size threshold, not a dispatch ordinal: work_units is a PLAN-TIME
# roster (see header) — a >=3-unit loop is gated on EVERY implementation-unit
# dispatch, including its first, because the roster size alone is what
# decided Phase 2.7 applied to this loop.
if [ "$unit_count" -lt 3 ]; then
    als_log "hook=loop_dispatch_guard session=$session_id subagent_type=$subagent_type work_units=$unit_count evals=skipped-below-threshold blocked=0"
    exit 0
fi

loop_dir=$(dirname "$als_path")
als_read_loop_evals_result "$loop_dir"
loop_id=$(jq -r '.loop_id // ""' "$als_path" 2>/dev/null)
if [ -n "$loop_id" ] && ! jq -e --arg session "$session_id" --arg loop "$loop_id" \
    '.session_id == $session and .loop_id == $loop' \
    "$loop_dir/evals.json" >/dev/null 2>&1; then
    ALS_LOOP_EVALS_RESULT="STALE"
fi

case "$ALS_LOOP_EVALS_RESULT" in
GO | VERIFICATION_LEVEL0)
    als_log "hook=loop_dispatch_guard session=$session_id subagent_type=$subagent_type work_units=$unit_count evals=$ALS_LOOP_EVALS_RESULT blocked=0"
    exit 0
    ;;
esac

als_log "hook=loop_dispatch_guard session=$session_id subagent_type=$subagent_type work_units=$unit_count evals=$ALS_LOOP_EVALS_RESULT blocked=1"
reason="[loop-dispatch-guard] Blocked: this loop's work_units roster has $unit_count entries (>=3), but no frozen, graded loop-scope evals.json was found at:
  $loop_dir/evals.json
Phase 2.7c (freeze loop-scope evals via /coderails:task-evals) must run and be graded GO (or a justified verification_level-0 exemption) before any implementation-unit (coderails:loop-worker) worker is dispatched in a >=3-unit loop — evals must be frozen BEFORE build, not checked only at loop completion. Current evals.json state: $ALS_LOOP_EVALS_RESULT."
jq -n --arg r "$reason" '{
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "deny",
    permissionDecisionReason: $r
  }
}'
exit 0
