#!/bin/bash
# UserPromptSubmit hook — inject current date, cwd, git branch into Claude's context.
# Also re-injects the discipline reminder on every prompt, so labels land in the
# first draft instead of being caught by the Stop hook after the fact.

IFS= read -r -d '' -t 5 input || true

ctx="[ctx] $(date '+%Y-%m-%d') | cwd=$(pwd) | branch=$(git branch --show-current 2>/dev/null || echo none)"
transcript_path=$(printf '%s' "$input" | jq -r '.transcript_path // empty' 2>/dev/null || true)
if [ -z "$transcript_path" ] || [ ! -s "$transcript_path" ]; then
    ctx="${ctx} | [discipline] Label every non-trivial claim (verified)/(inferred)/(guess). After multi-file changes include ## Did Not Verify listing what was not checked."
fi

printf '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"%s"}}\n' "$ctx"
