#!/bin/bash
# PreToolUse Bash hook: block `git commit` if project has .claude/test_command and tests fail.
# Opt-in per project: if .claude/test_command does not exist, hook is a no-op.

IFS= read -r -d '' -t 30 input || true
cmd=$(echo "$input" | jq -r '.tool_input.command // empty')

if [ -z "$cmd" ] || ! echo "$cmd" | grep -qE '\bgit +commit\b'; then
  exit 0
fi

if [ ! -f ".claude/test_command" ]; then
  exit 0
fi

test_cmd=$(cat .claude/test_command | head -1)
if [ -z "$test_cmd" ]; then
  exit 0
fi

if ! eval "$test_cmd" >/tmp/claude_test_gate.log 2>&1; then
  log_tail=$(tail -20 /tmp/claude_test_gate.log | head -c 1500)
  jq -n --arg cmd "$test_cmd" --arg log "$log_tail" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: ("Test gate failed. Project test_command: " + $cmd + "\n\nLast 20 lines of output:\n" + $log)
    }
  }'
  exit 0
fi

exit 0
