#!/usr/bin/env bash
# Shared native Codex hook helpers. Sourced; callers own shell options.

hook::read_input() {
    HOOK_INPUT=""
    IFS= read -r -d '' -t 5 HOOK_INPUT || true # EOF is normal; timeout fails open.
}

hook::deny() {
    jq -n --arg reason "$1" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason
    }
  }'
}

hook::continue_turn() {
    jq -n --arg reason "$1" '{decision: "block", reason: $reason}' ||
        printf '%s\n' '{"decision":"block","reason":"Coderails hook output failed; stopping remains blocked."}' ||
        exit 2
}

hook::data_dir() {
    printf '%s\n' "${PLUGIN_DATA:-$HOME/.coderails/codex}"
}

hook::log() {
    local data_dir log_file
    data_dir=$(hook::data_dir)
    mkdir -p "$data_dir" 2>/dev/null || return 0
    log_file="${CODERAILS_DISCIPLINE_LOG:-$data_dir/discipline.log}"
    printf '%s %s\n' "$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S%z)" "$1" >>"$log_file" 2>/dev/null || true
}

hook::session_dir() {
    local session_id safe data_dir
    session_id="$1"
    safe=$(printf '%s' "$session_id" | tr '/' '_' | sed 's/\.\.//g')
    [[ -n "$safe" ]] || return 1
    data_dir=$(hook::data_dir)
    printf '%s/sessions/%s\n' "$data_dir" "$safe"
}

hook::loop_root() {
    printf '%s\n' "${CODERAILS_AGENTIC_LOOP_DIR:-$HOME/.coderails/agentic-loop}"
}

hook::loop_state_path() {
    local cwd="$1" session_id="$2" safe root git_dir slug canonical candidate match=""
    safe=$(printf '%s' "$session_id" | tr '/' '_' | sed 's/\.\.//g')
    [[ -n "$safe" ]] || return 1
    root=$(hook::loop_root)
    git_dir=$(git -C "$cwd" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
    case "$git_dir" in
      /*) slug=$(printf '%s' "$git_dir" | sed 's#/#-#g') ;;
      *) slug=$(printf '%s' "$cwd" | sed 's#/#-#g') ;;
    esac
    canonical="$root/$slug/$safe/progress.json"
    if [[ -e "$canonical" ]]; then
        printf '%s\n' "$canonical"
        return 0
    fi
    for candidate in "$root"/*/"$safe"/progress.json; do
        [[ -e "$candidate" ]] || continue
        [[ -z "$match" || "$candidate" < "$match" ]] && match="$candidate"
    done
    printf '%s\n' "${match:-$canonical}"
}

hook::patch_paths() {
    local command
    command=$(printf '%s' "$HOOK_INPUT" | jq -r '.tool_input.command // empty' 2>/dev/null)
    printf '%s\n' "$command" | sed -nE \
        -e 's/^\*\*\* (Add|Update|Delete) File: (.*)$/\2/p' \
        -e 's/^\*\*\* Move to: (.*)$/\1/p'
}

hook::absolute_path() {
    local path="$1" cwd="$2"
    case "$path" in
    /*) printf '%s\n' "$path" ;;
    *) printf '%s/%s\n' "$cwd" "$path" ;;
    esac
}

hook::repo_for_path() {
    local path="$1" probe
    probe=$(dirname "$path")
    while [[ ! -d "$probe" && "$probe" != "/" ]]; do
        probe=$(dirname "$probe")
    done
    git -C "$probe" rev-parse --show-toplevel 2>/dev/null
}
