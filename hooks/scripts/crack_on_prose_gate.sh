#!/bin/bash
# Stop-event half of the crack-on envelope: while this session's
# crack_on_active flag is stamped (see crack_on_gate.sh), a final assistant
# message that hands a QUESTION back to the user in PROSE is blocked (exit 2),
# closing the evasion where the model asks in plain text instead of calling
# the (already-denied) AskUserQuestion tool. Sibling to crack_on_gate.sh, not
# an extension of it — that hook stays two-event and dependency-free; this one
# is a discipline Stop hook in the check_confidence_labels/check_verify_loop
# family (sources lib/discipline_common.sh, blocks via exit 2 + stderr).
#
# Classifier — deterministic two-tier heuristic, NOT an LLM judge. A judge
# was considered and rejected for a Stop hook: seconds of latency on every
# in-envelope turn end, a network/API dependency inside the hook sandbox,
# nondeterminism that can't be locked in a fixture test, and a new failure
# mode (judge outage) that would have to fail one way or the other anyway.
# The heuristic's known miss-cases are bounded and documented below instead.
#   preprocess — drop fenced code blocks (``` toggle), inline backtick spans,
#     and blockquote lines (quoted material is not the model asking).
#   tier 1 (positional) — the last content line of the prose body (the text
#     before a trailing "## Did Not Verify" section) OR of the whole message
#     ends with "?" (trailing quotes/brackets/markdown stripped first). A
#     question nothing follows is a question awaiting an answer; the
#     self-answered rhetorical form ("Should I use X? No — because ...")
#     carries its answer after the "?" and does not match.
#   tier 1b (positional) — a whole-line first-person-modal question
#     ("Should I ...?", "Shall we ...?") within the last 3 content lines of
#     the prose body — catches the ask when a structural trailer (DNV
#     section, LOOP-STOP line) follows it.
#   tier 2 (phrase) — high-precision second-person request phrases anywhere
#     in the prose ("do you want", "let me know which", "would you prefer",
#     "awaiting your", ...) — question mark or not. These are addressed TO
#     the user by construction, so position doesn't matter.
#
# Failure direction: biased toward BLOCKING (fail-closed on discipline, like
# the sibling Stop hooks). A false positive costs one forced rewrite of the
# turn's ending into a declarative report; a false negative silently parks a
# crack-on envelope on a question nobody will answer — the exact failure the
# envelope exists to prevent. Infrastructure failures (no transcript, no
# session_id, unwritable counter) stand aside / fail open with a log line,
# matching crack_on_gate.sh's stand-aside philosophy.
#
# Termination (no infinite block loop): a per-session counter file
# (<flag dir>/prose_question_blocks) is reset on the FIRST Stop attempt of
# each turn (stop_hook_active=false) and caps this hook's blocks at
# CLAUDE_CRACK_ON_PROSE_MAX_BLOCKS (default 3) per turn; at the cap the stop
# is allowed and logged capped=1. The release valve is deliberate — a model
# that rephrases the same question N times has defeated the heuristic, and
# an unbounded loop would be strictly worse. If the counter cannot be
# WRITTEN, the hook fails open (allow + err log) rather than risk an
# uncounted infinite block cycle. stop_hook_active is NOT used as an
# unconditional allow (unlike the sibling hooks): a rephrased question on
# the continuation turn must still be caught, so the counter, not the flag,
# is the terminator.
#
# Agentic-loop hard-stops: untouched. A well-formed stopping turn ends with
# its declarative `LOOP-STOP: <category> — <reason>` line (the skill's
# ending-line contract), which no tier matches. This gate never prevents
# stopping-with-a-report — it prevents stopping-with-a-question, and the cap
# guarantees any stop eventually lands even if mis-worded.
#
# Stop-only, never SubagentStop: a subagent's final message addresses the
# ORCHESTRATOR, not the human — a worker asking its parent a question is not
# a breach of the envelope (the parent answers it autonomously), and the
# SubagentStop payload carries the parent's session_id, so registering there
# would spuriously police worker reports against the parent's flag.
#
# HONEST CEILING (do not oversell): this is mechanical pattern-matching over
# prose, and intent has no regex. What it cannot catch:
#   - a declarative handoff with no interrogative marker at all ("Two options
#     exist: A and B." / "Blocked pending your decision on X." phrased novelly),
#   - novel second-person phrasings outside the tier-2 list,
#   - a question inside plain double quotes (only backtick/fence/blockquote
#     quoting is stripped — a terminal quoted question is a known FP, and a
#     mid-message one a known miss),
#   - anything after the per-turn cap: a model that keeps asking N+1 times
#     gets its question through, audited (capped=1) but not blocked.
# The guarantee is "the cheap, common ask-in-prose evasions are mechanically
# caught, every catch and every cap is logged" — not "asking is impossible".
# Same class of ceiling as destructive_bash_gate's pre-expansion regex.

