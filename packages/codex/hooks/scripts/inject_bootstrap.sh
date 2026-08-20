#!/usr/bin/env bash
# SessionStart: point Codex at its native skills and delegation tool.

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PLUGIN_ROOT="${PLUGIN_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
SKILL="$PLUGIN_ROOT/skills/using-coderails/SKILL.md"
input=$(cat 2>/dev/null || true)

if [[ -f "$SKILL" ]]; then
    context="Coderails is active. Before any response or action, load and follow the native coderails-codex:using-coderails skill, then load every other relevant native skill. Keep the top-level session as the orchestrator and delegate do-work tool calls with spawn_agent. Include the relevant skill instructions in each delegated prompt."
else
    context="Coderails is active, but its native using-coderails skill is missing at $SKILL. Report the missing plugin file before substantive work. Keep the top-level session as the orchestrator and delegate do-work tool calls with spawn_agent."
fi

source_kind=$(printf '%s' "$input" | jq -r '.source // empty' 2>/dev/null || true)
cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null || true)
if [[ "$source_kind" == "startup" && -n "$cwd" ]]; then
    git_root=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null || true)
    if [[ -n "$git_root" ]]; then
        probe=$(cd "$cwd" 2>/dev/null && pwd -P || true)
        legacy_found=0
        while [[ -n "$probe" ]]; do
            if [[ -f "$probe/.coderails/workflow.config.yaml" ]]; then
                legacy_found=0
                break
            fi
            if [[ -f "$probe/.claude/workflow.config.yaml" || -f "$probe/.codex/workflow.config.yaml" ]]; then
                legacy_found=1
            fi
            [[ "$probe" == "$git_root" || "$probe" == "/" ]] && break
            probe=$(dirname "$probe")
        done
        if [[ "$legacy_found" -eq 1 ]]; then
            context+=$'\n\nLegacy Coderails workflow configuration found. Run $coderails-codex:init to migrate it to .coderails/workflow.config.yaml.'
        fi
    fi
fi

jq -n --arg context "$context" '{
  hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $context}
}'
