#!/bin/bash
# Stop hook — NUDGE (never block) when the final assistant message tells the
# USER to run a `git push` to a repo's main/master from their own shell,
# instead of clearing enforce_pr_workflow.sh's push gate itself.
#
# The problem this fixes: enforce_pr_workflow.sh blocks `git push` to
# main/master unless /pr-review-toolkit:review-pr ran in THIS session's
# transcript. That block is self-clearable — run review-pr in-session, then
# push — but an agent can mis-handle it by telling the user "run this push
# yourself from your own shell," offloading work it could do itself. A
# PreToolUse hook can't block a bad SENTENCE (only a bad tool call), so this
# is a Stop-time nudge instead: it fires only when the final text both names
# a push to main/master AND carries an offload-to-user cue near it.
#
# Sibling to unregistered_loop_guard.sh (same "nudge, never block" contract,
# same nudge-once-per-session ledger idiom) but answers an unrelated
# question — this hook has nothing to do with agentic-loop registration.
#
# Gate order (top to bottom, cheapest first):
#   skip  — no transcript / no last_assistant_message      -> allow, silent
#   skip  — final text empty                               -> allow, silent
#   skip  — no push-to-main/master token in the text        -> allow, silent
#   skip  — no offload-to-user cue in the text               -> allow, silent
#   skip  — already nudged this session                     -> allow, silent
#   NUDGE — both the push token and the offload cue matched  -> allow, nudge
#
# Delivery: additionalContext on stdout, exit 0 (model-visible per hooks
# docs). Never stderr-on-exit-0 — that mechanism is reserved for
# block-precedent hooks' exit-2 messages.
#
# YAGNI cuts (deliberate, do not add): no blocking, no config flag, no
# classification of push types beyond the push+offload match, no new lib
# functions — reuses als_log/als_sanitise_session_id (lib/loop_state_common.sh)
# and dc_stable_text (lib/discipline_common.sh), the same helpers
# check_confidence_labels.sh and unregistered_loop_guard.sh already use.

. "$(dirname "${BASH_SOURCE[0]}")/lib/loop_state_common.sh"
. "$(dirname "${BASH_SOURCE[0]}")/lib/discipline_common.sh"

TAIL_LINES="${CLAUDE_HOOK_TAIL_LINES:-200}"
MAX_ATTEMPTS="${CLAUDE_HOOK_MAX_ATTEMPTS:-5}"
SLEEP_S="${CLAUDE_HOOK_SLEEP_S:-0.3}"

# A `git ... push ... origin main|master` (or bare main/master) token,
# case-insensitive. Allows an optional leading `! ` (run-it-yourself prefix)
# and an optional `-C <path>` between `git` and `push`. Does not anchor to
# line start, so it matches inside a longer sentence or a fenced command.
OPG_PUSH_RE='git( +-C +[^ ]+)? +push\b.*\b(origin +)?(main|master)\b'

# Offload-to-user cues: a leading `! ` run-it-yourself prefix, or phrases
# asking the user to run the command themselves. Case-insensitive.
OPG_OFFLOAD_RE='(^|[^[:alnum:]])! +git|your own shell|run (it|this) yourself|from your shell|you run|needs your shell|un-?gated shell'

# Prints 1 if $1 contains BOTH the push token and an offload cue, else 0.
opg_is_offload_push() {
  local text="$1"
  if printf '%s' "$text" | grep -qiE "$OPG_PUSH_RE" && printf '%s' "$text" | grep -qiE "$OPG_OFFLOAD_RE"; then
    printf '1'
  else
    printf '0'
  fi
}

if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
  IFS= read -r -d '' -t 5 input || true
  hook_event=$(echo "$input" | jq -r '.hook_event_name // "Stop"' 2>/dev/null)
  session_id=$(als_sanitise_session_id "$(echo "$input" | jq -r '.session_id // "?"' 2>/dev/null)")

  if [ "$hook_event" = "SubagentStop" ]; then
    text=$(echo "$input" | jq -r '.last_assistant_message // ""' 2>/dev/null)
  else
    transcript=$(echo "$input" | jq -r '.transcript_path // empty' 2>/dev/null)
    if [ -z "$transcript" ] || [ ! -f "$transcript" ]; then
      als_log "hook=offload_push_guard session=$session_id nudged=0 reason=no_transcript"
      exit 0
    fi
    text=$(dc_stable_text "$transcript" "$TAIL_LINES" "$MAX_ATTEMPTS" "$SLEEP_S")
  fi

  if [ -z "$text" ]; then
    als_log "hook=offload_push_guard session=$session_id nudged=0 reason=empty_text"
    exit 0
  fi

  if [ "$(opg_is_offload_push "$text")" = "0" ]; then
    als_log "hook=offload_push_guard session=$session_id nudged=0 reason=no_match"
    exit 0
  fi

  # Nudge-once-per-session: same ledger idiom as unregistered_loop_guard.sh —
  # grep the discipline log for a prior nudge for THIS session_id, BRE-escaped
  # (session_id can contain literal BRE metacharacters that als_sanitise_session_id
  # does not strip, e.g. ".").
  esc_sid=$(printf '%s' "$session_id" | sed 's/[.[\*^$\\]/\\&/g')
  if grep -q "hook=offload_push_guard .*session=$esc_sid .*nudged=1" "$LOG_FILE" 2>/dev/null; then
    als_log "hook=offload_push_guard session=$session_id nudged=0 reason=already_nudged_this_session"
    exit 0
  fi

  als_log "hook=offload_push_guard session=$session_id nudged=1"
  jq -n --arg ctx "[offload-guard] Your final message asks the user to run a git push that this session can clear itself. The enforce_pr_workflow push gate is satisfied by running /pr-review-toolkit:review-pr in THIS session (a worker's review-pr does not count — the gate scans this session's own transcript). Run a genuine review-pr here, then \`git push\` yourself. Do not offload it to the user's shell or add a settings.json bypass." \
    '{"hookSpecificOutput":{"hookEventName":"Stop","additionalContext":$ctx}}'
  exit 0
fi
