#!/usr/bin/env bash
# SessionStart hook — injects the using-coderails skill into every new session
# so coderails self-bootstraps at session start.

set -euo pipefail

input=$(cat 2>/dev/null || true)

# Locate plugin root: prefer CLAUDE_PLUGIN_ROOT env var, fall back to the
# directory two levels above this script (hooks/scripts/ -> plugin root).
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-"$(cd "${SCRIPT_DIR}/../.." && pwd)"}"

SKILL_FILE="${PLUGIN_ROOT}/skills/using-coderails/SKILL.md"

source_kind=$(printf '%s' "$input" | jq -r '.source // empty' 2>/dev/null || true)
cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null || true)
nudge=""
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
            nudge=$'\n\nLegacy Coderails workflow configuration found. Run /coderails:init to migrate it to .coderails/workflow.config.yaml.'
        fi
    fi
fi

if [ -f "$SKILL_FILE" ]; then
    skill_content=$(cat "$SKILL_FILE")
else
    skill_content="(coderails: using-coderails skill not found at ${SKILL_FILE})"
fi

session_context="<EXTREMELY_IMPORTANT>
You have coderails.

**Below is the full content of your 'coderails:using-coderails' skill — your introduction to using coderails skills. For all other skills, use the 'Skill' tool:**

${skill_content}
</EXTREMELY_IMPORTANT>${nudge}"

# Emit Claude Code SessionStart format.
# jq handles all JSON escaping exactly once — no manual escaping needed.
jq -n --arg ctx "$session_context" '{
  hookSpecificOutput: {
    hookEventName: "SessionStart",
    additionalContext: $ctx
  }
}'

exit 0
