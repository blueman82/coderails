#!/bin/bash
# UserPromptSubmit hook — inject current date, cwd, git branch into Claude's context.
# Provides freshness signals on every prompt without depending on Claude's memory.
# On the first prompt of a session, also re-injects the discipline reminder.

IFS= read -r -d '' -t 30 input || true
transcript=$(echo "$input" | jq -r '.transcript_path // empty')

ctx="[ctx] $(date '+%Y-%m-%d') | cwd=$(pwd) | branch=$(git branch --show-current 2>/dev/null || echo none)"

# First prompt of session = no prior assistant turns in transcript
if [ -n "$transcript" ] && [ -f "$transcript" ]; then
  prior=$(jq -s '[.[]? | select(.type == "assistant")] | length' "$transcript" 2>/dev/null)
  if [ "${prior:-0}" -eq 0 ]; then
    ctx="${ctx} | [discipline] Label every non-trivial claim (verified)/(inferred)/(guess). After multi-file changes include ## Did Not Verify listing what was not checked."
  fi
fi

printf '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"%s"}}\n' "$ctx"
