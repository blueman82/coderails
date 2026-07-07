#!/bin/bash
# Stop hook — voice announcements. When an agentic loop is active, speaks a
# short macOS `say` announcement for the turn's outcome:
#   complete       — LOOP-STOP: complete declared
#   waiting        — LOOP-STOP: approval-gate or awaiting-input declared
#   stall          — active + incomplete, no valid LOOP-STOP declaration
# Silent (zero `say` calls) in every other case, most importantly: no active
# loop at all.
#
# Observes only — never blocks a Stop. Blocking a stalled loop is
# loop_stall_guard.sh's job; this hook always exits 0. `say` is launched
# backgrounded and detached so the hook returns immediately regardless of how
# long speech takes.
#
# Shared loop-detection lives in lib/loop_state_common.sh (same as
# loop_stall_guard.sh, its closest sibling — same Stop payload on stdin, same
# transcript JSONL parsing via extract_last_text(), same declaration regex).
#
# Gates run top to bottom; the first that matches decides.
#   skip  — no transcript                                       → silent
#   skip  — already blocked once this turn (loop-guard)         → silent
#   skip  — no agentic-loop Skill invocation in the transcript  → silent (not a loop)
#   skip  — loop complete, not re-armed, session-owned          → silent (loop done)
#   ANNOUNCE — complete / waiting / stall, per the declaration (or lack of one)
#
# Debounce: an identical announcement kind for the same session within the
# debounce window is suppressed (state under the loop-state dir, never the repo).

. "$(dirname "$0")/lib/loop_state_common.sh"

TAIL_LINES="${CLAUDE_HOOK_TAIL_LINES:-300}"
DEBOUNCE_SECONDS="${CLAUDE_VOICE_DEBOUNCE_SECONDS:-60}"

IFS= read -r -d '' -t 5 input || true
# If jq is absent, this extraction silently yields empty, transcript stays "",
# and als_gate_no_transcript below allows (silently) — fail-open, same posture
# as loop_stall_guard.sh.
transcript=$(echo "$input" | jq -r '.transcript_path // empty')
session_id=$(als_sanitise_session_id "$(echo "$input" | jq -r '.session_id // "?"' 2>/dev/null)")
cwd=$(echo "$input" | jq -r '.cwd // empty' 2>/dev/null)
stop_hook_active=$(echo "$input" | jq -r '.stop_hook_active // false' 2>/dev/null)

extract_last_text() {
  tail -n "$TAIL_LINES" "$transcript" 2>/dev/null | jq -s -r '
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

# Speak a phrase backgrounded and fully detached so the hook returns well
# under 1 second regardless of how long `say` takes. stdin/stdout/stderr are
# all redirected so no pipe back to the hook's parent can block it.
speak() {
  command -v say >/dev/null 2>&1 || return 0
  say "$1" </dev/null >/dev/null 2>&1 &
  disown 2>/dev/null || true
}

# Debounce: suppress an immediate repeat of the SAME announcement kind for
# this session within DEBOUNCE_SECONDS. State lives alongside progress.json
# in the session's loop-state dir (resolved via als_resolve_path), never the
# repo. Fail-open: any error reading/writing the marker just re-announces.
debounce_allows() { # kind -> 0 (announce) or 1 (suppressed)
  local kind="$1" dir marker now last
  [ -n "$ALS_PATH" ] || return 0
  dir=$(dirname "$ALS_PATH")
  marker="$dir/voice_announce_${kind}.last"
  now=$(date +%s 2>/dev/null || echo 0)
  if [ -f "$marker" ]; then
    last=$(cat "$marker" 2>/dev/null)
    case "$last" in (''|*[!0-9]*) last=0;; esac
    if [ $((now - last)) -lt "$DEBOUNCE_SECONDS" ]; then
      return 1
    fi
  fi
  mkdir -p "$dir" 2>/dev/null
  printf '%s' "$now" > "$marker" 2>/dev/null
  return 0
}

announce() { # kind phrase
  local kind="$1" phrase="$2"
  if debounce_allows "$kind"; then
    als_log "hook=voice_announce session=$session_id kind=$kind announced=1"
    speak "$phrase"
  else
    als_log "hook=voice_announce session=$session_id kind=$kind announced=0 reason=debounced"
  fi
}

gate_announce_by_declaration() {
  prev_len=-1; attempts=0; text=""
  while [ "$attempts" -lt "$MAX_ATTEMPTS" ]; do
    text=$(extract_last_text); cur_len=${#text}
    if [ "$cur_len" -eq "$prev_len" ] && [ "$cur_len" -gt 0 ]; then break; fi
    prev_len=$cur_len
    attempts=$((attempts + 1))
    [ "$attempts" -lt "$MAX_ATTEMPTS" ] && sleep "$SLEEP_S"
  done
  if printf '%s\n' "$text" | grep -qiE "^[[:space:]]*LOOP-STOP:[[:space:]]*(${LOOP_STOP_VOCAB})([^[:alnum:]]|$)"; then
    category=$(printf '%s\n' "$text" | grep -oiE "LOOP-STOP:[[:space:]]*(${LOOP_STOP_VOCAB})" | grep -oiE "(${LOOP_STOP_VOCAB})\$" | tail -1)
    case "$category" in
      complete)
        announce complete "Loop complete."
        ;;
      approval-gate|awaiting-input)
        announce waiting "Loop is waiting on you."
        ;;
    esac
    exit 0
  fi
  announce stall "Loop may have stalled."
  exit 0
}

als_gate_no_transcript "$transcript"
als_gate_stop_loop "$stop_hook_active"
als_gate_require_active_loop "$transcript" "voice_announce" "$session_id"
als_load_progress "$cwd" "$session_id"
als_gate_loop_complete "voice_announce" "$session_id"
gate_announce_by_declaration
