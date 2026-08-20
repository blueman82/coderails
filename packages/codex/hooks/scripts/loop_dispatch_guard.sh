#!/usr/bin/env bash
# PreToolUse: graph-owned native worker dispatch must use this session's loop evidence.

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib/hook_common.sh"
hook::read_input

tool_name=$(printf '%s' "$HOOK_INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
[[ "$tool_name" == "spawn_agent" || "$tool_name" == "Agent" ]] || exit 0
task_name=$(printf '%s' "$HOOK_INPUT" | jq -r '.tool_input.task_name // empty' 2>/dev/null)
[[ "$task_name" == "loop-worker" || "$task_name" == loop-worker-* ]] || exit 0

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
[[ -f "$state" ]] || {
    hook::deny "Graph worker dispatch requires this session's progress.json. Start the native graph before spawn_agent."
    exit 0
}

PLUGIN_ROOT="${PLUGIN_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
graph="$PLUGIN_ROOT/skills/agentic-loop/scripts/graph.py"
if [[ ! -x "$graph" ]] || ! python3 "$graph" inspect "$state" >/dev/null 2>&1; then
    hook::deny "Graph worker dispatch requires valid graph state."
    exit 0
fi

owner=$(jq -r '.session_id // empty' "$state" 2>/dev/null)
loop_id=$(jq -r '.loop_id // empty' "$state" 2>/dev/null)
evals="$(dirname "$state")/evals.json"
if [[ "$owner" != "$session_id" ]]; then
    hook::deny "Graph worker dispatch is blocked because progress.json belongs to another session."
    exit 0
fi
if ! jq -e --arg session "$session_id" --arg loop "$loop_id" '
    .session_id == $session and .loop_id == $loop and
    (.result == "GO" or .result == "VERIFICATION_LEVEL0") and
    (.verification_justification | type == "string" and length > 0) and
    (.grading.by | type == "string" and length > 0) and
    (.grading.checksum | type == "string" and length > 0)
  ' "$evals" >/dev/null 2>&1; then
    hook::deny "Graph worker dispatch requires frozen, graded evals.json for this exact session and loop."
    exit 0
fi

hook::log "hook=loop_dispatch_guard session=$session_id loop=$loop_id task=$task_name blocked=0"
exit 0
