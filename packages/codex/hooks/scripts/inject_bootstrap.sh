#!/usr/bin/env bash
# SessionStart: point Codex at its native skills and delegation tool.

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PLUGIN_ROOT="${PLUGIN_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
SKILL="$PLUGIN_ROOT/skills/using-coderails/SKILL.md"

if [[ -f "$SKILL" ]]; then
    context="Coderails is active. Before any response or action, load and follow the native coderails-codex:using-coderails skill, then load every other relevant native skill. Keep the top-level session as the orchestrator and delegate do-work tool calls with spawn_agent. Include the relevant skill instructions in each delegated prompt."
else
    context="Coderails is active, but its native using-coderails skill is missing at $SKILL. Report the missing plugin file before substantive work. Keep the top-level session as the orchestrator and delegate do-work tool calls with spawn_agent."
fi

jq -n --arg context "$context" '{
  hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $context}
}'
