#!/usr/bin/env bash
# PreToolUse apply_patch: keep temporary session labels out of code comments.

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
# The package root is resolved at runtime.
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib/hook_common.sh"
hook::read_input

command=$(printf '%s' "$HOOK_INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
content=$(printf '%s\n' "$command" | awk '
  /^\*\*\* (Add|Update) File:/ {
    path=$0; sub(/^\*\*\* (Add|Update) File: /, "", path); markdown=(path ~ /\.md$/); next
  }
  /^\*\*\* Delete File:/ { markdown=1; next }
  !markdown && /^\+/ { print substr($0, 2) }
')
[[ -n "$content" ]] || exit 0
uncited=$(printf '%s\n' "$content" | sed -e 's/\\"/@/g' -e 's/"[^"]*"/""/g')
pattern='\bE[0-9]+:|\bF[0-9]+ (fix|:|design)|CHANGE [BC][0-9]|\bTask A[0-9]+\b|TA-I[0-9]+|reviewer finding|eval E[0-9]+|\bWU[0-9]+:|\bC2\b|per the (plan|design|session)|per F[0-9]+'
match=$(printf '%s\n' "$uncited" | grep -Ei "$pattern" | head -n 1)
[[ -n "$match" ]] || exit 0
hook::deny "A new code comment cites a temporary session label. State the lasting constraint instead of referring to the plan, session, eval, task, or reviewer finding."
