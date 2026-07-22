#!/bin/bash
# Stop hook — BLOCK (exit 2) when a session looks like an unregistered
# agentic loop: dispatch-heavy (>=4 distinct Agent-dispatch turns) with no
# progress.json and no agentic-loop Skill invocation anywhere in the
# transcript. This is the proxy for "orchestrator forgot to register" (the
# 2026-07-06 incident's actual failure mode).
#
# WHY THIS BLOCKS (changed 2026-07-21 from nudge to block). This hook spent
# its first life as an advisory nudge delivered via additionalContext. On
# 2026-07-21 it fired at a live orchestrator session, which read the advice
# and carried on: it then dispatched three concurrent agents into ONE shared
# checkout with an auto-commit hook running, they interleaved edits across
# three branches, the session's own branch moved twice unattended, and a
# moved file was misdiagnosed as a deletion because no one could attribute
# changes to an author. Hours were lost. That is the empirical case against
# advisory output: additionalContext is text the model reads and weighs,
# exit 2 is the harness refusing to end the turn. Only the second changes
# behaviour. Owner directive, verbatim: "nothing should warn, you always
# ignore warnings."
#
# Sibling to loop_state_guard.sh/loop_stall_guard.sh. Those guards answer "is
# a REGISTERED loop's progress.json present and healthy"; this one answers
# "does this UNREGISTERED session look like a loop that should have
# registered". loop_state_guard's first gate (als_gate_require_active_loop)
# exits allow on exactly the case this hook catches (no Skill invocation =>
# not its problem), which is the gap this hook fills.
#
# Gate order (top to bottom, cheapest first):
#   skip  — no transcript                                     -> allow, silent
#   skip  — jq missing / total-loss transcript parse          -> allow, silent
#   skip  — dispatch_turns < 4 (below threshold)              -> allow, silent
#   skip  — progress.json present at the resolved path        -> allow, silent
#   skip  — agentic-loop Skill invocation found in transcript -> allow, silent
#   BLOCK — none of the above skip conditions hold            -> exit 2
#
# Delivery: message on STDERR with exit 2, the delivery shape for a blocking
# Stop hook (mirrors loop_stall_guard.sh's block_missing_declaration — not an
# invented shape). The old additionalContext-on-stdout path is gone: it is the
# mechanism that failed.
#
# DEADLOCK-FREEDOM — the genuine hard problem, and why this is not one.
# A block whose only escape is an assertion the model types would be a
# self-attestation loophole; a block with NO escape would deadlock a genuine
# one-off sequence of independent dispatches (this repo already shipped one
# deadlock of that shape — the tier-gate required-status deadlock). This
# guard takes the third option: the block is ALWAYS CLEARABLE BY COMPLYING,
# and complying is doing the real thing, not describing it.
#
# Two clears, both always available, neither assertable:
#   1. Write the progress.json stub at the path
#      hooks/scripts/lib/agentic_loop_path.sh resolves. Seconds of work. A
#      BARE stub (no Skill invocation) clears THIS guard and — verified
#      empirically — leaves loop_state_guard.sh and loop_stall_guard.sh both
#      at invocations=0/blocked=0, so it does NOT cascade into a second block
#      or drag a genuine one-off into loop-completion ceremony. This is the
#      right escape for a real one-off.
#   2. Invoke the agentic-loop Skill. This DOES activate loop_stall_guard's
#      completion discipline — the right outcome for an actual loop.
# There is no state in which the block fires and the model cannot clear it,
# so this is not a deadlock. It is a cost: a genuine one-off pays a few
# seconds of stub-writing. That cost is trivially below the hours the
# unregistered dispatch storm cost on 2026-07-21.
#
# WHY IT IS NOT A SELF-ATTESTATION LOOPHOLE. Registration is not a flag the
# model sets to exempt itself. It is the same tracked state a real loop
# creates, at a path the model cannot choose (agentic_loop_path.sh is the
# sole path authority, keyed on repo + session_id — a model cannot reproduce
# it by reasoning), read back by that same authority. There is deliberately
# NO justification field, NO "this is a one-off" declaration, and NO env/flag
# escape anywhere in this hook — the previous version's honest "no action is
# needed" sentence is deleted, because under a block that sentence would be
# the loophole. Compare the documented self-declared-tier bypass in this
# repo's memory: the defect there was that the gated party supplied the
# evidence. Here the evidence is a file at an address the gate computes.
# HONEST BOUNDARY: a model that wanted to could write a stub it never intends
# to maintain. That is accepted, per this repo's gate_threat_model_fork
# posture (accept-ceiling absent a concrete threat) — the failure mode this
# guard targets is FORGETTING, not malice, and an un-fakeable stub would only
# risk reintroducing the deadlock.
#
# THRESHOLD: raised 3 -> 4 distinct dispatch turns with the nudge->block
# change. Rationale, argued rather than assumed: under a nudge, a false
# positive cost one ignorable line of text, so 3 was cheap; under a block it
# costs a forced stub write, so the bar should sit above the common benign
# shape (a handful of genuinely independent one-shot dispatches — e.g. three
# parallel read-only Explore agents). 4+ SEQUENTIAL dispatch turns is much
# more loop-shaped than one-off-shaped. Note a parallel fan-out of N agents
# in ONE turn still counts 1 (shared message.id), so the threshold only
# counts turns that actually recur. This number is a judgment call and the
# guard's safety does NOT rest on it — it rests on the block being cheap to
# clear by complying. Tune it freely; do not add an escape hatch instead.
#
# YAGNI cuts (deliberate, do not add): no subagent_type/description
# classification of dispatches; no dispatch-review-cycle state machine; no
# once-per-session suppression (DELETED with the nudge — see the block site);
# no changes to lib/loop_state_common.sh.

