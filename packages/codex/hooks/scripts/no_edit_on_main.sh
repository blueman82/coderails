#!/usr/bin/env bash
# PreToolUse apply_patch: protect native permission files and source on main.

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
# The package root is resolved at runtime.
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib/hook_common.sh"
hook::read_input

cwd=$(printf '%s' "$HOOK_INPUT" | jq -r '.cwd // empty' 2>/dev/null)
[[ -n "$cwd" ]] || cwd="$PWD"
paths=$(hook::patch_paths)
[[ -n "$paths" ]] || exit 0
blocked_file=""
blocked_branch=""
reason=""
while IFS= read -r file; do
    [[ -n "$file" ]] || continue
    case "$file" in
    .codex/config.toml | */.codex/config.toml | .codex/requirements.toml | */.codex/requirements.toml)
        blocked_file="$file"
        reason="Native Codex permission and hook configuration must be changed by the owner outside the agent."
        break
        ;;
    esac

    arm="code"
    case "$file" in
    */skills/*/SKILL.md | skills/*/SKILL.md | */commands/*.md | commands/*.md) arm="plugin-source" ;;
    esac
    if [[ "$arm" == "code" ]]; then
        base=${file##*/}
        case "$file" in *.md | *.txt | *.rst | *.yaml | *.yml | *.json | *.toml | *.ini | *.cfg) continue ;; esac
        case "$base" in .gitignore | LICENSE) continue ;; esac
    fi

    absolute=$(hook::absolute_path "$file" "$cwd")
    repo=$(hook::repo_for_path "$absolute")
    [[ -n "$repo" ]] || continue
    branch=$(git -C "$repo" branch --show-current 2>/dev/null)
    [[ "$branch" == "main" || "$branch" == "master" ]] || continue
    if [[ "$arm" == "plugin-source" && ! -f "$repo/.codex-plugin/plugin.json" ]]; then
        continue
    fi
    blocked_file="$file"
    blocked_branch="$branch"
    reason="Source files cannot be edited directly on '$branch'. Switch to a feature branch, then apply the patch there."
    break
done <<<"$paths"

[[ -n "$blocked_file" ]] || exit 0
hook::log "hook=no_edit_on_main decision=deny branch=$blocked_branch file=$blocked_file"
hook::deny "Blocked edit to '$blocked_file'. $reason"
