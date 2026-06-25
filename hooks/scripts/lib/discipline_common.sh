#!/bin/bash
# discipline_common.sh — shared transcript-extraction utilities for discipline hooks.
# SOURCED (not executed) by check_confidence_labels.sh, check_verify_loop.sh, and
# discipline_catchup.sh. Mirrors the lib/loop_state_common.sh pattern.
#
# Canonical form chosen from check_verify_loop.sh (the more defensive variant):
#   - handles array content (join text blocks), string content (pass through),
#     and any other type (emit empty) so a non-text entry can never beat a real
#     text block when `last` runs.

# dc_extract_last_text <transcript> <tail_lines>
#   Extracts the last assistant text block from a JSONL transcript.
#   Returns the joined text of the last assistant message that has any text content.
#   Prints empty string if no such message exists.
dc_extract_last_text() {
  local transcript="$1" tail_lines="$2"
  tail -n "$tail_lines" "$transcript" 2>/dev/null | jq -s -r '
    [.[]?
     | select(.type == "assistant")
     | (.message.content
        | if type == "array" then [ .[]? | select(.type == "text") | .text ] | join(" ")
          elif type == "string" then .
          else "" end)
     | select(type == "string" and length > 0)]
    | last // ""
  ' 2>/dev/null
}

# dc_stable_text <transcript> <tail_lines> <max_attempts> <sleep_s>
#   Calls dc_extract_last_text in a retry loop until the length stabilises
#   (two consecutive calls return the same non-zero length) or max_attempts is hit.
#   Prints the stabilised text. Mirrors the retry loop in check_confidence_labels.sh
#   and check_verify_loop.sh exactly.
#   Sets DC_LAST_ATTEMPTS to the number of iterations consumed (for diagnostic logs).
DC_LAST_ATTEMPTS=0
dc_stable_text() {
  local transcript="$1" tail_lines="$2" max_attempts="$3" sleep_s="$4"
  local prev_len=-1 attempts=0 text="" cur_len
  while [ "$attempts" -lt "$max_attempts" ]; do
    text=$(dc_extract_last_text "$transcript" "$tail_lines")
    cur_len=${#text}
    if [ "$cur_len" -eq "$prev_len" ] && [ "$cur_len" -gt 0 ]; then
      break
    fi
    prev_len=$cur_len
    attempts=$((attempts + 1))
    [ "$attempts" -lt "$max_attempts" ] && sleep "$sleep_s"
  done
  DC_LAST_ATTEMPTS=$attempts
  printf '%s' "$text"
}
