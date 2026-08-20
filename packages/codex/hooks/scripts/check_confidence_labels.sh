#!/usr/bin/env bash
# Stop/SubagentStop: require confidence labels on substantive final messages.

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
# The package root is resolved at runtime.
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib/hook_common.sh"
hook::read_input

active=$(printf '%s' "$HOOK_INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null)
[[ "$active" != "true" ]] || {
    printf '{}\n'
    exit 0
}
message=$(printf '%s' "$HOOK_INPUT" | jq -r '.last_assistant_message // empty' 2>/dev/null)
minimum="${CODERAILS_HOOK_MIN_LEN:-200}"
[[ ${#message} -ge "$minimum" ]] || {
    printf '{}\n'
    exit 0
}
printf '%s' "$message" | grep -qE '\((verified|inferred|guess)([^)]*)?\)' && {
    printf '{}\n'
    exit 0
}

event=$(printf '%s' "$HOOK_INPUT" | jq -r '.hook_event_name // Stop' 2>/dev/null)
session_id=$(printf '%s' "$HOOK_INPUT" | jq -r '.session_id // unknown' 2>/dev/null)
hook::log "hook=confidence_labels event=$event session=$session_id blocked=1 text_len=${#message}"
hook::continue_turn "Your substantive final message has no confidence labels. Add (verified), (inferred), or (guess) to the claims, then finish again."
