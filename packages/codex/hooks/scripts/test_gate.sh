#!/usr/bin/env bash
# PreToolUse Bash: run an opt-in project test command before git commit.

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
# The package root is resolved at runtime.
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib/hook_common.sh"
hook::read_input

command=$(printf '%s' "$HOOK_INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
printf '%s' "$command" | grep -qE '(^|[[:space:];&|])git[[:space:]]+commit([[:space:]]|$)' || exit 0
cwd=$(printf '%s' "$HOOK_INPUT" | jq -r '.cwd // empty' 2>/dev/null)
[[ -n "$cwd" ]] || cwd="$PWD"
repo_root=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null) || exit 0
config=$(git -C "$repo_root" rev-parse --git-path coderails/test_command 2>/dev/null) || exit 0
case "$config" in /*) ;; *) config="$repo_root/$config" ;; esac
[[ -f "$config" ]] || exit 0
IFS= read -r test_command <"$config" || true
[[ -n "$test_command" ]] || exit 0

log_file=$(mktemp "${TMPDIR:-/tmp}/coderails-test-gate.XXXXXX") || {
    hook::deny "Test gate could not create a temporary output file, so the commit is blocked."
    exit 0
}
trap 'rm -f "$log_file"' EXIT
if ! (cd "$repo_root" && /bin/bash -c "$test_command") >"$log_file" 2>&1; then
    output=$(tail -n 20 "$log_file" | head -c 1500)
    hook::deny "Test gate failed for: $test_command

Last output:
$output"
fi
