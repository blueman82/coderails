#!/usr/bin/env bash
# PreToolUse Bash: block the third full-suite or eval-ceremony run per branch.

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
# The package root is resolved at runtime.
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib/hook_common.sh"
hook::read_input

command=$(printf '%s' "$HOOK_INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null | tr '\n' ' ')
target=""
if printf '%s' "$command" | grep -qE '(^|[&;|])[[:space:]]*(bash[[:space:]]+|sh[[:space:]]+|\./)?([^[:space:]]*/)?(hooks/scripts/tests/run_all|packages/tests/codex_hooks\.test)\.sh([[:space:]]|$)'; then
    target="full-suite"
elif printf '%s' "$command" | grep -qE '(^|[&;|])[[:space:]]*(bash[[:space:]]+|sh[[:space:]]+|\./)?([^[:space:]]*/)?scripts/post_evals\.sh[[:space:]]+validate-structure([[:space:]]|$)'; then
    target="eval-ceremony"
else
    exit 0
fi

cwd=$(printf '%s' "$HOOK_INPUT" | jq -r '(.tool_input.workdir | select(type == "string" and length > 0)) // (.cwd | select(type == "string" and length > 0)) // empty' 2>/dev/null)
[[ -n "$cwd" ]] || cwd="$PWD"
branch=$(git -C "$cwd" branch --show-current 2>/dev/null)
[[ -n "$branch" ]] || branch="no-branch"
branch_slug=$(printf '%s' "$branch" | tr '/ ' '--')
data_dir=$(hook::data_dir)
state_dir="$data_dir/verification-ceiling"
mkdir -p "$state_dir" 2>/dev/null || {
    hook::deny "Verification-volume ceiling cannot create its state directory, so it is failing closed."
    exit 0
}
count_file="$state_dir/${branch_slug}__${target}.count"
lock_dir="$count_file.lock"
attempt=0
while ! mkdir "$lock_dir" 2>/dev/null; do
    attempt=$((attempt + 1))
    if [[ "$attempt" -ge 15 ]]; then
        hook::deny "Verification-volume ceiling could not acquire its branch lock, so it is failing closed."
        exit 0
    fi
    sleep 0.1
done
trap 'rmdir "$lock_dir" 2>/dev/null || true' EXIT
count=$(awk 'NR==1 && /^[0-9]+$/{print; found=1} END{if(!found) print 0}' "$count_file" 2>/dev/null)
printf '%s\n' "$((count + 1))" >"$count_file" 2>/dev/null || {
    hook::deny "Verification-volume ceiling could not update its count, so it is failing closed."
    exit 0
}
[[ "$count" -lt 2 ]] || hook::deny "This is run $((count + 1)) of the same $target on branch '$branch'. The third and later full re-runs are blocked; use a focused check or delegate verification with spawn_agent."
