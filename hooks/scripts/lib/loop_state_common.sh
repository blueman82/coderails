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
# One log call must write exactly ONE line. Message text can carry model-chosen
# data (work-unit ids, session ids) whose newlines would otherwise append extra
# lines to the log — letting a crafted id forge a whole record, e.g. a
# fabricated "gate=passed" with its own timestamp, in the audit trail the
# dashboard reads. Enforcement never depended on this; the log's integrity does.
# Escape CR/LF to literal \n / \r so the message stays one line and stays legible.
# Escaping uses bash parameter expansion ONLY — no awk/sed/tr. als_log must keep
# working when PATH carries almost nothing (the jq-missing retry window relies on
# it to report its own failure), so it must not acquire external dependencies.
als_log() {
  local msg="$1"
  msg=${msg//$'\r'/\\r}
  msg=${msg//$'\n'/\\n}
  { printf '%s %s\n' "$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S%z)" "$msg" >> "$LOG_FILE"; } 2>/dev/null
}

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
# Two invocation forms are counted, because a loop can start either way:
#   1. PROGRAMMATIC — the assistant calls the Skill tool: an assistant message
#      with a tool_use block name=="Skill", input.skill matching the loop name.
#   2. SLASH-COMMAND — a human runs /coderails:agentic-loop: a user message
#      whose content is a STRING carrying "<command-name>/coderails:agentic-loop
#      </command-name>". This has NO assistant tool_use, so form 1 alone missed
#      it entirely — the bug that left every loop_stop_counts null for a
#      slash-started loop (the gate saw invocations=0 and exited before the
#      counter write). Both forms match the SAME name semantic: scoped
#      ("coderails:agentic-loop") or bare ("agentic-loop"), via (^|:)agentic-loop$
#      after stripping the command's leading "/".
# Structured jq match on a tool_use / command-name — never a free-text grep.
#
# Counts EVERY matching occurrence, not distinct loops. A single loop that is
# both slash-started AND later re-invokes the Skill tool programmatically counts
# 2 — the SAME accepted behavior the assistant-only form already had (two
# Skill(agentic-loop) tool_uses in one loop have always counted 2). The
# completed_marker=count ordinal in als_load_progress is a BACKSTOP; the primary
# re-arm signal is Phase -2's stub-first overwrite (SKILL.md "Recency"), which
# resets status to initialising regardless of count. Deliberately NOT deduping
# across forms: it would add jq complexity to defend an ordinal that stub-first
# already protects, and the mixed-form co-occurrence is not observed in practice
# (a loop is started by one trigger). Form 2 DOES scan all command-name tags in
# a single message (match "g"), so a loop tag after a non-loop tag in one
# message is not missed — that undercount WOULD silently re-hide the null bug.
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
#
# Per-line tolerant parse: a single malformed JSONL line must not collapse the
# WHOLE transcript's count to empty. Stage 1 (`jq -R 'fromjson? // empty'`)
# parses one line at a time and drops any line that isn't valid JSON; stage 2
# (`jq -s`) aggregates only the successfully-parsed lines. A line dropped at
# stage 1 is reported via a "skipped_malformed=N" stderr line (only when N>0,
# mirroring the reason-tag's stderr-only/fail-open-stdout convention above) so
# the retrying caller can surface it without disturbing the integer stdout
# contract. genuinely-empty input (0 lines) reports N=0, i.e. no line.
#
# total (grep -c, one read of the file) and parsed (jq -R, a SECOND,
# independent read) are not from a single read — against an actively-
# appended transcript, the two reads can observe different line counts across
# the flush-race window, which can skew or suppress the skipped_malformed
# breadcrumb for that one attempt. This affects only the breadcrumb's
# accuracy, never the correctness of the invocation COUNT itself (stage 2
# only ever aggregates what stage 1 actually parsed), and als_stable_invocations'
# retry loop rides out the same window for the count regardless.
#
# Explicit failure attribution: readability and stage-1 exit status are
# checked before either count is computed, so an unreadable file or a broken
# jq surfaces its own reason (read_error) rather than masquerading as a
# skipped-line breadcrumb. When stage 1 succeeds but produces ZERO parsed
# lines out of a NON-EMPTY input (every line malformed), that is reported
# distinctly as "all_lines_malformed" rather than skipped_malformed=N — a
# transcript that is 100% garbage is not "N lines skipped, rest counted", and
# conflating the two made a totally-unparseable read indistinguishable from
# one bad line in an otherwise-clean transcript.
# Known limitation: a bare `null` or `false` JSONL line is valid JSON but
# `fromjson? // empty` maps both to empty output, so stage 1 drops them and
# stage 2's count treats them as skipped_malformed — a real Claude Code
# transcript is always one JSON OBJECT per line, so this is unreachable in
# practice, not worth a code branch for.
als_count_invocations() {
  command -v jq >/dev/null 2>&1 || { echo "jq_missing" >&2; return; }
  [ -r "$1" ] || { echo "read_error" >&2; return; }
  local total parsed skipped
  total=$(grep -c '[^[:space:]]' "$1" 2>/dev/null); [ -z "$total" ] && total=0
  local tolerant tolerant_rc
  # select(type=="object") added at stage 1 (SECURITY FIX, reproduced full
  # bypass): a valid-JSON but non-object line (e.g. a bare `42`) survived
  # fromjson? same as a real record, then threw at stage 2's `.type` access
  # ("Cannot index number with string \"type\"") — collapsing this function's
  # entire count to 0 via the jq_parse_error path below. A count of 0 makes
  # als_gate_require_active_loop treat the session as "not a loop" and exit 0
  # BEFORE any complete-gate (retro/work_units/proof) ever runs — a single
  # attacker-plantable transcript line defeated every one of them. Filtering
  # here, not just at the final pass, is what makes `parsed` (and therefore
  # `skipped`) also reflect the exclusion truthfully: a non-object line now
  # counts toward skipped_malformed like any other line this function cannot
  # use, rather than surviving into `parsed` only to be silently dropped
  # later. This is the SAME tolerant-parse intent the function's own header
  # already states ("a single malformed JSONL line must not collapse the
  # WHOLE transcript's count to empty") — a non-object line is exactly the
  # malformed-for-this-purpose case that intent already covers, just not yet
  # enforced.
  tolerant=$(jq -R 'fromjson? | select(type == "object")' "$1" 2>/dev/null); tolerant_rc=$?
  if [ "$tolerant_rc" -ne 0 ]; then echo "read_error" >&2; return; fi
  parsed=0
  [ -n "$tolerant" ] && parsed=$(printf '%s' "$tolerant" | jq -s 'length' 2>/dev/null)
  [ -z "$parsed" ] && parsed=0
  skipped=$((total - parsed))
  if [ "$parsed" -eq 0 ] && [ "$total" -gt 0 ]; then
    echo "all_lines_malformed" >&2
  elif [ "$skipped" -gt 0 ]; then
    echo "skipped_malformed=$skipped" >&2
  fi
  printf '%s' "$tolerant" | jq -s -r '
    def loop_name: test("(^|:)agentic-loop$");
    [ .[]?
      # Form 1: assistant Skill tool_use.
      | ( select(.type == "assistant")
          | .message.content[]?
          | select(.type == "tool_use" and .name == "Skill")
          | (.input.skill // "")
          | select(loop_name) ),
        # Form 2: user slash-command message (content is a string carrying
        # <command-name>). Scan EVERY command-name tag in the string (match
        # with "g"), not just the first — a message could carry more than one
        # and the loop tag might not be first; matching only the first would
        # undercount. Strip the leading "/" and trim surrounding whitespace
        # before the anchored loop_name test — the capture class [^<\n]+ would
        # otherwise pull a trailing space/tab into the string and the "$"-anchored
        # test would fail, silently re-hiding the null-counter bug for a padded tag.
        ( select(.type == "user")
          | .message.content
          | select(type == "string")
          | ( [ match("<command-name>/?([^<\\n]+)</command-name>"; "g")
                | .captures[0].string ][]? )
          | gsub("^\\s+|\\s+$"; "")
          | select(loop_name) )
    ]
    | length
  ' 2>/dev/null || echo "jq_parse_error" >&2
}

# Stable invocation count: retry for the transcript-flush race until it settles.
# Logs EXACTLY ONE summary line via als_log when any attempt hit a reason tag
# (jq_missing / read_error / all_lines_malformed / jq_parse_error) or saw a
# partial skip — never one line per attempt (that was the ambiguous-recovery /
# double-log bug: a transient failure that recovered on retry was
# indistinguishable from one that never recovered, and a sustained failure
# logged once per attempt with no final verdict). outcome=recovered means the
# LAST attempt succeeded (no reason tag on that attempt); outcome=exhausted
# means it didn't. attempts=N is the number of als_count_invocations calls
# made. Zero lines when every attempt was clean: no reason tag on ANY attempt,
# AND no skipped lines on any attempt. Gate outcomes (stdout contract,
# fail-open) are unchanged — this only affects what gets logged.
#
# skipped_malformed=N (from als_count_invocations' per-line tolerant parse,
# for the ordinary case of one-or-a-few bad lines among otherwise-clean ones)
# is tracked SEPARATELY from the reason tag: a partial skip alone is not
# itself a failure needing a retry (the count is still valid), so it must not
# gate the settling check below the way a reason tag does. The field appended
# to the summary line is the MAX skipped_malformed seen ACROSS ALL ATTEMPTS
# (not just the last one) — a spike on an early attempt must not be lost if a
# later attempt happens to see fewer or zero skipped lines. It rides on the
# SAME summary line as reason=/attempts=/outcome=, appended whenever
# max_skipped>0, whether or not a reason tag also fired.
#
# read_error (unreadable/missing-mid-read file, or the stage-1 jq process
# itself failing) and all_lines_malformed (stage 1 succeeded but every
# non-blank line was malformed) are real reason tags, exactly like
# jq_missing/jq_parse_error — they gate settling and can never be conflated
# with the benign skipped_malformed breadcrumb, which reports a handful of
# bad lines in an otherwise-trustworthy read.
als_stable_invocations() {
  local transcript="$1" prev=-1 attempts=0 n=0 last_reason="" seen_reason="" max_skipped=0
  local err_file; err_file=$(mktemp 2>/dev/null) || err_file=""
  while [ "$attempts" -lt "$MAX_ATTEMPTS" ]; do
    # Single call per attempt: stdout (the count) captured normally, stderr
    # (the reason tag / skipped_malformed breadcrumb, if any) redirected to a
    # scratch file and read back — avoids calling the function twice per
    # attempt, which would re-read the transcript twice and could observe two
    # different states across the very flush-race window this retry loop
    # exists to ride out.
    local raw_err=""
    if [ -n "$err_file" ]; then
      n=$(als_count_invocations "$transcript" 2>"$err_file")
      raw_err=$(cat "$err_file" 2>/dev/null)
    else
      n=$(als_count_invocations "$transcript" 2>/dev/null)
      raw_err=""
    fi
    [ -z "$n" ] && n=0
    # Parse raw_err's up-to-two lines with bash builtins only (no head/sed) —
    # the no-jq test fixture's minimal PATH deliberately excludes everything
    # but the coreutils this function actually needs. skipped_malformed does
    # NOT gate the settling check below (a stable, nonzero-but-tolerant count
    # is still a trustworthy count) — only reason (jq_missing/jq_parse_error)
    # does, matching the pre-existing contract.
    local this_skipped=0
    last_reason=""
    while IFS= read -r line; do
      case "$line" in
        skipped_malformed=*) this_skipped="${line#skipped_malformed=}" ;;
        *) [ -n "$line" ] && last_reason="$line" ;;
      esac
    done <<EOF
$raw_err
EOF
    case "$this_skipped" in (''|*[!0-9]*) this_skipped=0;; esac
    [ "$this_skipped" -gt "$max_skipped" ] && max_skipped="$this_skipped"
    attempts=$((attempts + 1))
    if [ "$n" -eq "$prev" ] && [ -z "$last_reason" ]; then break; fi
    prev=$n
    [ -n "$last_reason" ] && seen_reason="$last_reason"
    [ "$attempts" -lt "$MAX_ATTEMPTS" ] && sleep "$SLEEP_S"
  done
  [ -n "$err_file" ] && rm -f "$err_file" 2>/dev/null
  if [ -n "$seen_reason" ] || [ "$max_skipped" -gt 0 ]; then
    local outcome="exhausted"
    [ -z "$last_reason" ] && outcome="recovered"
    local reason_field="${seen_reason:-none}"
    local skipped_suffix=""
    [ "$max_skipped" -gt 0 ] && skipped_suffix=" skipped_malformed=$max_skipped"
    als_log "hook=als_count_invocations reason=$reason_field attempts=$attempts outcome=$outcome$skipped_suffix"
  fi
  printf '%s' "$n"
}

# als_extract_last_text <transcript> <tail_lines>
#   Extracts the last assistant text block from a JSONL transcript. Returns the
#   joined text of the last assistant message that has any text content, or an
#   empty string if none exists (absent/unreadable transcript, no text blocks,
#   or every line in the tail window malformed). Same tolerant per-line
#   extraction shape as discipline_common.sh's dc_extract_last_text — both
#   carry the identical two-stage parse that tolerates a malformed line in the
#   tail window (see below). Duplicated rather than shared across the two libs
#   since loop_state_common.sh and discipline_common.sh are deliberately
#   independent (different hook families).
#   Per-line tolerant parse (same two-stage shape as als_count_invocations): a
#   single malformed line in the tail window must not collapse extraction of a
#   genuine final message to empty — stage 1 drops just the bad line, stage 2
#   aggregates over what's left. No jq-presence guard here (unlike
#   als_count_invocations): a missing jq makes stage 1 itself emit nothing,
#   which stage 2 reduces to "" — the pre-existing no-jq fail-open contract,
#   preserved unchanged. Neither this function nor its retrying wrapper
#   als_stable_last_text logs — a malformed-line skip on this path is silent
#   by design, matching the prior contract of never distinguishing
#   "malformed" from "no text yet". (Callers like voice_announce.sh log their
#   own extract_failed reason on empty.)
als_extract_last_text() {
  local transcript="$1" tail_lines="$2"
  tail -n "$tail_lines" "$transcript" 2>/dev/null | jq -R 'fromjson? // empty' 2>/dev/null | jq -s -r '
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
#   (possibly empty, e.g. no assistant text yet, or every line in the tail
#   window malformed). Sets ALS_LAST_ATTEMPTS to the iteration count consumed.
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

# als_loop_active_incomplete <transcript_path> <cwd> <session_id>
#   Non-exiting predicate for the discipline hooks' Stop-only warn demotion
#   (PR1 of the ceremony-noise-reduction loop). Returns 0 (true, shell
#   success) iff the agentic-loop Skill has been INVOKED for this session and
#   the loop is not exempt as complete; returns 1 (false) otherwise. Mirrors
#   the als_gate_* pair (als_gate_require_active_loop + als_load_progress +
#   als_gate_loop_complete) exactly, but as a predicate rather than an exiting
#   gate — no `exit` calls and no logging here; callers own both. `session_id`
#   MUST already be sanitised via als_sanitise_session_id before being passed in.
#
#   Truth table: active iff invocations>0 AND NOT (status="complete" AND
#   NOT rearmed AND session-owned). Concretely:
#     invocations=0                                          -> INACTIVE (1)
#     invocations>0, no progress.json yet (invoked but not
#       stubbed) or absent/corrupt/foreign-owned progress.json -> ACTIVE (0)
#     invocations>0, status=complete, not rearmed, owned      -> INACTIVE (1)
#     invocations>0, status=complete, rearmed (invocations>marker) -> ACTIVE (0)
#     invocations>0, status=complete, but session_id mismatch  -> ACTIVE (0)
#   The absent/corrupt/foreign-owned case reading ACTIVE is BY DESIGN, not an
#   oversight: als_read_file_state's fail-open defaults (empty status/session,
#   marker=0) never satisfy the completed-and-owned exemption, so those states
#   fall through to active/warn — and loop_state_guard/loop_stall_guard block
#   those same stops separately via their own gates, so the stop is never
#   left unpoliced even though this predicate alone demotes it.
als_loop_active_incomplete() {
  local transcript="$1" cwd="$2" session_id="$3"
  local invocations; invocations=$(als_stable_invocations "$transcript")
  [ -z "$invocations" ] && invocations=0
  [ "$invocations" -eq 0 ] && return 1
  local als_path; als_path=$(als_resolve_path "$cwd" "$session_id")
  als_read_file_state "$als_path"
  local rearmed=0
  [ "$invocations" -gt "$ALS_MARKER" ] && rearmed=1
  if [ "$ALS_STATUS" = "complete" ] && [ "$rearmed" -eq 0 ] && [ "$ALS_SESSION" = "$session_id" ]; then
    return 1
  fi
  return 0
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
#
# UNSTAMPED (added for grade-loop): a GO or TIER0 verdict is demoted to
# UNSTAMPED when the file lacks a valid post_evals.sh grade-loop stamp — no
# `.grading.by`/`.grading.checksum`, or the checksum recomputed against the
# file's OWN `.result` doesn't match what's stored. This is what makes GO/
# TIER0 mean "graded by the neutral script", not "someone wrote GO into the
# file". NO-GO/UNJUSTIFIED are untouched — they already block, and an
# unstamped NO-GO is not a forgery risk (nothing to gain by faking a
# rejection). Fail-closed: if eval-artifact.sh can't be sourced or
# grading_checksum can't be called, treat that exactly like a missing stamp
# (UNSTAMPED), never fall through to GO/TIER0.
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

  case "$ALS_LOOP_EVALS_RESULT" in
    GO|TIER0)
      local stamped_by stamped_checksum recomputed
      stamped_by=$(jq -r '.grading.by // ""' "$f" 2>/dev/null)
      stamped_checksum=$(jq -r '.grading.checksum // ""' "$f" 2>/dev/null)
      if [ -z "$stamped_by" ] || [ -z "$stamped_checksum" ]; then
        ALS_LOOP_EVALS_RESULT="UNSTAMPED"
      elif ! source "$(dirname "${BASH_SOURCE[0]}")/../../../scripts/lib/eval-artifact.sh" 2>/dev/null; then
        ALS_LOOP_EVALS_RESULT="UNSTAMPED"
      else
        recomputed=$(eval_artifact::grading_checksum "$f" "$result" 2>/dev/null)
        if [ -z "$recomputed" ] || [ "$recomputed" != "$stamped_checksum" ]; then
          ALS_LOOP_EVALS_RESULT="UNSTAMPED"
        fi
      fi
      ;;
  esac
}

# Gate: on a `complete` declaration, require a parseable retro.json
# (schema_version >= 1) beside progress.json - Phase 13's write contract.
# Presence + parse only (honest boundary: provenance/content fidelity is
# not checkable here, same limit as every other guard). Fail-open when jq
# is absent, matching bump_loop_stop_count.
# Accepted schema_version is any integer >= 1 (forward-compatible - the
# guard cares that the retro exists and is a recognised schema, not which
# exact version). A non-numeric, absent, or < 1 value is still wrong_schema
# and blocks, so an empty/garbage retro can never pass as fail-never.
als_gate_retro_on_complete() {
  local category="$1" hook="$2" session="$3"
  local category_lc; category_lc=$(printf '%s' "$category" | tr '[:upper:]' '[:lower:]')
  [ "$category_lc" = "complete" ] || return 0
  command -v jq >/dev/null 2>&1 || { als_log "hook=$hook session=$session retro_gate=skipped_no_jq"; return 0; }
  [ -n "$ALS_PATH" ] || { ALS_RETRO_STATE="no_als_path"; als_log "hook=$hook session=$session retro=no_als_path blocked=1"; echo "[loop-stall-guard] retro gate: ALS_PATH unset — cannot locate retro.json." >&2; exit 2; }
  local retro; retro="$(dirname "$ALS_PATH")/retro.json"
  ALS_RETRO_STATE="present"
  if [ ! -f "$retro" ]; then ALS_RETRO_STATE="absent"
  elif ! jq -e . "$retro" >/dev/null 2>&1; then ALS_RETRO_STATE="malformed"
  elif ! jq -e '(.schema_version) as $v | ($v | type == "number") and $v >= 1' "$retro" >/dev/null 2>&1; then ALS_RETRO_STATE="wrong_schema"
  fi
  if [ "$ALS_RETRO_STATE" != "present" ]; then
    als_log "hook=$hook session=$session retro=$ALS_RETRO_STATE blocked=1"
    echo "[loop-stall-guard] LOOP-STOP: complete declared but retro.json is $ALS_RETRO_STATE.
Phase 13 teardown writes retro.json (schema_version >= 1) beside progress.json
BEFORE declaring complete: assemble the retro (see agentic-loop SKILL.md
Phase 13), write it, then re-declare complete." >&2
    exit 2
  fi
}

# Gate: on a `complete` declaration, block if any progress.json work_unit is
# not terminal. Terminal = "done", or "dropped" with a non-empty (post-trim)
# STRING dropped_reason. Anything else (pending, in-progress, blocked, or any
# other value) blocks — this is the structural "nothing is deferred"
# enforcement; prose standing-orders alone were observed to fail (deferred
# twice in one loop with the standing-order loaded the whole time).
#
# dropped_reason must be type-guarded BEFORE gsub touches it: jq's gsub
# throws on a non-string input (number/bool/array/object), which would kill
# the whole jq -r pipeline, collapse offenders to empty, and fail the gate
# OPEN — the exact bypass this gate exists to prevent. A non-string
# dropped_reason is therefore treated as absent (not terminal, blocks),
# same as a missing key or an empty/whitespace-only string.
#
# The unit VALUE itself must be type-guarded too, BEFORE .status/.dropped_reason
# touch it: a scalar value (string/number) throws "Cannot index string/number
# with string ..." inside the same jq -r pipeline, which kills the pipeline
# for EVERY unit in the file, not just the malformed one — one bad scalar
# entry would blind the gate to a genuinely-pending sibling unit elsewhere in
# work_units. status/dropped_reason are therefore read as null when the value
# isn't an object; a null status is not "done"/"dropped", so it blocks same as
# a missing key — a non-object unit has no verifiable done/dropped status, so
# it can never be treated as terminal.
#
# work_units is an OBJECT keyed by unit id (verified against every real
# progress.json on disk) — to_entries/.key gives the real id. An array shape
# is tolerated defensively via to_entries too, so a missing .id falls back to
# the array INDEX ("[0]") rather than the uninformative literal "null" —
# object is still the primary, expected shape.
#
# Fail-open at the FILE level: jq absent, ALS_PATH unset/missing, absent/null
# work_units, empty object/array, or malformed (unparseable) progress.json all
# allow. Fires ONLY on `complete` (case-insensitively).
#
# This is deliberately NOT the same posture as als_gate_retro_on_complete,
# which BLOCKS on an absent/malformed retro.json (its artifact is mandatory at
# Phase 13). The two gates share only the jq-absent skip. work_units is
# OPTIONAL — a trivial or legacy loop may never populate it — so its ABSENCE
# must never itself block. The distinction: absence of the field fails open,
# but an individual unit that cannot be PROVEN terminal fails closed (blocks),
# so a malformed entry can never launder an unfinished unit into a completion.
#
# Allowlist is deliberately narrow: {done, dropped}. Do NOT widen to accept
# "merged"/"complete"/other synonyms seen in historical loops — those
# vocabularies grew because nothing constrained them; widening here would
# rebuild the non-enforcement this gate exists to remove.
als_gate_work_units_on_complete() {
  local category="$1" hook="$2" session="$3"
  local category_lc; category_lc=$(printf '%s' "$category" | tr '[:upper:]' '[:lower:]')
  [ "$category_lc" = "complete" ] || return 0
  command -v jq >/dev/null 2>&1 || { als_log "hook=$hook session=$session work_units_gate=skipped_no_jq"; return 0; }
  [ -n "$ALS_PATH" ] && [ -f "$ALS_PATH" ] || return 0
  jq -e . "$ALS_PATH" >/dev/null 2>&1 || return 0
  local offenders
  offenders=$(jq -r '
    ( .work_units // {} ) as $wu
    | ( if ($wu | type) == "array"
        then [ $wu | to_entries[] | {id: ((if (.value | type) == "object" then .value.id else null end) // "[\(.key)]"),
               status: (if (.value | type) == "object" then .value.status else null end),
               dropped_reason: (if (.value | type) == "object" then .value.dropped_reason else null end)} ]
        elif ($wu | type) == "object"
        then [ $wu | to_entries[] | {id: .key,
               status: (if (.value | type) == "object" then .value.status else null end),
               dropped_reason: (if (.value | type) == "object" then .value.dropped_reason else null end)} ]
        else [] end )
    | map( select( ((.status == "done")
          or ((.status == "dropped")
              and (((.dropped_reason | if type == "string" then gsub("^\\s+|\\s+$";"") else "" end) // "") != ""))) | not ) )
    | map(.id)
    | join(", ")
  ' "$ALS_PATH" 2>/dev/null)
  [ -n "$offenders" ] || return 0
  als_log "hook=$hook session=$session work_units_gate=blocked offenders=$offenders"
  echo "[loop-stall-guard] LOOP-STOP: complete declared but work_units are unfinished: $offenders.
Every work_unit must be \"done\", or \"dropped\" with a non-empty dropped_reason,
before declaring complete. Finish or explicitly drop (with a reason) the
listed unit(s), then re-declare complete." >&2
  exit 2
}

# Gate: on a `complete` declaration, block if any frozen proof.json proof was
# never executed (in THIS session's own transcript) or last-executed with an
# error. NEW enforcement class for this repo: every prior gate here checks
# artifact presence/shape/stamp (retro.json exists and parses; work_units
# entries carry a terminal status); this one re-derives a verdict from raw
# transcript tool_use/tool_result pairs instead of trusting any field the
# artifact itself claims. That is also its honest boundary: the gate verifies
# a command RAN in this session's transcript and did NOT error — it CANNOT
# verify it was the RIGHT command. A weak, poorly-chosen frozen proof set
# passes trivially. What it buys: the proof CHOICE is auditable and
# time-stamped (frozen at Phase 2.7e, before implementation, per
# skills/agentic-loop/SKILL.md), and EXECUTION can no longer be
# self-reported — proof.json's own `.status` field is present but never
# consulted for the verdict; only a real tool_use/tool_result pair in the
# transcript can satisfy a proof.
#
# TRUST BOUNDARY: the gate treats the transcript as harness-written. A
# session that deliberately APPENDS forged tool_use/tool_result records to
# its own transcript file (it is an ordinary writable file, not a sealed
# log) can defeat this gate — no transcript-reading hook can stop that. The
# gate's actual target is the OBSERVED failure class: honest self-deception
# and lazy self-reporting (`"status":"pass"` written without ever running
# the command), not adversarial transcript forgery. Same overclaim-avoidance
# rule as the rest of this header — state what the gate defends against, not
# a stronger guarantee it cannot actually make.
#
# Orchestrator-session scope, BY DESIGN: subagent/worker Bash calls never
# appear in the orchestrator's own transcript (verified against real
# delegating transcripts elsewhere in this codebase) — proofs MUST be run by
# the orchestrator itself, in its own session, or this gate false-blocks.
# That is the intended enforcement, not a bug: a proof satisfied only inside
# a dispatched worker's transcript proves nothing to THIS gate, which is the
# point — see task-evals' identical grader-independence rationale.
#
# Exact-match rationale: a SUBSTRING match would be trivially satisfiable by
# `echo "the cmd"` or a comment containing the text — exact trimmed equality
# means the executed command literally IS the frozen proof command, closing
# that gap the same way the work_units gate's allowlist closes status-string
# gaming.
#
# Fail-open on ABSENT proof.json, fail-closed on malformed/unverifiable —
# the same established asymmetry as retro.json (mandatory, blocks on
# absence) versus work_units (optional, blocks only on an unprovable entry).
# proof.json is OPTIONAL and adopted voluntarily (mirrors task-evals'
# voluntary-adoption posture): a loop authored before this gate existed, or
# with no executable surface to prove, writes no proof.json and is not
# punished for its absence. But once present, a garbage file must never read
# as absence — malformed JSON, a bad schema_version, or a proofs entry that
# cannot be verified all fail CLOSED, mirroring the work_units rule that a
# unit which cannot be proven terminal blocks rather than passing by default.
#
# Cost: one O(transcript) mining pass (same cost class als_count_invocations
# already pays on every Stop, but this gate only runs on `complete`
# declarations, not on every Stop) plus O(proofs) index lookups, with the
# proof count itself hard-capped at 100 before any mining happens. This is
# NOT the whole story on its own: an earlier version of this gate did an
# O(proofs x executions) rescan per proof, which a model-writable, uncapped
# proof.json could inflate past the 15s hooks.json timeout — a timed-out
# hook never exits 2, so the Stop proceeds UNBLOCKED. The <=100 cap and the
# O(proofs + executions) command-match index (see the transcript-mining
# comment below) are both required to close that: the cap alone still lets a
# ~100 x 100-execution transcript stay fast, and the index alone doesn't stop
# an attacker from inflating proof.json unboundedly without it.
als_gate_proofs_on_complete() {
  local category="$1" hook="$2" session="$3" transcript="$4"
  local category_lc; category_lc=$(printf '%s' "$category" | tr '[:upper:]' '[:lower:]')
  [ "$category_lc" = "complete" ] || return 0
  command -v jq >/dev/null 2>&1 || { als_log "hook=$hook session=$session proof_gate=skipped_no_jq"; return 0; }
  [ -n "$ALS_PATH" ] || return 0
  local proof_file; proof_file="$(dirname "$ALS_PATH")/proof.json"
  [ -f "$proof_file" ] || return 0
  jq -e . "$proof_file" >/dev/null 2>&1 || {
    als_log "hook=$hook session=$session proof_gate=blocked offenders=malformed"
    echo "[loop-stall-guard] LOOP-STOP: complete declared but proof.json is malformed (not valid JSON).
A frozen proof.json must be valid JSON. Fix or regenerate it, then re-declare complete." >&2
    exit 2
  }
  jq -e '(.schema_version) as $v | ($v | type == "number") and $v >= 1' "$proof_file" >/dev/null 2>&1 || {
    als_log "hook=$hook session=$session proof_gate=blocked offenders=wrong_schema"
    echo "[loop-stall-guard] LOOP-STOP: complete declared but proof.json has no valid schema_version (>= 1 required).
Regenerate proof.json with a numeric schema_version >= 1, then re-declare complete." >&2
    exit 2
  }
  # .proofs absent/null -> nothing to prove (allow). Present-but-not-array is
  # a malformed shape and blocks, same posture as work_units' file-shape check.
  local proofs_type; proofs_type=$(jq -r '(.proofs // null) | type' "$proof_file" 2>/dev/null)
  case "$proofs_type" in
    null) return 0 ;;
    array) : ;;
    *)
      als_log "hook=$hook session=$session proof_gate=blocked offenders=malformed_shape"
      echo "[loop-stall-guard] LOOP-STOP: complete declared but proof.json's .proofs field is not an array.
Regenerate proof.json with .proofs as a JSON array, then re-declare complete." >&2
      exit 2
      ;;
  esac
  # proof_count is numerically validated BEFORE either comparison below — a
  # bare `[ "$x" -gt 0 ] 2>/dev/null || return 0` conflates "jq failed /
  # printed garbage" with "the deliberate, legitimate empty-proofs allow";
  # both silently fell through to the same `return 0`. A jq failure here
  # (missing binary already ruled out above; a truncated/mid-write proof.json
  # racing the reader is the realistic cause) must fail CLOSED like every
  # other unparseable-proof.json case in this gate, not silently pass.
  local proof_count; proof_count=$(jq '.proofs | length' "$proof_file" 2>/dev/null)
  case "$proof_count" in
    ''|*[!0-9]*)
      als_log "hook=$hook session=$session proof_gate=blocked offenders=jq_error"
      echo "[loop-stall-guard] LOOP-STOP: complete declared but proof.json's .proofs length could not be read.
Regenerate proof.json (it may be truncated or mid-write), then re-declare complete." >&2
      exit 2
      ;;
  esac
  # MERGE-BLOCKER FIX: proof.json is model-writable and uncapped, and this
  # gate previously did a linear rescan of $executions PER PROOF entry —
  # O(proofs x transcript_bash_calls). loop_stall_guard is registered with a
  # 15s hooks.json timeout, and a timed-out hook never exits 2 — the Stop
  # proceeds UNBLOCKED. An inflated proof.json (reproduced: ~2,000 proofs x
  # ~2,000 Bash calls ~= 15s) therefore defeats the gate by making the CHECK
  # itself time out, not by satisfying it. A hard cap, checked BEFORE any
  # transcript mining, closes this: a legitimate proof set is 3-10 entries;
  # 100+ is itself suspicious and blocks fail-closed rather than being mined.
  if [ "$proof_count" -gt 100 ]; then
    als_log "hook=$hook session=$session proof_gate=blocked offenders=too_many_proofs count=$proof_count"
    echo "[loop-stall-guard] LOOP-STOP: complete declared but proof.json declares $proof_count proofs, exceeding the cap of 100.
A legitimate frozen proof set is a handful of commands (typically 3-10). Reduce
proof.json to <= 100 proofs, then re-declare complete." >&2
    exit 2
  fi
  [ "$proof_count" -gt 0 ] || return 0

  # Two-stage tolerant parse of the transcript (same idiom als_count_invocations
  # uses): a single malformed JSONL line must not collapse the whole scan.
  # executions: every Bash tool_use run in the FOREGROUND ONLY (never
  # run_in_background), in transcript order, as {id, command}. results: every
  # tool_result's {tool_use_id, is_error}. Both mined in ONE jq -s pass
  # alongside proof.json's own .proofs array, so verdicts are computed in a
  # single invocation. `select(type=="object")` guards every record AND every
  # content-array element before its own `.type` is read: a transcript line
  # that is valid JSON but a non-object (bare array/number/string/bool)
  # survives the fromjson? stage same as a genuine record, and without this
  # guard `.type` on it throws, aborting the WHOLE jq program — collapsing
  # $verdicts to empty and blocking a legitimate complete on offenders=jq_error.
  # That is precisely the "one malformed line collapses the whole scan"
  # failure this gate's own header rules out; the guard keeps a stray
  # non-object line inert (skipped) instead of fatal, at both the top-level
  # record and the nested content-array level.
  #
  # COMMAND-MATCH INDEX (the O(n+m) fix): $executions is grouped by its
  # trimmed command into a map (last execution per distinct command wins,
  # since group_by is stable and preserves transcript order within each
  # group, so `.[-1]` of a group is the LAST matching execution — the exact
  # semantic the per-proof scan used to compute via `$matches[-1]`). Building
  # this ONCE costs O(executions), then each proof does an O(1) map lookup
  # instead of an O(executions) linear rescan — O(proofs + executions)
  # overall instead of O(proofs x executions), bounded further by the <=100
  # proof cap above. The command key is trimmed AND type-guarded (non-string
  # or empty commands dropped) BEFORE group_by/from_entries: a raw non-string
  # value reaching from_entries as an object key throws ("Cannot use ... as
  # object key"), which would kill the whole jq program the same way the
  # non-object-record bug did — the index is built defensively for exactly
  # that reason. RESULT pairing (matching a proof's chosen execution id
  # against $results) stays a per-proof linear scan, NOT a second map: a
  # map keyed by tool_use_id would collide "no result exists for this id"
  # (must read as unexecuted) with "a result exists with is_error:null" (must
  # read as satisfied, per the deliberate null-tolerance rule) into the same
  # missing-key lookup, silently losing that distinction. The per-proof
  # results scan is bounded by the same <=100 cap and by $results' own size
  # (one result per tool_use, itself bounded by the transcript), so there is
  # no perf reason to also map it.
  #
  # OUTPUT SHAPE: the pass emits a two-line "<count>\n<offenders>" string,
  # count FIRST. This is what makes offenders extraction fail closed: a
  # completely clean run (zero offenders) still emits a non-empty first line
  # (the digit count), so `[ -n "$out" ]` genuinely distinguishes "the pass
  # ran" from "the pass failed" — a prior version ran offenders extraction as
  # its OWN SEPARATE jq call on $verdicts, whose transient failure yielded ""
  # indistinguishable from the legitimate "zero offenders" case, i.e. a
  # silent pass. One pipeline, one failure mode, guarded once.
  local out
  out=$(
    jq -R 'fromjson? // empty' "$transcript" 2>/dev/null | \
    jq -s --slurpfile proofdoc "$proof_file" -r '
      . as $records
      | ($proofdoc[0].proofs) as $proofs
      | ( [ $records[]?
            | select(type == "object" and .type == "assistant")
            | .message.content[]?
            | select(type == "object" and .type == "tool_use" and .name == "Bash")
            | select((.input.run_in_background // false) == false)
            | select((.id | type == "string" and length > 0))
            | {id: .id, command: (.input.command // "")} ] ) as $executions
      | ( $executions
          | map(select((.command | type) == "string" and (.command | gsub("^\\s+|\\s+$";"")) != ""))
          | map(.command |= gsub("^\\s+|\\s+$";""))
          | group_by(.command)
          | map({key: .[0].command, value: .[-1]})
          | from_entries
        ) as $exec_index
      | ( [ $records[]?
            | select(type == "object" and .type == "user")
            | .message.content[]?
            | select(type == "object" and .type == "tool_result")
            | select((.tool_use_id | type == "string" and length > 0))
            | {tool_use_id: .tool_use_id, is_error: (.is_error // null)} ] ) as $results
      | [ $proofs[] as $p
          | ( if ($p | type) != "object" then
                {id: "P\($proofs | index($p))", verdict: "unverifiable"}
              else
                ( ($p.id | if type == "string" and length > 0 then . else null end)) as $rawid
                | ($rawid // "P\($proofs | index($p))") as $id
                | ( $p.cmd | if type == "string" then gsub("^\\s+|\\s+$";"") else null end ) as $cmd
                | if ($cmd == null or $cmd == "") then
                    {id: $id, verdict: "badcmd"}
                  else
                    ( $exec_index[$cmd] ) as $last
                    | if ($last == null) then
                        {id: $id, verdict: "unexecuted"}
                      else
                        ( [ $results[] | select(.tool_use_id == $last.id) ] | last) as $result
                        | if ($result == null) then
                            {id: $id, verdict: "unexecuted"}
                          elif ($result.is_error == true) then
                            {id: $id, verdict: "failed"}
                          else
                            {id: $id, verdict: "satisfied"}
                          end
                      end
                  end
              end )
        ] as $verdicts
      | "\($verdicts | length)\n\([ $verdicts[] | select(.verdict != "satisfied") | "\(.id)(\(.verdict))" ] | join(", "))"
    ' 2>/dev/null
  )
  [ -n "$out" ] || { als_log "hook=$hook session=$session proof_gate=blocked offenders=jq_error"; echo "[loop-stall-guard] LOOP-STOP: complete declared but proof.json/transcript could not be evaluated." >&2; exit 2; }

  local n offenders
  n=$(printf '%s\n' "$out" | sed -n '1p')
  offenders=$(printf '%s\n' "$out" | sed -n '2p')
  case "$n" in
    ''|*[!0-9]*)
      als_log "hook=$hook session=$session proof_gate=blocked offenders=jq_error"
      echo "[loop-stall-guard] LOOP-STOP: complete declared but proof.json/transcript could not be evaluated." >&2
      exit 2
      ;;
  esac
  if [ -n "$offenders" ]; then
    als_log "hook=$hook session=$session proof_gate=blocked offenders=$offenders"
    echo "[loop-stall-guard] LOOP-STOP: complete declared but these frozen proofs are not verified: $offenders.
Run each named proof's cmd VERBATIM as its own single Bash command in THIS
(the orchestrator's) session, in the foreground (never run_in_background) —
commands run inside dispatched workers or subagents never appear in this
transcript and cannot satisfy this gate — then re-declare complete." >&2
    exit 2
  fi
  als_log "hook=$hook session=$session proof_gate=ok proofs=$n"
}

# Reporter (NOT a gate): on a `complete` declaration, print the loop's mined
# cost to the human's terminal via top-level `systemMessage`, mechanically —
# so a `complete` loop can no longer finish without the human seeing what it
# cost, the way SKILL.md's Phase 13 prose has always demanded but a model
# could silently skip. This is the fix for that: prose can't enforce prose,
# a hook can.
#
# DELIBERATE POSTURE INVERSION — read this before "fixing" this function:
# every other gate in this file (check_verify_loop.sh and
# check_confidence_labels.sh follow the same house idiom elsewhere) runs its
# jq emission FIRST and lets that emission's exit status gate the caller's
# own `exit 0` — i.e. they fail TOWARD blocking. This function does the
# OPPOSITE on purpose: it must NEVER block, under any failure. Rationale:
# dc_mine_token_usage (hooks/scripts/lib/loop_cost.sh:7-12) is contractually
# fail-open to `{}` on any mining error and documents that it "must never
# block a caller" — retro.json's `.cost` can legitimately be `{}` (miner ran,
# failed open) on an otherwise perfectly valid, already-finished loop. If
# this reporter were written in the house fail-closed style, a miner bug
# would deadlock a loop that has ALREADY passed the retro/work_units/proof
# gates above it — strictly worse than the unrecorded-cost bug it exists to
# fix. Any error path here must therefore emit nothing and return, never
# exit non-zero. Do not widen this into the house fail-closed idiom.
#
# Fires ONLY on `category == "complete"` (case-insensitively, mirroring the
# category_lc idiom shared by every sibling gate above). Reads retro.json at
# `$(dirname "$ALS_PATH")/retro.json` — same resolution als_gate_retro_on_complete
# uses. By the time this runs (called AFTER the retro/work_units/proof gates
# at the loop_stall_guard.sh call site), retro.json is already proven present
# and parseable with schema_version >= 1 by als_gate_retro_on_complete, so
# this function does not re-validate file existence/parseability defensively
# — it only branches on the fields it needs.
#
# Behaviour matrix (see skills/agentic-loop/teardown.md for the cost-mining
# contract this reads):
#   schema_version < 2 (legacy, pre-cost-miner retro)      -> silent
#   schema_version >= 2, .cost populated (has a usd total) -> print USD +
#     tokens + staleness age
#   schema_version >= 2, .cost non-empty but MISSING total_usd_estimate
#     and/or total_tokens (partial miner output, schema drift) -> print
#     "cost recorded but incomplete (missing <field(s)>)" — NEVER return
#     silently and NEVER fabricate a $ figure. A silent return here would
#     recreate, inside this very mechanism, the exact failure this PR exists
#     to fix: a cost that exists on disk but never reaches the human.
#   schema_version >= 2, .cost == {} (miner ran, failed open) -> print "cost
#     unavailable (miner returned no data)" — NEVER a fabricated $ figure
#   schema_version >= 2, .cost absent (teardown skipped the mining sub-step)
#     -> print "cost not recorded" — deliberately distinct text from the
#     miner-failed-open case above: absent = step skipped, {} = miner ran and
#     came back empty. Different bugs, different messages; collapsing them
#     into one message would silently relocate the original bug (a cost the
#     human never sees) from model-omission to hook-omission instead of
#     fixing it. The incomplete-but-non-empty case above is a THIRD distinct
#     message for the same reason — collapsing it into either the {} case or
#     a silent return would do the same thing this whole PR exists to stop.
# schema_version is therefore the row-2-vs-row-4 discriminator, not
# cost-presence: rows 2 and 4 both have `.cost` absent, so cost-presence
# alone cannot tell "legacy loop, nothing to report" from "sv2 loop, teardown
# skipped a step it should have run".
#
# Staleness: computed from `.cost.prices_as_of` (a YYYY-MM-DD date string) vs
# today, in DAYS. The date math itself fails open — a `prices_as_of` value
# `date` cannot parse falls back to printing the raw string verbatim rather
# than erroring or fabricating an age. Staleness is reported inline as
# information, never as a block: the shipped price table is routinely weeks
# stale, so treating staleness as a failure condition would fire on every
# single loop.
# prices_as_of is unverifiable self-report — it measures "days since a human
# typed a date here," not "are the rates still correct" (no pricing API
# exists to check against; see model_prices.json's price_source note). Past
# this many days, nag a human to go check, without claiming the RATES
# themselves are wrong (that can never be known from a date alone).
# Staleness threshold in days. 14, not 30, and the reason is empirical rather
# than aesthetic: the shipped table sits at prices_as_of 2026-06-24 — 23 days
# old at the time this was written. A 30-day threshold is SILENT on the real
# table, i.e. the nag would never fire on the exact data that motivated it,
# which is a feature that exists only in its own tests. 14 also roughly tracks
# how often published rates actually move. Nothing enforces this number; it is
# a judgement, and a wrong one is cheap here because this only ever WARNS.
ALS_PRICE_STALE_DAYS=14
als_report_cost_on_complete() {
  local category="$1" hook="$2" session="$3"
  local category_lc; category_lc=$(printf '%s' "$category" | tr '[:upper:]' '[:lower:]')
  [ "$category_lc" = "complete" ] || return 0
  command -v jq >/dev/null 2>&1 || { als_log "hook=$hook session=$session cost_report=skipped_no_jq"; return 0; }
  [ -n "$ALS_PATH" ] || { als_log "hook=$hook session=$session cost_report=skipped_no_als_path"; return 0; }
  local retro; retro="$(dirname "$ALS_PATH")/retro.json"
  # Absent/unreadable retro: the retro gate above already blocked on this, so
  # reaching here means it was skipped (no jq) or the file vanished mid-turn.
  # Silent to the human by design — the gate owns that message — but logged.
  [ -f "$retro" ] || { als_log "hook=$hook session=$session cost_report=skipped_no_retro"; return 0; }

  # The >=2 comparison happens INSIDE jq, deliberately, and must stay there.
  # als_gate_retro_on_complete (which runs immediately before this reporter
  # and lets the retro through) validates schema_version with jq's NUMERIC
  # `>=`, so a float 2.0 or 2.5 passes it. Comparing in bash instead means
  # pattern-matching a string: `case $sv in *[!0-9]*)` matches the "." and
  # drops a float — so a retro carrying a perfectly valid cost would pass the
  # gate and then vanish here, printing nothing (verified end-to-end: a
  # {"schema_version":2.0, cost:{...$64.46...}} retro emitted absolutely
  # nothing). Two validators disagreeing about the same field is how the
  # exact bug this reporter exists to fix survives INSIDE the fix.
  # schema_version is authored freehand by an LLM per prose instruction, not
  # emitted by trusted code — treat it as adversarial input like every other
  # field here, even though no float instance exists in the corpus yet.
  local sv_ok; sv_ok=$(jq -r '(.schema_version // 0) | if type == "number" then (. >= 2) else false end' "$retro" 2>/dev/null)
  # Legacy grandfather: a schema_version 1 retro predates the cost miner
  # entirely, so there is no cost to report and silence is correct. Logged
  # anyway — a silent path that leaves NO trace is indistinguishable from a
  # broken one during an audit, which is the whole failure class this
  # reporter exists to close.
  [ "$sv_ok" = "true" ] || { als_log "hook=$hook session=$session cost_report=skipped_legacy_or_bad_sv"; return 0; }

  local cost_type; cost_type=$(jq -r '(.cost // null) | type' "$retro" 2>/dev/null)
  local msg=""
  case "$cost_type" in
    object)
      local is_empty; is_empty=$(jq -r '(.cost | length) == 0' "$retro" 2>/dev/null)
      if [ "$is_empty" = "true" ]; then
        msg="cost unavailable (miner returned no data)"
      else
        # Scalars only. `jq -r` on a non-scalar (array/object) emits its
        # PRETTY-PRINTED form — real newlines and all — which then lands
        # inside the human-facing message: "Loop cost: $[\n 1,\n 2\n] (...)"
        # (verified). That is not the "visibly-wrong beats fabricated" tradeoff
        # this function makes elsewhere: that rule assumes a raw value a human
        # can eyeball on one line, and it smuggles newlines into a report the
        # terminal renders. A field of the wrong TYPE is unusable data, which
        # is exactly what the incomplete path below already exists to report —
        # so select non-scalars to empty and let them fall into it.
        local usd tokens prices_as_of
        usd=$(jq -r '(.cost.total_usd_estimate | select(type=="number" or type=="string")) // empty' "$retro" 2>/dev/null)
        tokens=$(jq -r '(.cost.total_tokens | select(type=="number" or type=="string")) // empty' "$retro" 2>/dev/null)
        prices_as_of=$(jq -r '(.cost.prices_as_of | select(type=="string")) // empty' "$retro" 2>/dev/null)
        if [ -z "$usd" ] || [ -z "$tokens" ]; then
          local missing=""
          [ -z "$usd" ] && missing="total_usd_estimate"
          if [ -z "$tokens" ]; then
            [ -n "$missing" ] && missing="${missing}, total_tokens" || missing="total_tokens"
          fi
          msg="cost recorded but incomplete (missing ${missing})"
          als_log "hook=$hook session=$session cost_report=cost_incomplete"
          jq -n --arg m "$msg" '{systemMessage: $m}' 2>/dev/null
          return 0
        fi
        # Staleness age. WARNS inline, never blocks: a stale price table means
        # the table needs maintenance, not that this loop's work is invalid —
        # and the table is routinely weeks old, so blocking on it would refuse
        # every completion.
        #
        # The strict shape check before `date` is load-bearing, for the same
        # reason as the printf guard below: `date -j -f %Y-%m-%d` does NOT
        # reject trailing garbage — it silently ACCEPTS "2026-06-24FORGED",
        # "2026-06-24 anything", and even an embedded-newline value, parsing
        # the leading date and ignoring the rest (verified on macOS). A
        # corrupt prices_as_of would therefore render a confident, precise
        # "23 days old" computed from a value nobody should trust. Only pure
        # garbage ("not-a-date") fails the parse and falls back to raw.
        # So: gate on the exact YYYY-MM-DD shape FIRST, and let anything else
        # print raw. Visibly-wrong beats plausibly-fabricated — the same rule
        # the USD guard follows.
        local age="$prices_as_of"
        case "$prices_as_of" in
          [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9])
            local then_epoch now_epoch
            then_epoch=$(date -j -f "%Y-%m-%d" "$prices_as_of" +%s 2>/dev/null)
            now_epoch=$(date +%s 2>/dev/null)
            if [ -n "$then_epoch" ] && [ -n "$now_epoch" ]; then
              local days=$(( (now_epoch - then_epoch) / 86400 ))
              age="prices as of $prices_as_of, $days days old"
              # Nag, never block: past the threshold, tell a human to go
              # check the pricing page. The claim is strictly about the
              # DATE being old, never that the rates are wrong — this
              # function has no way to know that.
              # A prices_as_of in the FUTURE yields negative days and renders
              # "-10 days old", which is nonsense to read and looks like a bug.
              # It is not a fabrication risk (no figure is invented and nothing
              # blocks), so it stays a display fix, not a guard: say plainly the
              # date is in the future and let the human judge it.
              if [ "$days" -lt 0 ]; then
                age="prices as of $prices_as_of, dated in the future (check the date)"
              elif [ "$days" -gt "$ALS_PRICE_STALE_DAYS" ]; then
                age="${age} (checks the date only, not the rates) — verify at claude.com/pricing and bump prices_as_of"
              fi
            fi
            ;;
        esac
        # Round for display only: the miner stores full float precision
        # ($64.45735454999999), which reads as noise in a one-line terminal
        # report. Rounding happens HERE, not at extraction, so `usd` stays raw
        # for the emptiness check above that drives the incomplete-data path.
        #
        # The numeric guard is NOT ceremony: `printf '%.2f'` does NOT fail on a
        # non-numeric input, it silently prints 0.00 (verified). Handing it a
        # garbage value would therefore FABRICATE "$0.00" — inventing a figure
        # from unusable data is the precise failure this reporter exists to
        # prevent (loop 0d3fb487 omitted its cost AND authored a false
        # explanation for the omission). So: only round something that is
        # actually a number; otherwise print the raw value and let it look
        # wrong, because visibly-wrong beats plausibly-fabricated.
        local usd_disp="$usd"
        case "$usd" in
          ''|*[!0-9.eE+-]*) ;;
          *) usd_disp=$(printf '%.2f' "$usd" 2>/dev/null) || usd_disp="$usd" ;;
        esac
        [ -n "$usd_disp" ] || usd_disp="$usd"
        msg="Loop cost: \$${usd_disp} (${tokens} tokens), ${age}"
      fi
      ;;
    *)
      msg="cost not recorded"
      ;;
  esac

  [ -n "$msg" ] || { als_log "hook=$hook session=$session cost_report=skipped_empty_msg"; return 0; }
  # Strip control characters before the message reaches a terminal. Every
  # value interpolated above is retro.json-derived, and jq --arg guarantees
  # only that the JSON stays well-formed — a live ESC (0x1B) survives JSON
  # decode intact and lands in whatever renders this (verified). Whether the
  # harness neutralises it is outside this repo and unknowable from here; a
  # hook has no business shipping raw control bytes to a terminal on that
  # assumption. Same posture als_log already takes on its own newlines.
  # Printable + literal space only. NOT [:space:] — that class includes VT
  # (0x0b) and FF (0x0c), which would survive the strip and reach the terminal
  # (verified: `printf 'A\013B\014C' | tr -c '[:print:][:space:]' ' '` passes
  # both through). FF clears the screen on many terminals. The follow-up tr
  # below only ever mapped \n\r\t, so those two had no second line of defence.
  # Found by the security pass on this PR; it is pre-existing (PR #204 wrote
  # it) rather than introduced here, but it is one character on a line this
  # change already touches, and "I shipped it last loop" is not a reason to
  # leave a control byte heading for a terminal.
  msg=$(printf '%s' "$msg" | tr -c '[:print:] ' ' ' | tr '\n\r\t' '   ')
  # Log the outcome CLASS, never the message body: the body interpolates
  # retro.json-derived values, and als_log's sanitisation is a backstop, not a
  # reason to widen what reaches the log. The class is what a post-hoc audit
  # actually needs — "did the human get a cost line, and if not, why".
  local outcome="reported"
  case "$msg" in
    "cost unavailable"*) outcome="miner_failed_open" ;;
    "cost not recorded"*) outcome="cost_absent" ;;
    "cost recorded but incomplete"*) outcome="cost_incomplete" ;;
  esac
  als_log "hook=$hook session=$session cost_report=$outcome"
  jq -n --arg m "$msg" '{systemMessage: $m}' 2>/dev/null
  return 0
}
