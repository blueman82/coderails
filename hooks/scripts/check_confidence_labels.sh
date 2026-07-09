#!/bin/bash
# Tail-first read + retry-backoff race mitigation + diagnostic logging.
# BLOCK-MODE: exits 2 when confidence labels are missing (promoted from warn-mode 2026-05-05).

LOG_FILE="${CLAUDE_DISCIPLINE_LOG:-$HOME/.claude/discipline.log}"
TAIL_LINES="${CLAUDE_HOOK_TAIL_LINES:-200}"
MAX_ATTEMPTS="${CLAUDE_HOOK_MAX_ATTEMPTS:-5}"
SLEEP_S="${CLAUDE_HOOK_SLEEP_S:-0.3}"
MIN_LEN="${CLAUDE_HOOK_MIN_LEN:-200}"

. "$(dirname "$0")/lib/discipline_common.sh"

IFS= read -r -d '' -t 5 input || true
hook_event=$(echo "$input" | jq -r '.hook_event_name // "Stop"' 2>/dev/null)

# Loop-guard: if we already blocked once this turn, allow the stop to avoid looping.
# Mirrors check_verify_loop.sh's guard — without it, a stale/degenerate transcript
# read can re-block every subsequent Stop attempt in the same turn indefinitely.
stop_hook_active=$(echo "$input" | jq -r '.stop_hook_active // false' 2>/dev/null)
if [ "$stop_hook_active" = "true" ]; then
  exit 0
fi

# SubagentStop: the subagent's final text is available directly in last_assistant_message.
# Prefer it over transcript parsing — it avoids the flush race and reads the right
# message. (transcript_path on a SubagentStop payload is the PARENT session transcript,
# not the subagent's — reading it would check the wrong content.)
if [ "$hook_event" = "SubagentStop" ]; then
  text=$(echo "$input" | jq -r '.last_assistant_message // ""' 2>/dev/null)
  attempts=1
else
  transcript=$(echo "$input" | jq -r '.transcript_path // empty')
  if [ -z "$transcript" ] || [ ! -f "$transcript" ]; then
    exit 0
  fi
  text=$(dc_stable_text "$transcript" "$TAIL_LINES" "$MAX_ATTEMPTS" "$SLEEP_S")
  attempts=$DC_LAST_ATTEMPTS
fi

session_id=$(echo "$input" | jq -r '.session_id // "?"' 2>/dev/null)
matched_label=0
if echo "$text" | grep -qE '\((verified|inferred|guess)'; then matched_label=1; fi
would_block=0
if [ "${#text}" -ge "$MIN_LEN" ] && [ "$matched_label" -eq 0 ]; then would_block=1; fi
{
  printf '%s hook=confidence_labels session=%s text_len=%d attempts=%d matched=%d would_block=%d\n' \
    "$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S%z)" \
    "$session_id" "${#text}" "$attempts" "$matched_label" "$would_block"
} >> "$LOG_FILE" 2>/dev/null

if [ "${#text}" -lt "$MIN_LEN" ]; then
  exit 0
fi
if [ "$matched_label" -eq 1 ]; then
  exit 0
fi

{
  printf '%s hook=confidence_labels session=%s text_len=%d blocked=1\n' \
    "$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S%z)" \
    "$session_id" "${#text}"
} >> "$LOG_FILE" 2>/dev/null
echo "[discipline-block] response made substantive claims without (verified)/(inferred)/(guess) labels. Add them before stopping." >&2
exit 2
