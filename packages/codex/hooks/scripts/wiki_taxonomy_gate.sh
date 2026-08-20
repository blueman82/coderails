#!/usr/bin/env bash
# PreToolUse apply_patch: keep writes inside the configured wiki taxonomy.

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
# The package root is resolved at runtime.
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib/hook_common.sh"
hook::read_input

cwd=$(printf '%s' "$HOOK_INPUT" | jq -r '.cwd // empty' 2>/dev/null)
[[ -n "$cwd" ]] || cwd="$PWD"
project_root=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null)
[[ -n "$project_root" ]] || exit 0
probe="$cwd"
config=""
while :; do
    if [[ -f "$probe/.codex/workflow.config.yaml" ]]; then
        config="$probe/.codex/workflow.config.yaml"
        break
    fi
    [[ "$probe" == "$project_root" ]] && break
    probe=$(dirname "$probe")
done
[[ -n "$config" ]] || exit 0
schema="$project_root/AGENTS-wiki-schema.md"
[[ -f "$schema" ]] || exit 0
section=$(awk '/^## Page types/{active=1; next} /^## /{active=0} active' "$schema")
# Backticks are literal wiki markup in this regular expression.
# shellcheck disable=SC2016
sanctioned=$(printf '%s\n' "$section" | grep -oE '`[A-Za-z0-9_-]+/`' | tr -d '`')
[[ -n "$sanctioned" ]] || exit 0
wiki_path=$(awk '/^wiki_path:/{print $2; exit}' "$config" | sed -E 's/^"(.*)"$/\1/; s/^'"'"'(.*)'"'"'$/\1/')
case "$wiki_path" in "" | null | '~') exit 0 ;; esac
config_dir=$(dirname "$config")
case "$wiki_path" in
/*) vault="$wiki_path" ;;
*) vault="$config_dir/$wiki_path" ;;
esac
vault=$(cd "$vault" 2>/dev/null && pwd -P)
[[ -n "$vault" ]] || exit 0
present=0
while IFS= read -r dir; do [[ -d "$vault/$dir" ]] && present=$((present + 1)); done <<<"$sanctioned"
[[ "$present" -ge 2 ]] || exit 0

paths=$(hook::patch_paths)
while IFS= read -r file; do
    [[ -n "$file" ]] || continue
    absolute=$(hook::absolute_path "$file" "$cwd")
    repo=$(hook::repo_for_path "$absolute")
    [[ "$repo" == "$vault" ]] || continue
    absolute=$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$absolute" 2>/dev/null)
    case "$absolute" in "$vault"/*) rel=${absolute#"$vault"/} ;; *) continue ;; esac
    case "$rel" in */*) ;; *) continue ;; esac
    topdir=${rel%%/*}/
    case "$topdir" in raw/ | .git/ | .obsidian/ | .codex/) continue ;; esac
    allowed=0
    while IFS= read -r dir; do [[ "$dir" == "$topdir" ]] && allowed=1; done <<<"$sanctioned"
    [[ "$allowed" -eq 1 ]] && continue
    list=$(printf '%s' "$sanctioned" | tr '\n' ' ')
    hook::log "hook=wiki_taxonomy_gate decision=deny file=$file topdir=$topdir"
    hook::deny "'$topdir' is not a sanctioned wiki directory for '$file'. Allowed directories from $schema: $list"
    exit 0
done <<<"$paths"
