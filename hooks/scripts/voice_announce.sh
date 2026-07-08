#!/bin/bash
# Stop hook — voice announcements. When an agentic loop is active, speaks a
# short macOS `say` announcement for the turn's outcome:
#   complete       — LOOP-STOP: complete declared
#   waiting        — LOOP-STOP: approval-gate or awaiting-input declared
#   stopped        — LOOP-STOP: hard-stop declared
#   stall          — active + incomplete, text extracted but no valid
#                    LOOP-STOP declaration in it
# Silent (zero `say` calls) in every other case, most importantly: no active
# loop at all, or text extraction itself came back empty (nothing to read yet
# — NOT the same as "read it and found no declaration").
#
# Observes only — never blocks a Stop. Blocking a stalled loop is
# loop_stall_guard.sh's job; this hook always exits 0. `say` is launched
# backgrounded and detached so the hook returns immediately regardless of how
# long speech takes.
#
# ORDERING CONSTRAINT: must run BEFORE the blocking Stop hooks in hooks.json
# (check_confidence_labels/check_verify_loop/loop_state_guard/loop_stall_guard/
# unregistered_loop_guard). This hook is observe-only and always exits 0, so
# placing it first cannot affect any other hook's decision; placing it after a
# hook that can exit 2 risks the runner short-circuiting before this one runs,
# under either parallel or sequential Stop-hook execution semantics.
#
# Shared loop-detection AND stable-text extraction live in
# lib/loop_state_common.sh (als_stable_last_text), shared with
# loop_stall_guard.sh — same Stop payload on stdin, same declaration regex.
#
# Gates run top to bottom; the first that matches decides.
#   skip  — no transcript                                       → silent
#   skip  — already blocked once this turn (loop-guard)         → silent
#   skip  — no agentic-loop Skill invocation in the transcript  → silent (not a loop)
#   skip  — loop complete, not re-armed, session-owned          → silent (loop done)
#   skip  — stable text extraction came back empty              → silent (reason=extract_failed)
#   ANNOUNCE — complete / waiting / stopped / stall, per the declaration
#
# Debounce: an identical announcement kind for the same session within the
# debounce window is suppressed (state under the loop-state dir, never the
# repo). A marker-write failure fails open TOWARD SPEAKING (never silently
# drops the announcement) — audible spam beats a silently dead feature — but
# logs a distinct reason so the degradation is visible.

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

# Speak a phrase backgrounded and fully detached so the hook returns well
# under 1 second regardless of how long `say` takes. stdin/stdout/stderr are
# all redirected so no pipe back to the hook's parent can block it. Returns 1
# (before logging or speaking) when `say` isn't on PATH, so the caller can log
# a distinct reason instead of a false announced=1.
speak() {
  command -v say >/dev/null 2>&1 || return 1
  say "$1" </dev/null >/dev/null 2>&1 &
  disown 2>/dev/null || true
  return 0
}

# Debounce: suppress an immediate repeat of the SAME announcement kind for
# this session within DEBOUNCE_SECONDS. State lives alongside progress.json
# in the session's loop-state dir (resolved via als_resolve_path), never the
# repo. Sets ALS_DEBOUNCE_WRITE_FAILED=1 when the marker write itself failed
# (e.g. unwritable state dir) — the caller still announces (fail-open to
# speak) but logs this distinctly rather than claiming a clean debounce state.
debounce_allows() { # kind -> 0 (announce) or 1 (suppressed)
  local kind="$1" dir marker now last
  ALS_DEBOUNCE_WRITE_FAILED=0
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
  if ! printf '%s' "$now" > "$marker" 2>/dev/null; then
    ALS_DEBOUNCE_WRITE_FAILED=1
  fi
  return 0
}

announce() { # kind phrase
  local kind="$1" phrase="$2"
  if debounce_allows "$kind"; then
    if [ "$ALS_DEBOUNCE_WRITE_FAILED" = "1" ]; then
      als_log "hook=voice_announce session=$session_id kind=$kind announced=1 reason=debounce_write_failed"
    else
      als_log "hook=voice_announce session=$session_id kind=$kind announced=1"
    fi
    speak "$phrase" || als_log "hook=voice_announce session=$session_id kind=$kind announced=0 reason=no_say_binary"
  else
    als_log "hook=voice_announce session=$session_id kind=$kind announced=0 reason=debounced"
  fi
}

gate_announce_by_declaration() {
  text=$(als_stable_last_text "$transcript" "$TAIL_LINES" "$MAX_ATTEMPTS" "$SLEEP_S")
  if [ -z "$text" ]; then
    # Extraction found nothing to read — NOT evidence of a stall. Could be a
    # transcript-flush race that never lands within the retry budget, every
    # line in the tail window malformed, or a turn with no text content at
    # all. Silent, with a distinct log reason (never misreported as a stall).
    als_log "hook=voice_announce session=$session_id reason=extract_failed"
    exit 0
  fi
  if printf '%s\n' "$text" | grep -qiE "^[[:space:]]*LOOP-STOP:[[:space:]]*(${LOOP_STOP_VOCAB})([^[:alnum:]]|$)"; then
    category=$(printf '%s\n' "$text" | grep -oiE "LOOP-STOP:[[:space:]]*(${LOOP_STOP_VOCAB})" | grep -oiE "(${LOOP_STOP_VOCAB})\$" | tail -1)
    case "$category" in
      complete)
        announce complete "Loop complete."
        ;;
      approval-gate|awaiting-input)
        announce waiting "Loop is waiting on you."
        ;;
      hard-stop)
        announce stopped "Loop has hit a hard stop."
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
