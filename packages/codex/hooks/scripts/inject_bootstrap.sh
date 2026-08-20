#!/usr/bin/env bash
# SessionStart: point Codex at its native skills and durable graph state.

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PLUGIN_ROOT="${PLUGIN_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
SKILL="$PLUGIN_ROOT/skills/using-coderails/SKILL.md"
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib/hook_common.sh"
hook::read_input

session_id=$(printf '%s' "$HOOK_INPUT" | jq -r '.session_id // empty' 2>/dev/null)
cwd=$(printf '%s' "$HOOK_INPUT" | jq -r '.cwd // empty' 2>/dev/null)
resume=""
if [[ -n "$session_id" && -n "$cwd" ]]; then
    state=$(hook::loop_state_path "$cwd" "$session_id")
    if [[ -f "$state" ]]; then
        resume=$(python3 "$PLUGIN_ROOT/skills/agentic-loop/scripts/graph.py" inspect "$state" 2>/dev/null)
        [[ -n "$resume" ]] || resume='invalid graph state; repair before dispatch'
    else
        resume="no active graph; new graph path: $state"
    fi
fi

if [[ -f "$SKILL" ]]; then
    context="Coderails is active. Load coderails-codex:using-coderails before acting, then every relevant native skill. Keep the top-level session as the orchestrator and delegate do-work tool calls with spawn_agent. Native graph resume: $resume"
else
    context="Coderails is active, but its native using-coderails skill is missing at $SKILL. Report this before substantive work. Native graph resume: $resume"
fi

jq -n --arg context "$context" '{
  hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $context}
}'
