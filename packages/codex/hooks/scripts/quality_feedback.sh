#!/usr/bin/env bash
# PostToolUse apply_patch: warn on small, dependency-free source-quality checks.

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
# The package root is resolved at runtime.
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib/hook_common.sh"
hook::read_input

cwd=$(printf '%s' "$HOOK_INPUT" | jq -r '.cwd // empty' 2>/dev/null)
[[ -n "$cwd" ]] || cwd="$PWD"
checker="$SCRIPT_DIR/lib/quality_check.py"
[[ -f "$checker" ]] || exit 0
feedback=""
paths=$(hook::patch_paths)
while IFS= read -r file; do
    [[ -n "$file" ]] || continue
    absolute=$(hook::absolute_path "$file" "$cwd")
    [[ -f "$absolute" ]] || continue
    case "$absolute" in *.bash | *.cfg | *.js | *.json | *.jsx | *.md | *.py | *.sh | *.toml | *.ts | *.tsx | *.yaml | *.yml) ;; *) continue ;; esac
    repo=$(hook::repo_for_path "$absolute")
    [[ -n "$repo" ]] || continue
    output=$(python3 "$checker" --root "$repo" --paths "$absolute" 2>&1)
    printf '%s' "$output" | grep -q '0 finding(s)' && continue
    feedback="$feedback$output
"
done <<<"$paths"
[[ -n "$feedback" ]] || exit 0
feedback=$(printf '%s' "$feedback" | head -c 3000)
jq -n --arg feedback "coderails quality feedback (warn-only):
$feedback" '{hookSpecificOutput:{hookEventName:"PostToolUse", additionalContext:$feedback}}'
