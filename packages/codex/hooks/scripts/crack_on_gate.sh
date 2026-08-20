#!/usr/bin/env bash
# Stamp a session when the user says "crack on"; deny native human-input requests.

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
# The package root is resolved at runtime.
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib/hook_common.sh"
hook::read_input

event=$(printf '%s' "$HOOK_INPUT" | jq -r '.hook_event_name // empty' 2>/dev/null)
session_id=$(printf '%s' "$HOOK_INPUT" | jq -r '.session_id // empty' 2>/dev/null)
[[ -n "$session_id" ]] || exit 0
session_dir=$(hook::session_dir "$session_id") || exit 0
flag="$session_dir/crack_on_active"

if [[ "$event" == "UserPromptSubmit" ]]; then
    prompt=$(printf '%s' "$HOOK_INPUT" | jq -r '.prompt // empty' 2>/dev/null)
    if printf '%s' "$prompt" | grep -qiE '(^|[^[:alnum:]])crack[[:space:]]+on([^[:alnum:]]|$)'; then
        mkdir -p "$session_dir" 2>/dev/null || exit 0
        if date -Iseconds >"$flag" 2>/dev/null; then
            hook::log "hook=crack_on_gate event=UserPromptSubmit session=$session_id stamped=1"
        fi
    fi
    exit 0
fi

[[ "$event" == "PreToolUse" ]] || exit 0
tool_name=$(printf '%s' "$HOOK_INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
[[ "$tool_name" == "request_user_input" && -f "$flag" ]] || exit 0
hook::log "hook=crack_on_gate event=PreToolUse session=$session_id tool=request_user_input denied=1"
hook::deny "Crack-on is active for this session. Continue autonomously within the user's scope, or end with a clear report if the work is genuinely blocked."
