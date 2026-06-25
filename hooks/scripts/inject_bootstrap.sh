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

# JSON-escape via pure bash parameter substitution — bash-3.2/macOS-safe.
# Each substitution is a single pass; order matters (backslash first).
escape_for_json() {
  local s="$1"
  s="${s//\\/\\\\}"
  s="${s//\"/\\\"}"
  s="${s//$'\n'/\\n}"
  s="${s//$'\r'/\\r}"
  s="${s//$'\t'/\\t}"
  printf '%s' "$s"
}

skill_escaped=$(escape_for_json "$skill_content")
session_context="<EXTREMELY_IMPORTANT>\nYou have coderails.\n\n**Below is the full content of your 'coderails:using-coderails' skill — your introduction to using coderails skills. For all other skills, use the 'Skill' tool:**\n\n${skill_escaped}\n</EXTREMELY_IMPORTANT>"

# Emit Claude Code SessionStart format.
printf '{\n  "hookSpecificOutput": {\n    "hookEventName": "SessionStart",\n    "additionalContext": "%s"\n  }\n}\n' "$session_context" | cat

exit 0
