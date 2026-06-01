#!/bin/bash
# PreToolUse Bash hook: permanently block destructive commands.
# Detects rm -rf, git push --force, git reset --hard, SQL DROP/TRUNCATE, dd, mkfs, chmod -R 777.
# Returns permissionDecision="deny" — there is no approval path; use a safer alternative or add a settings.json permission rule.

input=$(cat)
cmd=$(echo "$input" | jq -r '.tool_input.command // empty')

if [ -z "$cmd" ]; then
  exit 0
fi

# Conservative destructive-pattern set
pattern='\brm +(-[rRfF]+|--recursive|--force)|\bgit +push +.*(--force|-f\b|--force-with-lease)|\bgit +reset +--hard|\bDROP +(TABLE|DATABASE|SCHEMA)\b|\bTRUNCATE +TABLE\b|\bdd +if=|\bmkfs\.|\bchmod +-R +777|\bgit +commit +.*--no-verify'

if echo "$cmd" | grep -qiE "$pattern"; then
  matched=$(echo "$cmd" | grep -oiE "$pattern" | head -1)
  jq -n --arg pat "$matched" --arg cmd "$cmd" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: ("Destructive pattern detected: " + $pat + "\nFull command: " + $cmd + "\nThis command is permanently blocked. To allow it, add a Bash permission rule to settings.json or use a non-destructive alternative.")
    }
  }'
  exit 0
fi

exit 0
