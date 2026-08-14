#!/bin/bash
# UserPromptSubmit hook — inject current date, cwd, git branch into Claude's context.
# Also re-injects the discipline reminder on every prompt, so labels land in the
# first draft instead of being caught by the Stop hook after the fact.

IFS= read -r -d '' -t 5 input || true

ctx="[ctx] $(date '+%Y-%m-%d') | cwd=$(pwd) | branch=$(git branch --show-current 2>/dev/null || echo none)"
ctx="${ctx} | [discipline] Label every non-trivial claim (verified)/(inferred)/(guess). After multi-file changes include ## Did Not Verify listing what was not checked."

printf '{"hookSpecificOutput":{"hookEventName":"UserPromptSubmit","additionalContext":"%s"}}\n' "$ctx"
