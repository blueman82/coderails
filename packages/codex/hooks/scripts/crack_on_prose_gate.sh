#!/usr/bin/env bash
# Stop: while crack-on is active, continue instead of ending on a question.

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
# The package root is resolved at runtime.
# shellcheck disable=SC1091
. "$SCRIPT_DIR/lib/hook_common.sh"
hook::read_input

session_id=$(printf '%s' "$HOOK_INPUT" | jq -r '.session_id // empty' 2>/dev/null)
[[ -n "$session_id" ]] || {
    printf '{}\n'
    exit 0
}
session_dir=$(hook::session_dir "$session_id") || {
    printf '{}\n'
    exit 0
}
[[ -f "$session_dir/crack_on_active" ]] || {
    printf '{}\n'
    exit 0
}

message=$(printf '%s' "$HOOK_INPUT" | jq -r '.last_assistant_message // empty' 2>/dev/null)
[[ -n "$message" ]] || {
    printf '{}\n'
    exit 0
}
# The single-quoted awk program owns $0.
# shellcheck disable=SC2016
prose=$(printf '%s\n' "$message" | awk '
  /^```/ { fenced = !fenced; next }
  !fenced && $0 !~ /^[[:space:]]*>/ { print }
' | sed -E 's/`[^`]*`//g')
body=$(printf '%s\n' "$prose" | awk '/^## Did Not Verify/{exit} {print}')
tail_line=$(printf '%s\n' "$body" | awk 'NF{line=$0} END{print line}')
tail_three=$(printf '%s\n' "$body" | awk 'NF{a[NR]=$0} END{for(i=NR-2;i<=NR;i++) if(i>0 && a[i]!="") print a[i]}')
asks=0
printf '%s' "$tail_line" | grep -qE '\?[[:space:]"'"'"')\]*_]*$' && asks=1
printf '%s\n' "$tail_three" | grep -qiE '^[[:space:]]*(should|shall|can|could|may|might|would)[[:space:]]+(I|we)\b.*\?' && asks=1
printf '%s\n' "$body" | grep -qiE '\b(do you want|would you prefer|which would you|let me know|please choose|awaiting your|need your decision|can you|could you|would you)\b' && asks=1
[[ "$asks" -eq 1 ]] || {
    printf '{}\n'
    exit 0
}

count_file="$session_dir/prose_question_blocks"
active=$(printf '%s' "$HOOK_INPUT" | jq -r '.stop_hook_active // false' 2>/dev/null)
if [[ "$active" != "true" ]]; then
    count=0
else
    count=$(awk 'NR==1 && /^[0-9]+$/{print; found=1} END{if(!found) print 0}' "$count_file" 2>/dev/null)
fi
max_blocks="${CODERAILS_CRACK_ON_PROSE_MAX_BLOCKS:-3}"
if [[ "$count" -ge "$max_blocks" ]]; then
    hook::log "hook=crack_on_prose_gate session=$session_id capped=1 count=$count"
    printf '{}\n'
    exit 0
fi
mkdir -p "$session_dir" 2>/dev/null || {
    printf '{}\n'
    exit 0
}
printf '%s\n' "$((count + 1))" >"$count_file" 2>/dev/null || {
    printf '{}\n'
    exit 0
}
hook::log "hook=crack_on_prose_gate session=$session_id blocked=1 count=$((count + 1))"
hook::continue_turn "Crack-on is active and the final message ends by asking the user. Make the decision yourself within scope and keep working, or finish with a declarative report."
