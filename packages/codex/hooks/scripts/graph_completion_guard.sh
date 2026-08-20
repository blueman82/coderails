#!/usr/bin/env bash
# Stop: an active native graph cannot be left before graph.py complete succeeds.

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib/hook_common.sh"
hook::read_input

session_id=$(printf '%s' "$HOOK_INPUT" | jq -r '.session_id // empty' 2>/dev/null)
cwd=$(printf '%s' "$HOOK_INPUT" | jq -r '.cwd // empty' 2>/dev/null)
[[ -n "$session_id" && -n "$cwd" ]] || exit 0
state=$(hook::loop_state_path "$cwd" "$session_id") || exit 0
[[ -f "$state" ]] || exit 0

PLUGIN_ROOT="${PLUGIN_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
graph="$PLUGIN_ROOT/skills/agentic-loop/scripts/graph.py"
inspection=$(python3 "$graph" inspect "$state" 2>/dev/null) || {
    hook::continue_turn "The active Codex graph state is invalid. Repair progress.json before stopping."
    exit 0
}
[[ $(printf '%s' "$inspection" | jq -r '.session_id // empty') == "$session_id" ]] || {
    hook::continue_turn "The active Codex graph belongs to another session. Repair the state path before stopping."
    exit 0
}
hard_stop=$(printf '%s' "$inspection" | jq -r '.hard_stop != null')
message=$(printf '%s' "$HOOK_INPUT" | jq -r '.last_assistant_message // empty' 2>/dev/null)
if [[ "$hard_stop" == "true" && "$message" =~ LOOP-STOP:[[:space:]]*(waiting-on-human|stopped|stall) ]]; then
    exit 0
fi
loop_dir=$(dirname "$state")
if python3 "$graph" verify-completion "$state" --session "$session_id" \
    --evals "$loop_dir/evals.json" --proof "$loop_dir/proof.json" --retro "$loop_dir/retro.json" \
    >/dev/null 2>&1; then
    exit 0
fi

hook::log "hook=graph_completion_guard session=$session_id blocked=1"
hook::continue_turn "The native Codex graph is not complete. Resume from: $inspection"
exit 0
