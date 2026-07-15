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
  tolerant=$(jq -R 'fromjson? // empty' "$1" 2>/dev/null); tolerant_rc=$?
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
# (schema_version 1 or 2) beside progress.json - Phase 13's write contract.
# Presence + parse only (honest boundary: provenance/content fidelity is
# not checkable here, same limit as every other guard). Fail-open when jq
# is absent, matching bump_loop_stop_count.
# Accepted schema_version set is 1 and 2 (bumped for the loop-cost-miner
# addition to the retro shape) - a version outside that set, or a
# non-numeric/absent value, is still wrong_schema and blocks.
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
  elif ! jq -e '(.schema_version // 0) as $v | ($v == 1 or $v == 2)' "$retro" >/dev/null 2>&1; then ALS_RETRO_STATE="wrong_schema"
  fi
  if [ "$ALS_RETRO_STATE" != "present" ]; then
    als_log "hook=$hook session=$session retro=$ALS_RETRO_STATE blocked=1"
    echo "[loop-stall-guard] LOOP-STOP: complete declared but retro.json is $ALS_RETRO_STATE.
Phase 13 teardown writes retro.json (schema_version 1 or 2) beside progress.json
BEFORE declaring complete: assemble the retro (see agentic-loop SKILL.md
Phase 13), write it, then re-declare complete." >&2
    exit 2
  fi
}
