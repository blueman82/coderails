#!/bin/bash
# Behavioural test for agent_model_routing_nudge.sh — feeds synthetic
# PreToolUse (Agent) payloads and asserts the advisory-only routing nudge:
#   mechanical/rote wording, no model override -> nudge toward haiku
#   complex/architectural wording, no model override -> nudge toward opus
#   model already set -> silent regardless of wording
#   neither/both signal families match -> silent
#   non-Agent tool -> silent, no-op
# Never denies — this hook has no permissionDecision path at all.
set -u
HOOK="$(cd "$(dirname "$0")/.." && pwd)/agent_model_routing_nudge.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_DISCIPLINE_LOG="$TMP/discipline.log"
fails=0

check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

run() { printf '%s' "$1" | bash "$HOOK" 2>/dev/null; }
run_rc() { printf '%s' "$1" | bash "$HOOK" >/dev/null 2>&1; echo $?; }

agent_payload() { # description prompt [model] -> Agent PreToolUse json
  local desc="$1" prompt="$2" model="${3:-}"
  if [ -n "$model" ]; then
    jq -n --arg d "$desc" --arg p "$prompt" --arg m "$model" \
      '{"hook_event_name":"PreToolUse","session_id":"s1","tool_name":"Agent","tool_input":{"description":$d,"prompt":$p,"subagent_type":"general-purpose","model":$m}}'
  else
    jq -n --arg d "$desc" --arg p "$prompt" \
      '{"hook_event_name":"PreToolUse","session_id":"s1","tool_name":"Agent","tool_input":{"description":$d,"prompt":$p,"subagent_type":"general-purpose"}}'
  fi
}

suggestion_of() { printf '%s' "$1" | jq -r '.hookSpecificOutput.additionalContext // empty' | grep -oE 'model: \\"[a-z]+\\"' | grep -oE '[a-z]+"?$' | tr -d '"'; }

# =====================================================================
# Scenario: mechanical/rote wording, no model -> nudge haiku
# =====================================================================
out=$(run "$(agent_payload "Rename variables for clarity" "Rename all foo to bar in this boilerplate file")")
rc=$(run_rc "$(agent_payload "Rename variables for clarity" "Rename all foo to bar in this boilerplate file")")
ctx=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.additionalContext // empty')
check "mechanical task -> exit 0" "0" "$rc"
check "mechanical task -> nudges (non-empty)" "yes" "$([ -n "$ctx" ] && echo yes || echo no)"
check "mechanical task -> suggests haiku" "yes" "$(printf '%s' "$ctx" | grep -q 'haiku' && echo yes || echo no)"

# =====================================================================
# Scenario: complex/architectural wording, no model -> nudge opus
# =====================================================================
out=$(run "$(agent_payload "Design new auth architecture" "Redesign the authentication subsystem architecture")")
ctx=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.additionalContext // empty')
check "architectural task -> nudges (non-empty)" "yes" "$([ -n "$ctx" ] && echo yes || echo no)"
check "architectural task -> suggests opus" "yes" "$(printf '%s' "$ctx" | grep -q 'opus' && echo yes || echo no)"

# =====================================================================
# Scenario: model already specified -> silent regardless of wording
# =====================================================================
out=$(run "$(agent_payload "Rename variables" "Rename foo to bar" "haiku")")
check "model already set (mechanical wording) -> silent" "" "$out"
out=$(run "$(agent_payload "Design architecture" "Redesign the architecture" "opus")")
check "model already set (architectural wording) -> silent" "" "$out"

# =====================================================================
# Scenario: neutral wording (neither signal family) -> silent
# =====================================================================
out=$(run "$(agent_payload "Fix the failing test" "Investigate and fix the failing test in auth.test.ts")")
check "neutral wording -> silent" "" "$out"

# =====================================================================
# Scenario: both signal families present -> ambiguous, silent
# =====================================================================
out=$(run "$(agent_payload "Redesign and rename" "Redesign the architecture and rename the boilerplate variables")")
check "both mechanical+architectural signals -> silent (ambiguous)" "" "$out"

# =====================================================================
# Scenario: non-Agent tool -> silent, no-op
# =====================================================================
out=$(run '{"hook_event_name":"PreToolUse","session_id":"s1","tool_name":"Bash","tool_input":{"command":"echo hi"}}')
rc=$(run_rc '{"hook_event_name":"PreToolUse","session_id":"s1","tool_name":"Bash","tool_input":{"command":"echo hi"}}')
check "non-Agent tool -> exit 0" "0" "$rc"
check "non-Agent tool -> silent" "" "$out"

# =====================================================================
# Scenario: never denies (no permissionDecision key in any output)
# =====================================================================
out=$(run "$(agent_payload "Rename variables" "Rename all foo to bar")")
deny=$(printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecision // empty')
check "mechanical nudge never carries permissionDecision" "" "$deny"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
