#!/bin/bash
# UserPromptSubmit catch-up hook — race-free belt-and-suspenders.
# Fires when user submits a prompt; transcript is fully flushed by then.
# Inspects last assistant text; if discipline missed, injects additionalContext
# so Claude addresses it in the new turn.

LOG_FILE="${CLAUDE_DISCIPLINE_LOG:-$HOME/.claude/discipline.log}"
TAIL_LINES="${CLAUDE_HOOK_TAIL_LINES:-200}"
MIN_LEN="${CLAUDE_HOOK_MIN_LEN:-200}"

. "$(dirname "$0")/lib/discipline_common.sh"

IFS= read -r -d '' -t 5 input || true
transcript=$(echo "$input" | jq -r '.transcript_path // empty')

if [ -z "$transcript" ] || [ ! -f "$transcript" ]; then
  exit 0
fi

last_text=$(dc_extract_last_text "$transcript" "$TAIL_LINES")

if [ -z "$last_text" ] || [ "${#last_text}" -lt "$MIN_LEN" ]; then
  exit 0
fi

file_count=$(jq -s -r '
  [.[]?
   | select(.type == "assistant")
   | .message.content[]?
   | select(.type == "tool_use" and (.name == "Write" or .name == "Edit" or .name == "MultiEdit"))
   | .input.file_path]
  | unique | length
' "$transcript" 2>/dev/null)
[ -z "$file_count" ] && file_count=0

missing=()
if ! echo "$last_text" | grep -qE '\((verified|inferred|guess)'; then
  missing+=("confidence labels (verified/inferred/guess)")
fi
if [ "$file_count" -ge 3 ] && ! echo "$last_text" | grep -qiE '## *did not verify|## *not verified'; then
  missing+=("\"## Did Not Verify\" section (session modified $file_count files)")
fi

if [ "${#missing[@]}" -eq 0 ]; then
  exit 0
fi

# Diagnostic log
session_id=$(echo "$input" | jq -r '.session_id // "?"' 2>/dev/null)
{
  printf '%s hook=catchup session=%s missing="%s"\n' \
    "$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S%z)" \
    "$session_id" "${missing[*]}"
} >> "$LOG_FILE" 2>/dev/null

# Build the catch-up message
msg="[discipline-catchup] Your previous response missed: $(IFS=', '; echo "${missing[*]}")."

jq -n --arg m "$msg" '{
  hookSpecificOutput: {
    hookEventName: "UserPromptSubmit",
    additionalContext: $m
  }
}'
exit 0