. "$(dirname "${BASH_SOURCE[0]}")/lib/loop_state_common.sh"

# Count DISTINCT message.id values that carry an Agent tool_use anywhere in
# that message's content array. Structured jq match, never a text grep.
# Parallel fan-outs (N Agent calls in one assistant turn) share one
# message.id -> counts as 1. Sequential loop-style dispatches (one Agent call
# per turn, across turns) get distinct message.ids -> counts as N. Tool name
# is "Agent", never "Task", in this harness.
# (A null/missing message.id on multiple dispatch turns would collapse them
# to one via `unique` — not observed in real transcripts, defense-in-depth only.)
# Pure: prints an integer on stdout, no exit calls. Sets global
# ULG_PARSE_REASON to "jq_missing", "jq_parse_error", or "" (empty) — but
# "" now covers TWO cases, not one: a genuinely quiet transcript (0 real
# dispatches) AND a BENIGN PARTIAL SKIP (some lines malformed, but at least
# one line parsed) — a partial skip is not a failure, so the recovered count
# is valid and must be allowed through unattributed, same as a clean parse.
#
# The non-empty reason cases ALSO echo the reason token on stderr, mirroring
# als_count_invocations (lib/loop_state_common.sh). Reason: the hook body
# below invokes this function via command substitution
# (dispatch_turns=$(ulg_count_dispatch_turns ...)), which runs the function
# in a SUBSHELL — a plain global assignment inside that subshell never
# reaches the parent shell. Direct/sourced callers (9 existing unit tests)
# still read the global directly and are unaffected; the hook body instead
# captures stderr to a scratch file to recover the reason across the
# subshell boundary. stdout stays a bare integer either way.
#
# Two-stage tolerant parse (mirrors als_count_invocations in
# lib/loop_state_common.sh): stage 1 (`jq -R 'fromjson? // empty'`) parses
# one line at a time and drops any line that isn't valid JSON, instead of
# `jq -s` aborting the WHOLE parse on a single bad line; stage 2 (`jq -s`)
# aggregates only the lines stage 1 successfully parsed.
#
# ULG_PARSE_REASON is set to "jq_parse_error" (a non-empty, TOTAL-LOSS
# reason) ONLY when every line is malformed (stage 1 recovers nothing from a
# non-empty file) or stage 1 itself dies — that is the case a caller must
# treat as "count is not trustworthy, suppress the nudge." A benign partial
# skip (parsed > 0) is NOT that case: ULG_PARSE_REASON stays empty and the
# recovered count is used as-is.
ulg_count_dispatch_turns() {
  local transcript="$1"
  ULG_PARSE_REASON=""
  [ -n "$transcript" ] && [ -f "$transcript" ] || { printf '0'; return; }
  command -v jq >/dev/null 2>&1 || { ULG_PARSE_REASON="jq_missing"; echo "jq_missing" >&2; printf '0'; return; }
  local total tolerant tolerant_rc
  total=$(grep -c '[^[:space:]]' "$transcript" 2>/dev/null); [ -z "$total" ] && total=0
  tolerant=$(jq -R 'fromjson? // empty' "$transcript" 2>/dev/null); tolerant_rc=$?
  if [ "$tolerant_rc" -ne 0 ]; then
    ULG_PARSE_REASON="jq_parse_error"
    echo "jq_parse_error" >&2
    printf '0'
    return
  fi
  local n
  n=0
  if [ -n "$tolerant" ]; then
    n=$(printf '%s' "$tolerant" | jq -s -r '
      [ .[]?
        | select(.type == "assistant")
        | select(.message.content[]? | select(.type == "tool_use" and .name == "Agent"))
        | .message.id ]
      | unique
      | length
    ' 2>/dev/null)
  fi
  case "$n" in (''|*[!0-9]*) n=0;; esac
  if [ "$n" -eq 0 ] && [ "$total" -gt 0 ] && [ -z "$tolerant" ]; then
    ULG_PARSE_REASON="jq_parse_error"
    echo "jq_parse_error" >&2
  fi
  printf '%s' "$n"
}

# Prints 1 if a progress.json exists at the path agentic_loop_path.sh resolves
# for this cwd/session_id, else 0. Resolves via als_resolve_path (the sole
# path authority, shared with loop_state_guard.sh) — never recomputes the
# path independently.
ulg_has_progress_file() {
  local cwd="$1" session_id="$2" path
  path=$(als_resolve_path "$cwd" "$session_id")
  if [ -n "$path" ] && [ -f "$path" ]; then printf '1'; else printf '0'; fi
}

# Prints 1 if the transcript contains an agentic-loop Skill tool_use (scoped
# coderails:agentic-loop or bare agentic-loop), else 0. Delegates to
# als_count_invocations (already sourced from lib/loop_state_common.sh) rather
# than reimplementing its jq match — single source of truth for what counts
# as a loop-registering Skill invocation. Uses the one-shot count, not
# als_stable_invocations' flush-race retry: a false negative here just means
# the nudge re-fires at the next Stop, so the extra latency of retrying isn't
# worth it for a non-blocking nudge (unlike loop_state_guard's blocking gate,
# which needs the stable count to avoid blocking on a still-flushing write).
# als_count_invocations signals a jq-failure reason on stderr (see its own
# comment) for als_stable_invocations to pick up and log — this one-shot
# caller deliberately does not read or log that reason (matching its prior,
# pre-hardening silent-on-parse-failure behavior), so stderr is discarded here
# rather than left to leak to the hook's own stderr.
ulg_has_skill_invocation() {
  local transcript="$1" n
  n=$(als_count_invocations "$transcript" 2>/dev/null)
  [ -z "$n" ] && n=0
  if [ "$n" -gt 0 ]; then printf '1'; else printf '0'; fi
}

# Main body only runs when this script is executed directly (hooks.json
# invokes it as a command), not when sourced — lets tests source the file to
# call the three pure functions above in isolation, with no stdin read or
# gate exit triggered as a side effect of sourcing.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  # No stop_hook_active gate here — a DELIBERATE divergence from
  # loop_state_guard.sh/loop_stall_guard.sh, not an oversight, and no longer
  # justified by "this hook never blocks" (it does now).
  # als_gate_stop_loop exits 0 whenever stop_hook_active is true, which makes
  # those siblings block-once-then-allow-on-the-retry. That is precisely the
  # "blocks once, then goes quiet" behaviour this hook must NOT have: the
  # unregistered state persists until the model registers, so the block must
  # persist with it. Adopting als_gate_stop_loop here would silently rebuild
  # the nudge-once suppression that was just deleted.
  # This does not risk an unbreakable stop-loop, because the block is always
  # clearable by complying (see the DEADLOCK-FREEDOM block in the header):
  # every re-fire is one tool call away from being cleared, and that pressure
  # is the intended design, not a defect.
  IFS= read -r -d '' -t 5 input || true
  transcript=$(echo "$input" | jq -r '.transcript_path // empty' 2>/dev/null) || {
    als_log "hook=unregistered_loop_guard blocked=0 reason=payload_parse_error"
    exit 0
  }
  session_id=$(als_sanitise_session_id "$(echo "$input" | jq -r '.session_id // "?"' 2>/dev/null)")
  cwd=$(echo "$input" | jq -r '.cwd // empty' 2>/dev/null)
  [ -z "$cwd" ] && cwd="$PWD"  # Falls back to $PWD when .cwd is absent.

  [ -n "$transcript" ] && [ -f "$transcript" ] || {
    als_log "hook=unregistered_loop_guard session=$session_id blocked=0 reason=no_transcript"
    exit 0
  }

  # Command substitution below runs ulg_count_dispatch_turns in a SUBSHELL, so
  # its global ULG_PARSE_REASON assignment cannot reach this parent shell —
  # capture the reason it also emits on stderr instead, mirroring how
  # als_stable_invocations (lib/loop_state_common.sh) recovers als_count_invocations'
  # stderr-signalled reason across the same kind of subshell boundary.
  ulg_err_file=$(mktemp 2>/dev/null) || ulg_err_file=""
  if [ -n "$ulg_err_file" ]; then
    dispatch_turns=$(ulg_count_dispatch_turns "$transcript" 2>"$ulg_err_file")
    # Reading the WHOLE file as one reason is safe only because
    # ulg_count_dispatch_turns emits at most one single-line token on stderr
    # (jq_missing or jq_parse_error) and never a second line — unlike the
    # reference als_stable_invocations, which parses up to two stderr lines
    # (a skipped_malformed=N breadcrumb plus a reason tag) and so can't use
    # this shortcut. If a future edit adds a second stderr line here, this
    # plain `cat` will silently fold it into parse_reason.
    parse_reason=$(cat "$ulg_err_file" 2>/dev/null)
    rm -f "$ulg_err_file" 2>/dev/null
  else
    # mktemp itself is unavailable, so any real stderr reason (jq_missing /
    # jq_parse_error) is unrecoverable — this transcript's parse_reason falls
    # through to empty below exactly as before this fix (log-only change, NOT
    # a new exit/nudge path: below_threshold or the nudge itself still decide
    # the outcome same as always). Log a one-line breadcrumb so the degraded
    # mode is at least visible instead of silently indistinguishable from a
    # clean parse.
    dispatch_turns=$(ulg_count_dispatch_turns "$transcript" 2>/dev/null)
    parse_reason=""
    als_log "hook=unregistered_loop_guard session=$session_id reason=mktemp_unavailable attribution=lost"
  fi
  # FAIL-OPEN ON INFRASTRUCTURE, NEVER ON THE EVIDENCE. jq absent or a
  # total-loss transcript parse means the guard cannot see the evidence at
  # all — it must not block a session over its own broken tooling. A BENIGN
  # partial skip is NOT this case: ULG_PARSE_REASON stays empty there and the
  # recovered count is trusted and can block (asserted in the tests).
  if [ -n "$parse_reason" ]; then
    als_log "hook=unregistered_loop_guard session=$session_id blocked=0 reason=$parse_reason"
    exit 0
  fi
  # Threshold 4: see the THRESHOLD paragraph in the header for the argument.
  [ "$dispatch_turns" -ge 4 ] || {
    als_log "hook=unregistered_loop_guard session=$session_id dispatch_turns=$dispatch_turns blocked=0 reason=below_threshold"
    exit 0
  }

  # CLEAR 1: a progress.json exists at the resolved path. Real state at an
  # address the model cannot compute — not an assertion.
  has_progress=$(ulg_has_progress_file "$cwd" "$session_id")
  [ "$has_progress" = "0" ] || {
    als_log "hook=unregistered_loop_guard session=$session_id dispatch_turns=$dispatch_turns blocked=0 reason=registered"
    exit 0
  }

  # CLEAR 2: the agentic-loop Skill was actually invoked in this transcript.
  has_skill=$(ulg_has_skill_invocation "$transcript")
  [ "$has_skill" = "0" ] || {
    als_log "hook=unregistered_loop_guard session=$session_id dispatch_turns=$dispatch_turns blocked=0 reason=skill_invoked"
    exit 0
  }

  # BLOCK. The once-per-session suppression that used to sit here is DELETED
  # along with the nudge it served. A warning needed a ledger to stop
  # re-firing forever; a block must NOT have one — it persists until the
  # model actually registers, which is the entire point. A guard that blocks
  # once and then goes quiet is the failure being fixed, not a refinement of
  # it. (Deleted with it: the BRE-escaping of session_id, which existed only
  # to make that log-grep ledger safe.)
  #
  # Resolve the concrete path so the message can name it verbatim. The model
  # must never compute this path itself (agentic_loop_path.sh is the sole
  # authority), and a message that made it guess would re-block a
  # complying session — the one way this could have deadlocked in practice.
  # Fail-soft: if resolution yields nothing, still block, but say so.
  resolved_path=$(als_resolve_path "$cwd" "$session_id")
  [ -n "$resolved_path" ] || resolved_path="(path resolution failed — run: bash hooks/scripts/lib/agentic_loop_path.sh)"

  als_log "hook=unregistered_loop_guard session=$session_id dispatch_turns=$dispatch_turns blocked=1"
  echo "[unregistered-loop-guard] BLOCKED. This session has dispatched $dispatch_turns separate Agent
turns with no agentic-loop registration (no progress.json, no agentic-loop Skill
invocation). Unregistered concurrent dispatch is what let three agents interleave
edits across one shared checkout on 2026-07-21 with no way to attribute changes.

Clear this by REGISTERING — do one of these two things. There is no third option,
and nothing you can write in a message will clear it.

  1. One-off dispatches (no loop discipline wanted): write the stub file at
     exactly this path (copy it verbatim, never recompute it):
       $resolved_path
     with:
       { \"schema_version\": 1, \"session_id\": \"$session_id\", \"status\": \"in-progress\", \"created\": \"<ISO8601>\" }
     This clears the block on its own and does NOT activate the loop
     completion guards.

  2. A real multi-step loop: invoke the coderails:agentic-loop Skill and
     follow its registration phase. This DOES activate loop discipline.

If you are mid-flight with concurrent agents in one checkout, register first,
then check whether those agents need isolating into separate worktrees." >&2
  exit 2
fi
