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
# coderails:loop-worker — the implementation-unit type used by the in-process
# Agent-tool dispatch path in skills/agentic-loop/SKILL.md Phase 3/3a
# (confirmed by direct read, not assumed). Every other subagent_type (scouts,
# auditors, wiki-writer, generic, review agents, etc.) is out of scope and
# always allowed — narrowing to the one type this gate is meant to govern.
#
# KNOWN CEILING (SKILL.md line ~93): when config.sandbox_workers is true,
# implementation-unit workers dispatch via
# scripts/sandbox/spawn-sandboxed-worker.sh as a separate OS process (npx
# exec), never as an in-process Agent tool_use — so this hook's
# PreToolUse:Agent matcher never fires for the sandboxed path at all. This
# gate does not, and cannot, cover sandboxed dispatch; out of scope for this
# hook, not a bug.
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
# progress.json it sits beside (ALS_SESSION == session_id) — a stray
# evals.json belonging to a foreign session's progress.json at this path
# must never satisfy this gate. KNOWN CEILING: this does NOT detect a
# same-session RE-ARM (Phase -2 stub-first resets status to "initialising",
# but by the time Phase 3 dispatches a worker, status has already advanced
# to "in-progress" indistinguishably from a fresh loop — and evals.json
# itself carries no loop-instance identity for a dispatch-time check to
# compare against). A re-armed loop, in the SAME session, whose 3rd-unit
# dispatch finds a stale evals.json left over from a PRIOR completed loop at
# this same path can still pass through ungated. Closing that gap needs
# either evals.json to carry loop-instance identity or Phase -2 stub-first
# to clear/rename a prior evals.json — both are schema/skill changes outside
# this hook's scope; not closed here.
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

als_read_file_state "$als_path"
[ "$ALS_SESSION" = "$session_id" ] || exit 0

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

case "$ALS_LOOP_EVALS_RESULT" in
  GO|VERIFICATION_LEVEL0)
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
