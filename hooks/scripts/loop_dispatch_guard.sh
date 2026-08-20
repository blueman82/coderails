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
# from spawn-sandboxed-worker.sh before launching the separate process, but are
# outside graph dispatch ownership; graph waves use native Agent calls only.
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
# Ownership check: graph-backed dispatch requires a prompt envelope bound to
# this session, loop, revision, active wave, and running node. evals.json is
# trusted only when it carries the same identity and a valid grading stamp.
#
# PreToolUse block contract (AGENTS.md "Hook script conventions"): emit
# hookSpecificOutput.permissionDecision:"deny" JSON to stdout, then exit 0 —
# never exit 2 in a PreToolUse hook (exit 2 is the Stop-hook contract
# loop_state_guard.sh uses; a different hook family, different contract).
#
# Fail-closed posture for loop work: an implementation worker without owned
# state is denied, and any graph-backed Agent dispatch requires a valid graph
# plus the exact active-wave envelope. An unrelated Agent call with no loop
# state remains outside this gate.

. "$(dirname "$0")/lib/loop_state_common.sh"
# shellcheck source=./lib/graph_executor.sh
. "$(dirname "$0")/lib/graph_executor.sh"

loop_dispatch_deny() { # reason state
    local deny_reason="$1" state="$2"
    als_log "hook=loop_dispatch_guard session=$session_id subagent_type=$subagent_type state=$state blocked=1"
    jq -n --arg r "[loop-dispatch-guard] Blocked: $deny_reason" \
        '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
    exit 0
}

IFS= read -r -d '' -t 5 input || true

tool_name=$(printf '%s' "$input" | jq -r '.tool_name // empty' 2>/dev/null)
subagent_type=$(printf '%s' "$input" | jq -r '.tool_input.subagent_type // empty' 2>/dev/null)
command=$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null)
prompt=$(printf '%s' "$input" | jq -r '.tool_input.prompt // empty' 2>/dev/null)
is_agent=0
is_worker=0
if [ "$tool_name" = "Agent" ]; then
    is_agent=1
    [ "$subagent_type" = "coderails:loop-worker" ] && is_worker=1
elif [ "$tool_name" = "Bash" ]; then
    case "$command" in
    *scripts/sandbox/spawn-sandboxed-worker.sh*)
        subagent_type="sandboxed-loop-worker"
        is_worker=1
        ;;
    esac
fi
[ "$is_agent" -eq 1 ] || [ "$is_worker" -eq 1 ] || exit 0

session_id=$(als_sanitise_session_id "$(printf '%s' "$input" | jq -r '.session_id // "?"' 2>/dev/null)")
cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null)
[ -z "$cwd" ] && cwd="$PWD"

als_path=$(als_resolve_path "$cwd" "$session_id")
[ -n "$als_path" ] && [ -f "$als_path" ] || {
    [ "$is_worker" -eq 1 ] || exit 0
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
    loop_dispatch_deny "$state_reason. Implementation workers require session-owned loop state before dispatch." "$ALS_LOOP_EVALS_RESULT"
fi

if [ "$is_agent" -eq 1 ] && jq -e '(.graph | type) == "object"' "$als_path" >/dev/null 2>&1; then
    graph_executor_graph_valid "$als_path" ||
        loop_dispatch_deny "graph state is malformed" "MALFORMED_GRAPH"

    dispatch_line="${prompt%%$'\n'*}"
    case "$dispatch_line" in
    CODERAILS_GRAPH_DISPATCH=*) dispatch_json="${dispatch_line#CODERAILS_GRAPH_DISPATCH=}" ;;
    *) loop_dispatch_deny "the Agent prompt is missing its CODERAILS_GRAPH_DISPATCH ownership envelope" "MISSING_ENVELOPE" ;;
    esac
    printf '%s' "$dispatch_json" | jq -e '
      type == "object"
      and ((keys - ["session_id","loop_id","revision","wave_id","node_id"]) | length == 0)
      and (.session_id | type) == "string" and (.session_id | length) > 0
      and (.loop_id | type) == "string" and (.loop_id | length) > 0
      and (.revision | type) == "number" and (.revision | floor) == .revision and .revision > 0
      and (.wave_id | type) == "string" and (.wave_id | length) > 0
      and (.node_id | type) == "string" and (.node_id | length) > 0
    ' >/dev/null 2>&1 || loop_dispatch_deny "the Agent dispatch envelope is malformed" "MALFORMED_ENVELOPE"

    jq -e --arg session "$session_id" --argjson dispatch "$dispatch_json" '
      .session_id == $session
      and .session_id == $dispatch.session_id
      and .loop_id == $dispatch.loop_id
      and .revision == $dispatch.revision
      and (.graph.active_wave | type) == "object"
      and .graph.active_wave.wave_id == $dispatch.wave_id
      and .graph.active_wave.revision == $dispatch.revision
      and (.graph.active_wave.nodes | index($dispatch.node_id)) != null
      and .graph.nodes[$dispatch.node_id].status == "running"
    ' "$als_path" >/dev/null 2>&1 ||
        loop_dispatch_deny "the Agent dispatch envelope does not own an exact node in the active wave" "FOREIGN_DISPATCH"
fi

[ "$is_worker" -eq 1 ] || exit 0

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
