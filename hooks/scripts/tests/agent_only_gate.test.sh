#!/bin/bash
# Behavioural test for agent_only_gate.sh — feeds synthetic PreToolUse
# payloads and asserts the main-vs-subagent detection contract plus the
# nudge/enforce posture:
#   agent_id present (subagent)      -> always silent, exit 0
#   agent_id absent (top-level)      -> default mode nudges (additionalContext)
#   AGENT_ONLY_GATE_ENFORCE=1 + no carve-out -> hard deny
#   AGENT_ONLY_GATE_ENFORCE=1 + carve-out (gh/git/scripts/*.sh) -> nudge, not deny
set -u
GATE="$(cd "$(dirname "$0")/.." && pwd)/agent_only_gate.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_DISCIPLINE_LOG="$TMP/discipline.log"
fails=0

check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

run() { printf '%s' "$1" | bash "$GATE" 2>/dev/null; }
run_rc() { printf '%s' "$1" | bash "$GATE" >/dev/null 2>&1; echo $?; }

bash_payload() { # command -> top-level Bash PreToolUse json (no agent_id)
  jq -n --arg cmd "$1" '{"hook_event_name":"PreToolUse","session_id":"s1","cwd":"/x","tool_name":"Bash","tool_input":{"command":$cmd},"tool_use_id":"t1"}'
}
subagent_bash_payload() { # command -> subagent Bash PreToolUse json (agent_id present)
  jq -n --arg cmd "$1" '{"hook_event_name":"PreToolUse","session_id":"s1","cwd":"/x","agent_id":"abc123","agent_type":"general-purpose","tool_name":"Bash","tool_input":{"command":$cmd},"tool_use_id":"t2"}'
}

# =====================================================================
# Scenario: subagent call (agent_id present) -> always silent, exit 0,
# regardless of enforce mode.
# =====================================================================
unset AGENT_ONLY_GATE_ENFORCE
out=$(run "$(subagent_bash_payload "npm test")")
rc=$(run_rc "$(subagent_bash_payload "npm test")")
check "subagent call -> exit 0" "0" "$rc"
check "subagent call -> silent (no output)" "" "$out"

export AGENT_ONLY_GATE_ENFORCE=1
out=$(run "$(subagent_bash_payload "npm test")")
check "subagent call in enforce mode -> still silent" "" "$out"
unset AGENT_ONLY_GATE_ENFORCE

# =====================================================================
# Scenario: top-level call, default mode -> nudge (additionalContext), exit 0
# =====================================================================
out=$(run "$(bash_payload "npm test")")
rc=$(run_rc "$(bash_payload "npm test")")
check "top-level call default mode -> exit 0" "0" "$rc"
ctx=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.additionalContext // empty')
deny=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecision // empty')
check "top-level call default mode -> nudges (non-empty additionalContext)" "yes" "$([ -n "$ctx" ] && echo yes || echo no)"
check "top-level call default mode -> never denies" "" "$deny"

# =====================================================================
# Scenario: top-level call, enforce mode, non-carve-out command -> hard deny
# =====================================================================
export AGENT_ONLY_GATE_ENFORCE=1
out=$(run "$(bash_payload "npm test")")
rc=$(run_rc "$(bash_payload "npm test")")
deny=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecision // empty')
check "top-level non-carve-out, enforce mode -> exit 0 (deny via JSON, not exit 2)" "0" "$rc"
check "top-level non-carve-out, enforce mode -> permissionDecision=deny" "deny" "$deny"

# =====================================================================
# Scenario: top-level call, enforce mode, carve-out commands -> nudge, not deny
# =====================================================================
for cmd in "gh pr create --title x" "git push origin main" "scripts/merge.sh 123" "bash scripts/post_evals.sh validate-structure"; do
  out=$(run "$(bash_payload "$cmd")")
  deny=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecision // empty')
  check "carve-out '$cmd' in enforce mode -> not denied" "" "$deny"
done
unset AGENT_ONLY_GATE_ENFORCE

# =====================================================================
# Scenario: missing tool_name -> silent, exit 0 (malformed/empty payload)
# =====================================================================
out=$(run '{"hook_event_name":"PreToolUse"}')
rc=$(run_rc '{"hook_event_name":"PreToolUse"}')
check "missing tool_name -> exit 0" "0" "$rc"
check "missing tool_name -> silent" "" "$out"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
