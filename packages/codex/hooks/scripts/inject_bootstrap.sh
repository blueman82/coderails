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
        inspection=$(python3 "$PLUGIN_ROOT/skills/agentic-loop/scripts/graph.py" inspect "$state" 2>/dev/null)
        [[ -n "$inspection" ]] || inspection='invalid graph state; repair before dispatch'
        resume="$state: $inspection"
    else
        resume="no active graph; new graph path: $state"
    fi
fi
input=$HOOK_INPUT

if [[ -f "$SKILL" ]]; then
    context="Coderails is active. Load coderails-codex:using-coderails before acting, then every relevant native skill. Keep the top-level session as the orchestrator and delegate do-work tool calls with spawn_agent. Native graph resume: $resume"
else
    context="Coderails is active, but its native using-coderails skill is missing at $SKILL. Report this before substantive work. Native graph resume: $resume"
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
