#!/usr/bin/env bash
# PreToolUse: graph-owned native worker dispatch must use this session's loop evidence.

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib/hook_common.sh"
hook::read_input

tool_name=$(printf '%s' "$HOOK_INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
[[ "$tool_name" == "spawn_agent" ]] || {
    hook::deny "Codex graph workers must use native spawn_agent."
    exit 0
}
task_name=$(printf '%s' "$HOOK_INPUT" | jq -r '.tool_input.task_name // empty' 2>/dev/null)
session_id=$(printf '%s' "$HOOK_INPUT" | jq -r '.session_id // empty' 2>/dev/null)
cwd=$(printf '%s' "$HOOK_INPUT" | jq -r '.cwd // empty' 2>/dev/null)
[[ -n "$session_id" && -n "$cwd" ]] || {
    [[ "$task_name" == loop_worker_* || "$task_name" == loop-worker-* ]] || exit 0
    hook::deny "Graph worker dispatch requires a session id and working directory."
    exit 0
}
state=$(hook::loop_state_path "$cwd" "$session_id") || {
    hook::deny "Graph worker dispatch could not resolve this session's progress.json."
    exit 0
}
if [[ ! -f "$state" ]]; then
    [[ "$task_name" == loop_worker_* || "$task_name" == loop-worker-* ]] || exit 0
    hook::deny "Graph worker dispatch requires this session's progress.json. Start the native graph before spawn_agent."
    exit 0
fi

PLUGIN_ROOT="${PLUGIN_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
graph="$PLUGIN_ROOT/skills/agentic-loop/scripts/graph.py"
evals="$(dirname "$state")/evals.json"
[[ -x "$graph" ]] || {
    hook::deny "Graph worker dispatch requires the provider-local graph helper."
    exit 0
}
inspection=$(python3 "$graph" inspect "$state" 2>/dev/null) || {
    hook::deny "Graph worker dispatch requires valid provider-local graph state."
    exit 0
}
if [[ $(printf '%s' "$inspection" | jq -r '.status // empty') == "complete" ]]; then
    case "$task_name" in
    loop_worker_* | loop-worker-*) hook::deny "A completed graph cannot dispatch graph workers." ;;
    esac
    exit 0
fi
authorization=$(python3 "$graph" authorize-dispatch "$state" \
    --session "$session_id" --task "$task_name" --evals "$evals" 2>/dev/null)
if [[ -z "$authorization" ]]; then
    hook::deny "Graph worker dispatch requires valid state, active-wave ownership, and graded loop evidence."
    exit 0
fi

loop_id=$(printf '%s' "$authorization" | jq -r '.loop_id')
wave_id=$(printf '%s' "$authorization" | jq -r '.wave_id')
hook::log "hook=loop_dispatch_guard session=$session_id loop=$loop_id wave=$wave_id task=$task_name blocked=0"
exit 0
