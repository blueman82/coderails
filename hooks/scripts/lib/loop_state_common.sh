#!/bin/bash
# loop_state_common.sh — shared detection for the agentic-loop Stop guards.
# SOURCED (not executed) by loop_state_guard.sh (presence/ownership) and
# loop_stall_guard.sh (anti-stall). Single source for: env defaults, the
# discipline-log helper, the LOOP-STOP vocabulary, and the active-loop /
# progress.json state resolution — so the two guards can never drift on what
# "an active loop" means.

# Single source of truth for the LOOP-STOP category vocabulary. The anti-stall guard
# builds BOTH its match regex and its block message from this, so they can't disagree.
LOOP_STOP_VOCAB="hard-stop|approval-gate|awaiting-input|complete"

LOG_FILE="${CLAUDE_DISCIPLINE_LOG:-$HOME/.claude/discipline.log}"
MAX_ATTEMPTS="${CLAUDE_HOOK_MAX_ATTEMPTS:-5}"
SLEEP_S="${CLAUDE_HOOK_SLEEP_S:-0.3}"

# Append a single key=value line to the discipline log (best-effort). Brace-group
# wraps the printf/redirect so the group's OWN 2>/dev/null also catches the
# redirection-open error itself (a trailing 2>/dev/null on printf alone does not
# suppress that error) — no dir auto-creation, stays side-effect-free.
# Accepted tradeoff: if LOG_FILE's parent directory is missing, a caller's own
# failure-reporting line (e.g. als_stable_invocations' jq-failure summary) is
# itself silently swallowed here — only reachable via a misconfigured
# CLAUDE_DISCIPLINE_LOG override, not a normal operating condition.
als_log() { { printf '%s %s\n' "$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S%z)" "$1" >> "$LOG_FILE"; } 2>/dev/null; }

# Sanitise a session_id extracted from the Stop-hook JSON payload. If the
# payload's session_id is missing/null, the jq extraction below falls back to
# the literal "?" — a FIXED sentinel that would make every malformed-payload
# session collide onto the identical progress.json path, silently defeating
# session-scoped isolation. Same fallback style as agentic_loop_path.sh's own
# default: generate a fresh unique value (PID + high-res timestamp) instead of
# a shared constant, so two concurrent malformed-payload sessions can't collide.
als_sanitise_session_id() {
  local raw="$1"
  if [ -z "$raw" ] || [ "$raw" = "?" ]; then
    printf 'unknown-%s-%s' "$$" "$(date +%s%N 2>/dev/null || date +%s)"
  else
    # session_id is harness-owned (Stop payload / env), not attacker-controlled
    # — defence-in-depth against payload anomalies, not a security boundary.
    # REPLACE (not fresh-fallback): a malformed id must not silently orphan its
    # real session, so strip "/" and collapse ".." in place rather than
    # discarding the id and generating an unrelated fresh one.
    # ACCEPTED TRADEOFF: lossy transform — "foo/bar" and "foo_bar" both
    # sanitise to "foo_bar", so two distinct raw ids can collide. Accepted
    # given session_id is harness-owned, rather than adding a re-uniquifying
    # suffix that would make the sanitised form unpredictable across calls.
    # Keep in lockstep with the duplicate copy in agentic_loop_path.sh (kept
    # dependency-free by design, so this transform is intentionally
    # duplicated there rather than sourcing this file) — update both on any change.
    raw=$(printf '%s' "$raw" | tr '/' '_')
    raw=$(printf '%s' "$raw" | sed 's/\.\.//g')
    printf '%s' "$raw"
  fi
}

