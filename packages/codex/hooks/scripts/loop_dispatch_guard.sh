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
agent_type=$(printf '%s' "$HOOK_INPUT" | jq -r '.tool_input.agent_type // empty' 2>/dev/null)
[[ "$agent_type" == "loop-worker" ]] || exit 0
message=$(printf '%s' "$HOOK_INPUT" | jq -r '.tool_input.message // empty' 2>/dev/null)
task_name=$(printf '%s\n' "$message" | sed -n '1s/^CODERAILS_GRAPH_TASK=\(loop_worker_[0-9a-f][0-9a-f]*\(_a[2-9][0-9]*\)\{0,1\}\)$/\1/p')
[[ -n "$task_name" ]] || {
    hook::deny "Graph worker dispatch requires a canonical CODERAILS_GRAPH_TASK marker on the first message line."
    exit 0
}
session_id=$(printf '%s' "$HOOK_INPUT" | jq -r '.session_id // empty' 2>/dev/null)
cwd=$(printf '%s' "$HOOK_INPUT" | jq -r '.cwd // empty' 2>/dev/null)
[[ -n "$session_id" && -n "$cwd" ]] || {
    hook::deny "Graph worker dispatch requires a session id and working directory."
    exit 0
}
state=$(hook::loop_state_path "$cwd" "$session_id") || {
    hook::deny "Graph worker dispatch could not resolve this session's progress.json."
    exit 0
}
if [[ ! -f "$state" ]]; then
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
    hook::deny "A completed graph cannot dispatch graph workers."
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