LOG_FILE="${CLAUDE_DISCIPLINE_LOG:-$HOME/.claude/discipline.log}"
TAIL_LINES="${CLAUDE_HOOK_TAIL_LINES:-300}"
MAX_ATTEMPTS="${CLAUDE_HOOK_MAX_ATTEMPTS:-5}"
SLEEP_S="${CLAUDE_HOOK_SLEEP_S:-0.3}"
MAX_BLOCKS="${CLAUDE_CRACK_ON_PROSE_MAX_BLOCKS:-3}"

. "$(dirname "$0")/lib/discipline_common.sh"

log_line() { printf '%s %s\n' "$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S%z)" "$1" >> "$LOG_FILE" 2>/dev/null; }

IFS= read -r -d '' -t 5 input || true

event=$(echo "$input" | jq -r '.hook_event_name // empty')
[ "$event" = "Stop" ] || exit 0

session_id=$(echo "$input" | jq -r '.session_id // empty')
[ -z "$session_id" ] && exit 0

# Headless-run exemption (same rationale and shape as the sibling Stop hooks):
# a dashboard-spawned `claude -p` run has no interactive human, and a repair
# turn would displace the run's answer.
if [ "${CODERAILS_HEADLESS_RUN:-}" = "1" ]; then
  log_line "hook=crack_on_prose_gate skipped=headless"
  exit 0
fi

# flag_path: session-only crack-on flag location. Sanitisation kept in
# lockstep with the same two-line transform in crack_on_gate.sh (and
# lib/agentic_loop_path.sh / loop_state_common.sh) — intentionally duplicated
# so this hook and the stamping hook can never resolve different paths.
flag_path() {
  local base sid
  base="${CLAUDE_AGENTIC_LOOP_DIR:-$HOME/.claude/agentic-loop}"
  sid=$(printf '%s' "$session_id" | tr '/' '_')
  sid=$(printf '%s' "$sid" | sed 's/\.\.//g')
  [ -z "$sid" ] && return 1
  printf '%s/%s/crack_on_active' "$base" "$sid"
}

flag=$(flag_path) || exit 0
[ -n "$flag" ] && [ -f "$flag" ] || exit 0

count_file="${flag%/*}/prose_question_blocks"

transcript=$(echo "$input" | jq -r '.transcript_path // empty')
if [ -z "$transcript" ] || [ ! -f "$transcript" ]; then
  exit 0
fi

# Turn-scoped block counter. stop_hook_active=false means this is the first
# Stop attempt of the turn (no stop hook has blocked yet), so the counter is
# reset; stop_hook_active=true means we (or a sibling hook) already blocked
# this turn, so the recorded count carries forward. This is the terminator —
# see the Termination note in the header.
stop_hook_active=$(echo "$input" | jq -r '.stop_hook_active // false' 2>/dev/null)
if [ "$stop_hook_active" != "true" ]; then
  rm -f "$count_file" 2>/dev/null
  count=0
else
  count=$(cat "$count_file" 2>/dev/null)
  case "$count" in ''|*[!0-9]*) count=0 ;; esac
fi

text=$(dc_stable_text "$transcript" "$TAIL_LINES" "$MAX_ATTEMPTS" "$SLEEP_S")
if [ -z "$text" ]; then
  log_line "hook=crack_on_prose_gate event=Stop session=$session_id skipped=empty_text blocked=0"
  exit 0
fi

