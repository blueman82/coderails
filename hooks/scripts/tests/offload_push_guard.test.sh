#!/bin/bash
# Behavioural test for offload_push_guard.sh — feeds synthetic Stop/SubagentStop
# payloads and asserts the nudge fires/stays silent per the spec's cases.
# Mirrors unregistered_loop_guard.test.sh conventions: all state under a temp
# dir, never the repo tree.
set -u
GUARD="$(cd "$(dirname "$0")/.." && pwd)/offload_push_guard.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_DISCIPLINE_LOG="$TMP/discipline.log"
fails=0

check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# --- Fixture builders ------------------------------------------------------

# A transcript whose last assistant text block is $1.
mk_transcript() {
  local text="$1"
  local out="$TMP/t_$RANDOM.jsonl"
  jq -cn --arg t "$text" '{"type":"assistant","message":{"id":"m1","content":[{"type":"text","text":$t}]}}' > "$out"
  printf '%s' "$out"
}

stop_payload() { # transcript_path session_id -> JSON
  printf '{"transcript_path":"%s","session_id":"%s","hook_event_name":"Stop"}' "$1" "$2"
}
subagent_payload() { # last_assistant_message session_id -> JSON
  jq -cn --arg t "$1" --arg s "$2" '{"hook_event_name":"SubagentStop","last_assistant_message":$t,"session_id":$s}'
}
run() { printf '%s' "$1" | bash "$GUARD" >/dev/null 2>&1; echo $?; }
run_stdout() { printf '%s' "$1" | bash "$GUARD" 2>/dev/null; }

nudged() { # payload -> "yes" or "no", based on non-empty additionalContext
  local out; out=$(run_stdout "$1")
  local ctx; ctx=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.additionalContext // empty' 2>/dev/null)
  if [ -n "$ctx" ]; then printf 'yes'; else printf 'no'; fi
}

# =====================================================================
# Scenario: offload push to main + "your own shell" -> NUDGE
# =====================================================================
: > "$CLAUDE_DISCIPLINE_LOG"
T=$(mk_transcript "Please run git push origin main yourself from your own shell.")
code=$(run "$(stop_payload "$T" sess-yourshell)")
check "offload+push exit 0" "0" "$code"
: > "$CLAUDE_DISCIPLINE_LOG"  # reset: the exit-code check above already consumed this session's one nudge
check "offload push + 'your own shell' -> nudges" "yes" "$(nudged "$(stop_payload "$T" sess-yourshell)")"

# =====================================================================
# Scenario: leading "! " run-it-yourself framing -> NUDGE
# =====================================================================
: > "$CLAUDE_DISCIPLINE_LOG"
T=$(mk_transcript "I cannot push directly, so run this yourself: ! git -C /some/path push origin main")
code=$(run "$(stop_payload "$T" sess-bang)")
check "bang-prefix exit 0" "0" "$code"
: > "$CLAUDE_DISCIPLINE_LOG"  # reset: the exit-code check above already consumed this session's one nudge
check "'! git -C path push origin main' + run-it-yourself -> nudges" "yes" "$(nudged "$(stop_payload "$T" sess-bang)")"

# =====================================================================
# Scenario: agent describes doing the push itself -> NO nudge
# =====================================================================
: > "$CLAUDE_DISCIPLINE_LOG"
T=$(mk_transcript "I pushed to origin main and opened the PR.")
code=$(run "$(stop_payload "$T" sess-didit)")
check "agent-did-it exit 0" "0" "$code"
check "agent did the push itself -> no nudge" "no" "$(nudged "$(stop_payload "$T" sess-didit)")"

# =====================================================================
# Scenario: sanctioned slash-command suggestion -> NO nudge
# =====================================================================
: > "$CLAUDE_DISCIPLINE_LOG"
T=$(mk_transcript "Run /coderails:push yourself when you're ready to open the PR.")
code=$(run "$(stop_payload "$T" sess-slash)")
check "slash-command exit 0" "0" "$code"
check "'/coderails:push' suggestion -> no nudge (no push token)" "no" "$(nudged "$(stop_payload "$T" sess-slash)")"

