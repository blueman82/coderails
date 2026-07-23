#!/bin/bash
# discipline_common.sh — shared transcript-extraction utilities for discipline hooks.
# SOURCED (not executed) by check_confidence_labels.sh and check_verify_loop.sh.
# Mirrors the lib/loop_state_common.sh pattern.
#
# Canonical form chosen from check_verify_loop.sh (the more defensive variant):
#   - handles array content (join text blocks), string content (pass through),
#     and any other type (emit empty) so a non-text entry can never beat a real
#     text block when `last` runs.

# dc_file_count <transcript-path>
#   Returns the count of unique Write/Edit/MultiEdit target files in a JSONL
#   transcript, scoped to the CURRENT TURN — records after the last genuine
#   user prompt (a "user" record whose message.content is a non-empty string,
#   or an array containing a text block; a tool_result-only array does NOT
#   count as genuine). If no genuine user record exists, counts the whole
#   transcript (test fixtures and edge-case transcripts that never had one).
#   Returns 0 if the transcript is absent, unreadable, or contains no such
#   tool uses in scope.
#   Per-line tolerant parse (same style as dc_extract_last_text): a single
#   malformed/truncated line must not zero the count for the rest of the
#   transcript — stage 1 drops just the bad line, stage 2 aggregates over
#   what's left.
dc_file_count() {
  local transcript="$1" n
  # Objects only, for the same reason as dc_extract_last_text below: stage 1
  # keeps any line that parses as JSON, including bare scalars, and indexing a
  # scalar with .type makes jq error out. With stderr discarded that error is
  # silent and the count comes back 0 — a single stray scalar line would zero
  # the whole transcript's file count.
  n=$(jq -R 'fromjson? // empty' "$transcript" 2>/dev/null | jq -s -r '
    def is_genuine_user:
      .type == "user" and
      ( .message.content
        | if type == "string" then (length > 0)
          elif type == "array" then ( any(.[]?; .type == "text") )
          else false end
      );
    map(select(type == "object")) as $lines
    | ($lines | to_entries | map(select(.value | is_genuine_user)) | last.key // -1) as $cutoff
    | [ $lines[($cutoff+1):][]?
        | select(.type=="assistant")
        | .message.content[]?
        | select(.type=="tool_use" and (.name=="Write" or .name=="Edit" or .name=="MultiEdit"))
        | .input.file_path
      ] | unique | length
  ' 2>/dev/null)
  [ -z "$n" ] && n=0
  printf '%s' "$n"
}

# dc_extract_last_text <transcript> <tail_lines>
#   Extracts the last assistant text block from a JSONL transcript.
#   Returns the joined text of the last assistant message that has any text content.
#   Prints empty string if no such message exists (absent/unreadable transcript,
#   no text blocks, or every line in the tail window malformed).
#   Per-line tolerant parse: a single malformed line in the tail window must
#   not collapse extraction of a genuine final message to empty — stage 1
#   drops just the bad line, stage 2 aggregates over what's left. This
#   function does not log — a malformed-line skip here is silent by design,
#   matching its prior contract of never distinguishing "malformed" from
#   "no text yet".
dc_extract_last_text() {
  local transcript="$1" tail_lines="$2"
  # `fromjson? // empty` keeps every line that parses as JSON — including lines
  # that are valid JSON SCALARS (a bare string or number), not just objects.
  # Indexing a scalar with .type makes jq error out ("Cannot index string with
  # string \"type\""), and because stderr is discarded below that error is
  # silent: the whole extraction returns empty and the caller sees "no text"
  # rather than a failure. So filter to objects first. Same guard, same reason,
  # as als_extract_last_text in loop_state_common.sh (added by PR #208).
  tail -n "$tail_lines" "$transcript" 2>/dev/null | jq -R 'fromjson? // empty' 2>/dev/null | jq -s -r '
    [.[]?
     | select(type == "object")
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

# dc_mine_hook_blocks <session_id> [log_file]
#   Aggregates this session's discipline-log lines per hook. Stdout: compact
#   JSON {"<hook>":{"events":N,"flagged":M}}. Lines are hook-authored
#   (key=value format, als_log convention) - a hook-authored field; the
#   orchestrator cannot have written these log lines itself. Fail-open to {}
#   on any read problem: the retro must still be writable when the log is absent.
dc_mine_hook_blocks() {
  local session="$1" log="${2:-${CLAUDE_DISCIPLINE_LOG:-$HOME/.claude/discipline.log}}"
  { [ -n "$session" ] && [ -r "$log" ]; } || { printf '{}'; return 0; }
  awk -v sid="$session" '
    {
      hook=""; flagged=0; sess=0
      for (i=1; i<=NF; i++) {
        if ($i == "session=" sid) sess=1
        if ($i ~ /^hook=/) hook=substr($i,6)
        if ($i=="blocked=1" || $i=="would_block=1" || $i=="nudged=1") flagged=1
      }
      if (sess && hook != "") { ev[hook]++; if (flagged) fl[hook]++ }
    }
    END { for (h in ev) printf "%s %d %d\n", h, ev[h], fl[h]+0 }
  ' "$log" 2>/dev/null \
  | jq -Rnc '[inputs | split(" ") | {(.[0]): {events:(.[1]|tonumber), flagged:(.[2]|tonumber)}}] | add // {}' 2>/dev/null \
  || printf '{}'
}