# ── Preprocess: remove content the model is quoting, not saying ────────────
stripped=$(printf '%s\n' "$text" | awk '
  /^[[:space:]]*```/ { in_fence = !in_fence; next }
  in_fence { next }
  /^[[:space:]]*>/ { next }
  { print }
' | sed 's/`[^`]*`//g')

# Prose body = everything before a trailing "## Did Not Verify" section (the
# repo convention appends DNV + the LOOP-STOP line after the real prose
# ending, so the ask-position is the body's last line, not the message's).
body=$(printf '%s\n' "$stripped" | awk '/^## *(Did Not Verify|Not Verified)/ { exit } { print }')

body_last=$(printf '%s\n' "$body" | grep -vE '^[[:space:]]*$' | tail -n 1)
whole_last=$(printf '%s\n' "$stripped" | grep -vE '^[[:space:]]*$' | tail -n 1)
body_tail3=$(printf '%s\n' "$body" | grep -vE '^[[:space:]]*$' | tail -n 3)

# ends_with_q <line>: true if the line ends with "?" once trailing closing
# decorations (quotes, brackets, markdown emphasis, whitespace) are stripped.
ends_with_q() {
  printf '%s' "$1" | sed "s/[]\")'*_[:space:]]*$//" | grep -q '?$'
}

matched=""
snippet=""

# tier 1 — terminal question mark on the body's or the message's last line.
if ends_with_q "$body_last"; then
  matched="tier1_body_last"; snippet="$body_last"
elif ends_with_q "$whole_last"; then
  matched="tier1_whole_last"; snippet="$whole_last"
fi

# tier 1b — whole-line first-person-modal question in the body's last 3
# content lines (catches the ask when a structural trailer follows it).
# Line-terminal "?" required, so "Should I use X? No — ..." never matches.
if [ -z "$matched" ]; then
  p1='(^|[^[:alnum:]])(should|shall|could|can|may|must|do|would) (i|we) [^?]*\?[[:space:]]*$'
  hit=$(printf '%s\n' "$body_tail3" | grep -iE "$p1" | head -n 1)
  if [ -n "$hit" ]; then
    matched="tier1b_modal"; snippet="$hit"
  fi
fi

# tier 2 — second-person request phrases, message-wide. Each is addressed to
# the user by construction; position doesn't matter.
if [ -z "$matched" ]; then
  ask_patterns=(
    'do you (want|need|prefer)'
    'want me to [^?]*\?'
    'would you (like|prefer|rather)'
    'let me know (if|which|what|whether|when|how|your)'
    'tell me (which|what|whether|if)'
    'which (do|would|should) you'
    '(awaiting|waiting (on|for)) your'
    'please (confirm|advise|clarify|choose|pick|decide)'
    '(give|need|await|wait for) (me )?the (go-ahead|green light)'
    'say the word'
    'how would you like'
    'what would you (like|prefer)'
    "if you('d)? (want|like|prefer), (i|we) can"
    '(is|would) that (be )?(ok|okay|alright|acceptable)'
    'your (call|choice|preference)[[:punct:][:space:]]*$'
  )
  for p in "${ask_patterns[@]}"; do
    hit=$(printf '%s\n' "$stripped" | grep -iE "$p" | head -n 1)
    if [ -n "$hit" ]; then
      matched="tier2"; snippet="$hit"
      break
    fi
  done
fi

if [ -z "$matched" ]; then
  log_line "hook=crack_on_prose_gate event=Stop session=$session_id text_len=${#text} matched=0 blocked=0"
  exit 0
fi

# ── Question detected while crack-on active ────────────────────────────────
if [ "$count" -ge "$MAX_BLOCKS" ]; then
  # Release valve: cap reached this turn — allow the stop, loudly audited.
  log_line "hook=crack_on_prose_gate event=Stop session=$session_id text_len=${#text} matched=1 tier=$matched count=$count capped=1 blocked=0"
  exit 0
fi

newcount=$((count + 1))
if ! printf '%s' "$newcount" > "$count_file" 2>/dev/null; then
  # Cannot record the block — an uncounted block could cycle forever, so
  # fail open (allow) with an audit line instead. Same stand-aside direction
  # as crack_on_gate.sh's unkeyable-stamp case.
  log_line "hook=crack_on_prose_gate event=Stop session=$session_id matched=1 tier=$matched blocked=0 err=count_write_failed"
  exit 0
fi

log_line "hook=crack_on_prose_gate event=Stop session=$session_id text_len=${#text} matched=1 tier=$matched count=$newcount blocked=1"
echo "[crack-on-block] A crack-on envelope is active in this session and your final message hands a question back to the user (matched: \"${snippet}\"). Asking the human is suppressed in BOTH forms — the AskUserQuestion tool and prose. Make the call yourself inside the envelope scope and keep working, or end with a declarative report / LOOP-STOP declaration stating what you did, what you decided, and what remains. Do not end the turn with a question, and do not rephrase this one." >&2
exit 2
