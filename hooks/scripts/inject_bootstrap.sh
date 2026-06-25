#!/usr/bin/env bash
# SessionStart hook — injects the using-coderails skill into every new session
# so coderails self-bootstraps at session start.

set -euo pipefail

# Locate plugin root: prefer CLAUDE_PLUGIN_ROOT env var, fall back to the
# directory two levels above this script (hooks/scripts/ -> plugin root).
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLUGIN_ROOT="${CLAUDE_PLUGIN_ROOT:-"$(cd "${SCRIPT_DIR}/../.." && pwd)"}"

SKILL_FILE="${PLUGIN_ROOT}/skills/using-coderails/SKILL.md"

if [ -f "$SKILL_FILE" ]; then
  skill_content=$(cat "$SKILL_FILE")
else
  skill_content="(coderails: using-coderails skill not found at ${SKILL_FILE})"
fi

session_context="<EXTREMELY_IMPORTANT>
You have coderails.

**Below is the full content of your 'coderails:using-coderails' skill — your introduction to using coderails skills. For all other skills, use the 'Skill' tool:**

${skill_content}
</EXTREMELY_IMPORTANT>"

# Emit Claude Code SessionStart format.
# jq handles all JSON escaping exactly once — no manual escaping needed.
jq -n --arg ctx "$session_context" '{
  hookSpecificOutput: {
    hookEventName: "SessionStart",
    additionalContext: $ctx
  }
}'

exit 0
