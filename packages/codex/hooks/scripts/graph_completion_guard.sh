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
transcript=$(printf '%s' "$HOOK_INPUT" | jq -r '.transcript_path // empty' 2>/dev/null)
if [[ "$hard_stop" == "true" ]]; then
    final_line=$(printf '%s\n' "$message" | awk 'NF { line = $0 } END { print line }')
    case "$final_line" in
    "LOOP-STOP: waiting-on-human" | "LOOP-STOP: stopped" | "LOOP-STOP: stall") exit 0 ;;
    esac
fi
loop_dir=$(dirname "$state")
if python3 "$graph" verify-completion "$state" --session "$session_id" \
    --evals "$loop_dir/evals.json" --proof "$loop_dir/proof.json" --retro "$loop_dir/retro.json" \
    --transcript "$transcript" \
    >/dev/null 2>&1; then
    exit 0
fi

if ! jq -e '
    (.graph | type) == "object" and
    (.graph.active_wave != null or .graph.hard_stop != null or
     ([.graph.nodes[]? | select((.status // "") | IN("done","skipped") | not)] | length) > 0 or
     ([.graph.joins[]? | select(.released != true)] | length) > 0)
  ' "$state" >/dev/null 2>&1; then
    hook::continue_turn "The native Codex graph passed graph checks but completion evidence is invalid. Repair evals, proof, or retro evidence before stopping."
    exit 0
fi

message="Human approval required: the native graph is unresolved. Approve the next action or resume the loop; stopping remains blocked until the graph is complete."
loop_id=$(jq -r '.loop_id // empty' "$state" 2>/dev/null)
revision=$(jq -r '.revision // empty' "$state" 2>/dev/null)
safe_loop=$(printf '%s' "$loop_id" | tr -c '[:alnum:]_.-' '_')
marker="$(dirname "$state")/.human-approval-${safe_loop}-${revision}"
hook::log "hook=graph_completion_guard session=$session_id blocked=1"
if [[ -n "$loop_id" && "$revision" =~ ^[0-9]+$ ]]; then
    if mkdir "$marker" 2>/dev/null; then
        :
    elif [[ -d "$marker" ]]; then
        hook::continue_turn "Native graph unresolved; stopping remains blocked."
        exit 0
    else
        hook::log "hook=graph_completion_guard session=$session_id human_request=dedupe_write_failed"
    fi
else
    # Keep invalid state fail-closed and visible without claiming it is a valid
    # unresolved graph.
    hook::continue_turn "Native graph unresolved; stopping remains blocked."
    exit 0
fi
if ! jq -n --arg reason "Native graph unresolved; stopping remains blocked." --arg message "$message" \
    '{decision:"block",reason:$reason,systemMessage:$message}'; then
    hook::log "hook=graph_completion_guard session=$session_id human_request=response_write_failed"
    if ! printf '%s\n' '{"decision":"block","reason":"Native graph unresolved; stopping remains blocked.","systemMessage":"Human approval required: the native graph is unresolved. Stopping remains blocked."}'; then
        rmdir "$marker" 2>/dev/null || true
        exit 2
    fi
fi
exit 0