# =====================================================================
# Scenario: push to a feature branch, offload framing -> NO nudge
# =====================================================================
: > "$CLAUDE_DISCIPLINE_LOG"
T=$(mk_transcript "Run this yourself from your own shell: git push origin hooks/offload-guard")
code=$(run "$(stop_payload "$T" sess-featbranch)")
check "feature-branch exit 0" "0" "$code"
check "feature-branch push -> no nudge" "no" "$(nudged "$(stop_payload "$T" sess-featbranch)")"

# =====================================================================
# Scenario: no push token at all -> NO nudge
# =====================================================================
: > "$CLAUDE_DISCIPLINE_LOG"
T=$(mk_transcript "You'll need to run this yourself from your own shell to finish up.")
code=$(run "$(stop_payload "$T" sess-nopush)")
check "no-push-token exit 0" "0" "$code"
check "offload cue but no push token -> no nudge" "no" "$(nudged "$(stop_payload "$T" sess-nopush)")"

# =====================================================================
# Scenario: second Stop same session after a nudge -> NO nudge (once-per-session)
# =====================================================================
: > "$CLAUDE_DISCIPLINE_LOG"
T=$(mk_transcript "Run git push origin main yourself from your own shell.")
out1=$(nudged "$(stop_payload "$T" sess-repeat)")
check "repeat-session first Stop -> nudges" "yes" "$out1"
out2=$(nudged "$(stop_payload "$T" sess-repeat)")
check "repeat-session second Stop -> suppressed" "no" "$out2"

# =====================================================================
# Scenario: SubagentStop reads last_assistant_message
# =====================================================================
: > "$CLAUDE_DISCIPLINE_LOG"
payload=$(subagent_payload "Please run git push origin main yourself from your own shell." sess-subagent)
code=$(printf '%s' "$payload" | bash "$GUARD" >/dev/null 2>&1; echo $?)
check "SubagentStop exit 0" "0" "$code"
: > "$CLAUDE_DISCIPLINE_LOG"  # reset: the exit-code check above already consumed this session's one nudge
out=$(printf '%s' "$payload" | bash "$GUARD" 2>/dev/null)
ctx=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.additionalContext // empty' 2>/dev/null)
[ -n "$ctx" ] && check "SubagentStop nudges from last_assistant_message" "ok" "ok" \
                || check "SubagentStop nudges from last_assistant_message" "ok" "FAIL: empty"

# =====================================================================
# Additional negative controls
# =====================================================================

# No transcript / missing file -> silent, exit 0.
: > "$CLAUDE_DISCIPLINE_LOG"
code=$(run '{"transcript_path":"/does/not/exist.jsonl","session_id":"sess-missing","hook_event_name":"Stop"}')
out=$(run_stdout '{"transcript_path":"/does/not/exist.jsonl","session_id":"sess-missing","hook_event_name":"Stop"}')
check "missing transcript -> exit 0" "0" "$code"
check "missing transcript -> silent" "" "$out"

# Empty final text -> silent, exit 0.
: > "$CLAUDE_DISCIPLINE_LOG"
empty_t=$(mk_transcript "")
code=$(run "$(stop_payload "$empty_t" sess-empty)")
out=$(run_stdout "$(stop_payload "$empty_t" sess-empty)")
check "empty text -> exit 0" "0" "$code"
check "empty text -> silent" "" "$out"

# Different sessions independent: session A nudged must not suppress session B.
: > "$CLAUDE_DISCIPLINE_LOG"
T=$(mk_transcript "Run git push origin main yourself from your own shell.")
run "$(stop_payload "$T" sess-multi-a)" >/dev/null
out_b=$(nudged "$(stop_payload "$T" sess-multi-b)")
check "distinct session not suppressed by prior nudge" "yes" "$out_b"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
