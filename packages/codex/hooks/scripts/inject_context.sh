#!/usr/bin/env bash
# UserPromptSubmit: inject small, stable workspace context without reading transcripts.

IFS= read -r -d '' -t 5 input || true # EOF is normal; timeout fails open.
cwd=$(printf '%s' "$input" | jq -r '.cwd // empty' 2>/dev/null)
[[ -n "$cwd" ]] || cwd="$PWD"
branch=$(git -C "$cwd" branch --show-current 2>/dev/null)
[[ -n "$branch" ]] || branch="none"
context="[ctx] $(date '+%Y-%m-%d') | cwd=$cwd | branch=$branch | [discipline] Label substantive claims (verified), (inferred), or (guess)."
jq -n --arg context "$context" '{
  hookSpecificOutput: {hookEventName: "UserPromptSubmit", additionalContext: $context}
}'
