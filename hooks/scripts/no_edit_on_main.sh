#!/bin/bash
# PreToolUse hook (Write|Edit|MultiEdit): block edits to code files on the default branch.
# Enforces the worktree/branch discipline /workflow describes — main/master is for merges,
# not direct code edits. Only code extensions are gated; docs and config pass (the docs-only
# carve-out). Escape: create a feature branch first (/coderails:prep or a git worktree), or
# add a Write/Edit permission rule to settings.json. Emits permissionDecision=deny, the same
# PreToolUse idiom as destructive_bash_gate.sh.

input=$(cat)

file=$(printf '%s' "$input" | jq -r '.tool_input.file_path // empty')
[ -z "$file" ] && exit 0

# Only code files are gated; everything else (docs, config, etc.) passes freely.
case "$file" in
  *.py|*.ts|*.tsx|*.js|*.jsx|*.go) ;;
  *) exit 0 ;;
esac

dir=$(printf '%s' "$input" | jq -r '.cwd // empty')
[ -z "$dir" ] && dir="$PWD"

branch=$(git -C "$dir" branch --show-current 2>/dev/null)
case "$branch" in
  main|master) ;;
  *) exit 0 ;;
esac

reason="Blocked: editing a code file ($file) directly on '$branch'. Create a feature branch first (e.g. /coderails:prep or a git worktree), then edit there. For a genuine one-line hotfix, add a Write/Edit permission rule to settings.json."

jq -n --arg r "$reason" '{
  hookSpecificOutput: {
    hookEventName: "PreToolUse",
    permissionDecision: "deny",
    permissionDecisionReason: $r
  }
}'

# Structured discipline log (greppable key=value).
log="${CLAUDE_DISCIPLINE_LOG:-$HOME/.claude/discipline.log}"
printf 'hook=no_edit_on_main decision=deny branch=%s file=%s\n' "$branch" "$file" >> "$log" 2>/dev/null

exit 0
