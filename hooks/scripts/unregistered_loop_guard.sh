#!/bin/bash
# Stop hook — NUDGE (never block) when a session looks like an unregistered
# agentic loop: dispatch-heavy (>=3 distinct Agent-dispatch turns) with no
# progress.json and no agentic-loop Skill invocation anywhere in the
# transcript. This is the proxy for "orchestrator forgot to register" (the
# 2026-07-06 incident's actual failure mode).
#
# Sibling to loop_state_guard.sh/loop_stall_guard.sh, NOT an extension of
# either: those guards answer "is a REGISTERED loop's progress.json present
# and healthy" (ground-truth, ownership-checked, ok to block on). This hook
# answers a different question — "does this UNREGISTERED session look like a
# loop that should have registered" (heuristic, no ground truth) — so it
# nudges instead of blocking. loop_state_guard's first gate
# (als_gate_require_active_loop) exits allow on exactly the case this hook
# exists to catch (no Skill invocation => not its problem), which is the gap
# this hook fills.
#
# Gate order (top to bottom, cheapest first):
#   skip  — no transcript                                    -> allow, silent
#   skip  — dispatch_turns < 3 (below threshold)              -> allow, silent
#   skip  — progress.json present at the resolved path        -> allow, silent
#   skip  — agentic-loop Skill invocation found in transcript  -> allow, silent
#   NUDGE — none of the above skip conditions hold             -> allow, nudge
#
# Delivery: additionalContext on stdout, exit 0 (model-visible per hooks
# docs). Never stderr-on-exit-0 (invisible to the model, debug-log-only) —
# that delivery mechanism is reserved for block-precedent siblings' exit-2
# messages, a genuinely different mechanism for a genuinely different signal.
#
# YAGNI cuts (deliberate, do not add): no subagent_type/description
# classification of dispatches; no dispatch-review-cycle state machine; no
# block-once marker (a nudge needs no loop guard — it can fire every Stop
# until the condition clears); no changes to lib/loop_state_common.sh.

. "$(dirname "${BASH_SOURCE[0]}")/lib/loop_state_common.sh"

# Count DISTINCT message.id values that carry an Agent tool_use anywhere in
# that message's content array. Structured jq match, never a text grep.
# Parallel fan-outs (N Agent calls in one assistant turn) share one
# message.id -> counts as 1. Sequential loop-style dispatches (one Agent call
# per turn, across turns) get distinct message.ids -> counts as N. Tool name
# is "Agent", never "Task", in this harness.
# (A null/missing message.id on multiple dispatch turns would collapse them
# to one via `unique` — not observed in real transcripts, defense-in-depth only.)
# Pure: prints an integer, no side effects, no exit calls. Sets global
# ULG_PARSE_REASON to "jq_missing" or "jq_parse_error" if jq itself failed
# (jq not on PATH, or malformed/corrupt transcript JSON), else "" — so callers
# can log a distinct reason from a genuine zero. `jq -s` aborts the whole
# parse on a single bad line, which would otherwise be silently
# indistinguishable from "0 dispatches, quiet session."
ulg_count_dispatch_turns() {
  local transcript="$1"
  ULG_PARSE_REASON=""
  [ -n "$transcript" ] && [ -f "$transcript" ] || { printf '0'; return; }
  command -v jq >/dev/null 2>&1 || { ULG_PARSE_REASON="jq_missing"; printf '0'; return; }
  local n
  n=$(jq -s -r '
    [ .[]?
      | select(.type == "assistant")
      | select(.message.content[]? | select(.type == "tool_use" and .name == "Agent"))
      | .message.id ]
    | unique
    | length
  ' "$transcript" 2>/dev/null) || ULG_PARSE_REASON="jq_parse_error"
  case "$n" in (''|*[!0-9]*) n=0;; esac
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
ulg_has_skill_invocation() {
  local transcript="$1" n
  n=$(als_count_invocations "$transcript")
  [ -z "$n" ] && n=0
  if [ "$n" -gt 0 ]; then printf '1'; else printf '0'; fi
}

# Main body only runs when this script is executed directly (hooks.json
# invokes it as a command), not when sourced — lets tests source the file to
# call the three pure functions above in isolation, with no stdin read or
# gate exit triggered as a side effect of sourcing.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  # No stop_hook_active gate here (unlike loop_state_guard.sh): this hook
  # always exits 0 and never blocks, so it can't drive a stop-loop.
  IFS= read -r -d '' -t 5 input || true
  transcript=$(echo "$input" | jq -r '.transcript_path // empty' 2>/dev/null) || {
    als_log "hook=unregistered_loop_guard nudged=0 reason=payload_parse_error"
    exit 0
  }
  session_id=$(als_sanitise_session_id "$(echo "$input" | jq -r '.session_id // "?"' 2>/dev/null)")
  cwd=$(echo "$input" | jq -r '.cwd // empty' 2>/dev/null)

  [ -n "$transcript" ] && [ -f "$transcript" ] || {
    als_log "hook=unregistered_loop_guard session=$session_id nudged=0 reason=no_transcript"
    exit 0
  }

  dispatch_turns=$(ulg_count_dispatch_turns "$transcript")
  if [ -n "$ULG_PARSE_REASON" ]; then
    als_log "hook=unregistered_loop_guard session=$session_id nudged=0 reason=$ULG_PARSE_REASON"
    exit 0
  fi
  [ "$dispatch_turns" -ge 3 ] || {
    als_log "hook=unregistered_loop_guard session=$session_id dispatch_turns=$dispatch_turns nudged=0 reason=below_threshold"
    exit 0
  }

  has_progress=$(ulg_has_progress_file "$cwd" "$session_id")
  [ "$has_progress" = "0" ] || {
    als_log "hook=unregistered_loop_guard session=$session_id dispatch_turns=$dispatch_turns nudged=0 reason=registered"
    exit 0
  }

  has_skill=$(ulg_has_skill_invocation "$transcript")
  [ "$has_skill" = "0" ] || {
    als_log "hook=unregistered_loop_guard session=$session_id dispatch_turns=$dispatch_turns nudged=0 reason=skill_invoked"
    exit 0
  }

  als_log "hook=unregistered_loop_guard session=$session_id dispatch_turns=$dispatch_turns nudged=1"
  jq -n --arg ctx "[unregistered-loop-guard] This session has dispatched $dispatch_turns+ separate Agent turns with no agentic-loop registration detected (no progress.json, no agentic-loop Skill invocation). If this is a multi-step loop, register it now: invoke coderails:agentic-loop and create the progress.json stub at the path hooks/scripts/lib/agentic_loop_path.sh resolves for this session, so the loop-state guards can track it. If this is genuinely a one-off sequence of independent dispatches, no action is needed." \
    '{"hookSpecificOutput":{"hookEventName":"Stop","additionalContext":$ctx}}'
  exit 0
fi
