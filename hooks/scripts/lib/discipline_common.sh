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
#
#   Two-layer defense against a bad line reaching stage 2 (mirrors
#   ulg_count_dispatch_turns in unregistered_loop_guard.sh):
#   Layer 1 (recovery, primary) — `select(type == "object")` on line 39 stops a
#   top-level SCALAR aborting the slurp, but it is necessary, not sufficient: a
#   valid JSON OBJECT of the wrong INNER shape still aborts it — `.message` a
#   bare string/array (indexing `.content` on it errors), or a non-object
#   content element (indexing `.type` on it errors). Both `is_genuine_user` and
#   the tool_use scan now guard `.message`/element shape inline so the slurp
#   completes and recovers the count from the surviving lines, instead of the
#   whole aggregation aborting on one wrong-shaped line.
#   Layer 2 (net, not primary) — stage 2 is split into a captured intermediate
#   ($tolerant) and its own command substitution so `agg_rc=$?` can be read.
#   This is trigger-independent: it catches wrong-shape hazards nobody has
#   enumerated yet, which chasing one guard per shape does not. With Layer 1 in
#   place this should not fire on the known hazards above — it exists for the
#   unknown ones. On an actual Layer-2 abort (agg_rc != 0), attribute via
#   stderr (matching ulg's `echo ... >&2`) and fail open to 0. No reason
#   global: dc_file_count has exactly one direct caller
#   (check_verify_loop.sh) and nothing today reads a reason for it.
dc_file_count() {
  local transcript="$1" tolerant n agg_rc
  tolerant=$(jq -R 'fromjson? // empty' "$transcript" 2>/dev/null)
  n=0
  agg_rc=0
  if [ -n "$tolerant" ]; then
    n=$(printf '%s' "$tolerant" | jq -s -r '
      def is_genuine_user:
        .type == "user" and
        ((.message | type) == "object") and
        ( .message.content
          | if type == "string" then (length > 0)
            elif type == "array" then ( any(.[]?; (type == "object") and .type == "text") )
            else false end
        );
      map(select(type == "object")) as $lines
      | ($lines | to_entries | map(select(.value | is_genuine_user)) | last.key // -1) as $cutoff
      | [ $lines[($cutoff+1):][]?
          | select(.type=="assistant")
          | select((.message | type) == "object")
          | .message.content[]?
          | select(type == "object")
          | select(.type=="tool_use" and (.name=="Write" or .name=="Edit" or .name=="MultiEdit"))
          | .input.file_path
        ] | unique | length
    ' 2>/dev/null)
    agg_rc=$?
  fi
  if [ "${agg_rc:-0}" -ne 0 ] && [ -n "$tolerant" ]; then
    echo "jq_parse_error" >&2
    printf '0'
    return
  fi
  case "$n" in (''|*[!0-9]*) n=0;; esac
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
#   function does not log on a benign per-line skip — a malformed-line skip
#   here is silent by design, matching its prior contract of never
#   distinguishing "malformed" from "no text yet". It DOES log (stderr only,
#   see below) on the rarer total-abort case where stage 2 itself errors out.
#
#   Two-layer defense, mirrors dc_file_count above (see its comment for the
#   full rationale) and ulg_count_dispatch_turns in unregistered_loop_guard.sh:
#   Layer 1 (recovery, primary) — `select(type == "object")` stops a top-level
#   SCALAR aborting the slurp, but a valid object with a wrong-shaped `.message`
#   (a bare string/array) still aborts on `.message.content`; guarding
#   `.message`'s type inline lets the slurp complete and recover the last valid
#   text from surviving lines.
#   Layer 2 (net) — stage 2 is split into a captured intermediate ($tolerant)
#   so its exit code ($?) can be read as a trigger-independent net for
#   unenumerated shape hazards. On an actual abort, attribute via stderr only
#   (no reason global — see dc_file_count's comment) and fail open to empty.
dc_extract_last_text() {
  local transcript="$1" tail_lines="$2" tolerant text agg_rc
  # `fromjson? // empty` keeps every line that parses as JSON — including lines
  # that are valid JSON SCALARS (a bare string or number), not just objects.
  # Indexing a scalar with .type makes jq error out ("Cannot index string with
  # string \"type\""), and because stderr is discarded below that error is
  # silent: the whole extraction returns empty and the caller sees "no text"
  # rather than a failure. So filter to objects first. Same guard, same reason,
  # as als_extract_last_text in loop_state_common.sh (added by PR #208).
  tolerant=$(tail -n "$tail_lines" "$transcript" 2>/dev/null | jq -R 'fromjson? // empty' 2>/dev/null)
  text=""
  agg_rc=0
  if [ -n "$tolerant" ]; then
    text=$(printf '%s' "$tolerant" | jq -s -r '
      [.[]?
       | select(type == "object")
       | select(.type == "assistant")
       | select((.message | type) == "object")
       | (.message.content
          | if type == "array" then [ .[]? | select(type == "object") | select(.type == "text") | .text ] | join(" ")
            elif type == "string" then .
            else "" end)
       | select(type == "string" and length > 0)]
      | last // ""
    ' 2>/dev/null)
    agg_rc=$?
  fi
  if [ "${agg_rc:-0}" -ne 0 ] && [ -n "$tolerant" ]; then
    echo "jq_parse_error" >&2
    printf ''
    return
  fi
  printf '%s' "$text"
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