# Count agentic-loop Skill invocations across the WHOLE transcript (one-shot).
# Structured jq match on a tool_use — never a text grep. Matches the scoped
# ("coderails:agentic-loop") and bare ("agentic-loop") skill names.
# Stdout contract is UNCHANGED (empty or an integer) even on jq failure — every
# consumer still reads that as "0, allow" (fail-open). On jq failure this ALSO
# writes a distinguishable reason tag ("jq_missing" / "jq_parse_error") to
# STDERR (never stdout, so the count contract stays untouched) — mirroring
# unregistered_loop_guard.sh's ULG_PARSE_REASON global, but a global can't be
# used here: als_stable_invocations (the sole retrying caller) invokes this via
# `n=$(als_count_invocations ...)` command substitution, which runs in a
# subshell — any global the function set would vanish with the subshell and
# never reach the caller. Stderr survives that boundary. This function does
# NOT log directly: als_stable_invocations decides whether/how to log, since a
# single call here may be one of several retry attempts, and per-attempt
# logging is exactly the ambiguous double-log / lost-recovery bug this exists
# to avoid. One-shot callers (e.g. unregistered_loop_guard.sh's
# ulg_has_skill_invocation) that call this directly, not through the retry
# wrapper, simply never read stderr — no logging fires for them, matching
# their prior (pre-hardening) behavior of being silent on a parse failure.
als_count_invocations() {
  command -v jq >/dev/null 2>&1 || { echo "jq_missing" >&2; return; }
  jq -s -r '
    [ .[]?
      | select(.type == "assistant")
      | .message.content[]?
      | select(.type == "tool_use" and .name == "Skill")
      | (.input.skill // "")
      | select(test("(^|:)agentic-loop$")) ]
    | length
  ' "$1" 2>/dev/null || echo "jq_parse_error" >&2
}

# Stable invocation count: retry for the transcript-flush race until it settles.
# Logs EXACTLY ONE summary line via als_log when any attempt hit a jq failure —
# never one line per attempt (that was the ambiguous-recovery / double-log bug:
# a transient failure that recovered on retry was indistinguishable from one
# that never recovered, and a sustained failure logged once per attempt with no
# final verdict). outcome=recovered means the LAST attempt succeeded (no reason
# tag on that attempt); outcome=exhausted means it didn't. attempts=N is the
# number of jq calls made. Zero lines when every attempt was clean. Gate
# outcomes (stdout contract, fail-open) are unchanged — this only affects what
# gets logged.
als_stable_invocations() {
  local transcript="$1" prev=-1 attempts=0 n=0 last_reason="" seen_reason=""
  local err_file; err_file=$(mktemp 2>/dev/null) || err_file=""
  while [ "$attempts" -lt "$MAX_ATTEMPTS" ]; do
    # Single call per attempt: stdout (the count) captured normally, stderr
    # (the reason tag, if any) redirected to a scratch file and read back —
    # avoids calling the function twice per attempt, which would re-read the
    # transcript twice and could observe two different states across the very
    # flush-race window this retry loop exists to ride out.
    if [ -n "$err_file" ]; then
      n=$(als_count_invocations "$transcript" 2>"$err_file")
      last_reason=$(cat "$err_file" 2>/dev/null)
    else
      n=$(als_count_invocations "$transcript" 2>/dev/null)
      last_reason=""
    fi
    [ -z "$n" ] && n=0
    attempts=$((attempts + 1))
    if [ "$n" -eq "$prev" ] && [ -z "$last_reason" ]; then break; fi
    prev=$n
    [ -n "$last_reason" ] && seen_reason="$last_reason"
    [ "$attempts" -lt "$MAX_ATTEMPTS" ] && sleep "$SLEEP_S"
  done
  [ -n "$err_file" ] && rm -f "$err_file" 2>/dev/null
  if [ -n "$seen_reason" ]; then
    local outcome="exhausted"
    [ -z "$last_reason" ] && outcome="recovered"
    als_log "hook=als_count_invocations reason=$seen_reason attempts=$attempts outcome=$outcome"
  fi
  printf '%s' "$n"
}

# als_extract_last_text <transcript> <tail_lines>
#   Extracts the last assistant text block from a JSONL transcript. Returns the
#   joined text of the last assistant message that has any text content, or an
#   empty string if none exists (absent/unreadable transcript, no text blocks,
#   or a malformed line jq -s can't parse). Mirrors discipline_common.sh's
#   dc_extract_last_text exactly (same canonical extraction shape); duplicated
#   rather than shared across the two libs since loop_state_common.sh and
#   discipline_common.sh are deliberately independent (different hook families).
als_extract_last_text() {
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

# als_stable_last_text <transcript> <tail_lines> <max_attempts> <sleep_s>
#   Calls als_extract_last_text in a retry loop until the length stabilises
#   (two consecutive calls return the same non-zero length) or max_attempts is
#   hit — rides out the transcript-flush race. Prints the stabilised text
#   (possibly empty, e.g. a malformed transcript line jq -s can't parse across
#   every attempt). Sets ALS_LAST_ATTEMPTS to the iteration count consumed.
#   Mirrors discipline_common.sh's dc_stable_text; callers must inspect the
#   RETURNED TEXT for emptiness themselves — this function does not treat
#   empty-after-exhausting-retries as an error, only as "no text found."
ALS_LAST_ATTEMPTS=0
als_stable_last_text() {
  local transcript="$1" tail_lines="$2" max_attempts="$3" sleep_s="$4"
  local prev_len=-1 attempts=0 text="" cur_len
  while [ "$attempts" -lt "$max_attempts" ]; do
    text=$(als_extract_last_text "$transcript" "$tail_lines")
    cur_len=${#text}
    if [ "$cur_len" -eq "$prev_len" ] && [ "$cur_len" -gt 0 ]; then
      break
    fi
    prev_len=$cur_len
    attempts=$((attempts + 1))
    [ "$attempts" -lt "$max_attempts" ] && sleep "$sleep_s"
  done
  ALS_LAST_ATTEMPTS=$attempts
  printf '%s' "$text"
}

# Resolve the progress.json path via the sole path authority (sibling script).
als_resolve_path() { bash "$(dirname "${BASH_SOURCE[0]}")/agentic_loop_path.sh" "$1" "$2" 2>/dev/null; }

# Read progress.json state into globals ALS_STATUS / ALS_SESSION / ALS_MARKER.
# ALS_MARKER is sanitised to a non-negative integer (empty/non-numeric -> 0).
als_read_file_state() {
  ALS_STATUS=""; ALS_SESSION=""; ALS_MARKER=0
  if [ -n "$1" ] && [ -f "$1" ]; then
    ALS_STATUS=$(jq -r '.status // ""' "$1" 2>/dev/null)
    ALS_SESSION=$(jq -r '.session_id // ""' "$1" 2>/dev/null)
    ALS_MARKER=$(jq -r '.completed_marker // 0' "$1" 2>/dev/null)
    case "$ALS_MARKER" in (''|*[!0-9]*) ALS_MARKER=0;; esac
  fi
}

# ── Shared gate functions (called by both loop guards) ───────────────────────
# Guard scripts do NOT use set -euo pipefail; gate functions exit directly to
# skip or block, exactly like require::* helpers in scripts/lib/git-common.sh.

# Gate: skip if no transcript file to inspect.
als_gate_no_transcript() {
  local transcript="$1"
  if [ -z "$transcript" ] || [ ! -f "$transcript" ]; then
    exit 0
  fi
}

# Gate: skip if already blocked this turn to avoid a stop-loop.
als_gate_stop_loop() {
  local stop_hook_active="$1"
  if [ "$stop_hook_active" = "true" ]; then
    exit 0
  fi
}

# Gate: skip if no agentic-loop Skill invocation found — not a loop.
# Sets global ALS_INVOCATIONS. Logs and exits when invocations = 0.
# Takes hook name as arg so the log line carries the correct hook= tag.
als_gate_require_active_loop() {
  local transcript="$1" hook="$2" session="$3"
  ALS_INVOCATIONS=$(als_stable_invocations "$transcript"); [ -z "$ALS_INVOCATIONS" ] && ALS_INVOCATIONS=0
  if [ "$ALS_INVOCATIONS" -eq 0 ]; then
    als_log "hook=$hook session=$session invocations=0 active=0 blocked=0"
    exit 0
  fi
}

# Setup: resolve progress.json path and read its state into globals.
# Sets ALS_PATH, ALS_STATUS, ALS_SESSION, ALS_MARKER, ALS_REARMED.
# Requires ALS_INVOCATIONS to be set (by als_gate_require_active_loop).
als_load_progress() {
  local cwd="$1" session="$2"
  ALS_PATH=$(als_resolve_path "$cwd" "$session")
  als_read_file_state "$ALS_PATH"
  ALS_REARMED=0
  if [ "$ALS_INVOCATIONS" -gt "$ALS_MARKER" ]; then ALS_REARMED=1; fi
}

# Gate: skip when the loop is genuinely complete — complete, not re-armed, and
# session-owned (the shared off-switch). Logs and exits 0.
# Takes hook name as arg so the log line carries the correct hook= tag.
als_gate_loop_complete() {
  local hook="$1" session="$2"
  if [ "$ALS_STATUS" = "complete" ] && [ "$ALS_REARMED" -eq 0 ] && [ "$ALS_SESSION" = "$session" ]; then
    als_log "hook=$hook session=$session invocations=$ALS_INVOCATIONS status=complete rearmed=0 owned=1 blocked=0"
    exit 0
  fi
}

# Read the .work_units count from progress.json into global ALS_WORK_UNIT_COUNT.
# Fail-open: absent file, absent/null .work_units (legacy loop), or malformed
# JSON all resolve to 0 — absence must never itself trigger a block. Sibling to
# als_read_file_state rather than folded into it, since that function's globals
# are read by loop_stall_guard.sh too, which has no use for work-unit counts.
als_read_work_units() {
  ALS_WORK_UNIT_COUNT=0
  if [ -n "$1" ] && [ -f "$1" ]; then
    local n; n=$(jq -r '(.work_units // {}) | length' "$1" 2>/dev/null)
    case "$n" in (''|*[!0-9]*) n=0;; esac
    ALS_WORK_UNIT_COUNT=$n
  fi
}

# Read the loop-scope evals verdict from a sibling evals.json into global
# ALS_LOOP_EVALS_RESULT: GO | TIER0 | NO-GO | UNJUSTIFIED | ABSENT. ABSENT
# covers no file, malformed JSON, or a non-"loop" scope (a stray pr-scope file
# must never satisfy the loop gate). Sibling to als_read_work_units for the
# same reason.
#
# tier_justification is required at every tier (owner directive), mirroring
# post_evals::validate_structure check 2 — eval_artifact::compute_go (the
# only place .result is derived) never inspects tier_justification, so a
# blank justification must be caught here or a GO-but-unjustified artifact
# would silently satisfy the loop gate. UNJUSTIFIED is distinct from NO-GO so
# the guard's block message can name the actual defect (missing
# tier_justification) instead of misattributing it to a failed eval run.
# Legacy flip: pre-existing GO loop artifacts written before this check
# existed, and lacking tier_justification, now block (owner directive
# 2026-07-06) rather than silently passing as before.
#
# Explicit NO-GO wins at every tier, including tier 0 (owner directive
# 2026-07-06): an exemption justifies having no evals, not overriding a
# recorded failure. So a tier-0 artifact with justification but no result
# field still reads TIER0 (the legitimate exemption), but a tier-0 artifact
# that explicitly recorded result:"NO-GO" must block like any other tier.
als_read_loop_evals_result() {
  ALS_LOOP_EVALS_RESULT="ABSENT"
  command -v jq >/dev/null 2>&1 || { als_log "hook=loop_state_guard evals=skipped reason=jq_missing"; return 0; }
  local f="$1/evals.json"
  [ -f "$f" ] || return 0
  jq -e . "$f" >/dev/null 2>&1 || return 0
  local scope; scope=$(jq -r '.scope // ""' "$f" 2>/dev/null)
  [ "$scope" = "loop" ] || return 0
  local result tier justification
  result=$(jq -r '.result // ""' "$f" 2>/dev/null)
  tier=$(jq -r '.tier // -1' "$f" 2>/dev/null)
  justification=$(jq -r '.tier_justification // "" | gsub("^\\s+|\\s+$"; "")' "$f" 2>/dev/null)
  if [ -z "$justification" ]; then ALS_LOOP_EVALS_RESULT="UNJUSTIFIED"
  elif [ "$result" = "GO" ]; then ALS_LOOP_EVALS_RESULT="GO"
  elif [ "$result" = "NO-GO" ]; then ALS_LOOP_EVALS_RESULT="NO-GO"
  elif [ "$tier" = "0" ]; then ALS_LOOP_EVALS_RESULT="TIER0"
  else ALS_LOOP_EVALS_RESULT="NO-GO"
  fi
}
