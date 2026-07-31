#!/bin/bash
# PreToolUse hook (Agent): advisory-only nudge when an Agent dispatch omits a
# `model` override for a task description that reads as mechanical/rote or as
# complex/architectural — never a hard deny (this is a suggestion about cost
# and depth of reasoning, not a correctness gate; a wrong role assignment
# doesn't break anything downstream, per AGENTS.md's "Model-role routing for
# spawned workers is advisory, not hook-enforced" ceiling note, which this
# hook is the first thing to actually act on).
#
# Reads .tool_input.description and .tool_input.prompt (both confirmed
# present on a live Agent tool_input payload; .model is confirmed absent when
# no override is given, present as a bare string e.g. "haiku" when one is).
# Keyword lists are deliberately small and literal — a false miss just means
# no nudge, which is the safe direction for advisory-only guidance.
#
#   mechanical/rote signal words -> nudge toward haiku
#   complex/architectural signal words -> nudge toward opus
#   both match, or neither match, or .model is already set -> silent
#
# Delivery: additionalContext on stdout, exit 0 (model-visible per hooks
# docs) — same idiom as unregistered_loop_guard.sh/offload_push_guard.sh.
# Never permissionDecision — this hook has no deny path at all.

IFS= read -r -d '' -t 5 input || true

tool_name=$(printf '%s' "$input" | jq -r '.tool_name // empty' 2>/dev/null)
[ "$tool_name" = "Agent" ] || exit 0

model=$(printf '%s' "$input" | jq -r '.tool_input.model // empty' 2>/dev/null)
[ -n "$model" ] && exit 0

text=$(printf '%s' "$input" | jq -r '((.tool_input.description // "") + " " + (.tool_input.prompt // "")) | ascii_downcase' 2>/dev/null)
[ -z "$text" ] && exit 0

mechanical_re='\b(rename|format|formatting|boilerplate|scaffold|reformat|relabel|find[[:space:]]*[/-]?replace)\b'
complex_re='\b(design|architecture|architectural|redesign|re-architect)\b'

is_mechanical=0
is_complex=0
printf '%s' "$text" | grep -qE "$mechanical_re" && is_mechanical=1
printf '%s' "$text" | grep -qE "$complex_re" && is_complex=1

LOG_FILE="${CLAUDE_DISCIPLINE_LOG:-$HOME/.claude/discipline.log}"
log_line() { printf '%s %s\n' "$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S%z)" "$1" >> "$LOG_FILE" 2>/dev/null; }

# Both or neither match -> ambiguous or no signal, stay silent.
if [ "$is_mechanical" -eq "$is_complex" ]; then
  log_line "hook=agent_model_routing_nudge nudged=0 reason=no_or_ambiguous_signal"
  exit 0
fi

if [ "$is_mechanical" -eq 1 ]; then
  suggestion="haiku"
  rationale="mechanical/rote-sounding task (rename/format/boilerplate-class wording) with no model override"
else
  suggestion="opus"
  rationale="complex/architectural-sounding task (design/architecture/redesign-class wording) with no model override"
fi

log_line "hook=agent_model_routing_nudge nudged=1 suggestion=$suggestion"
ctx="[agent-model-routing-nudge] This Agent dispatch looks like a $rationale. Defaulting to sonnet is fine, but consider adding model: \"$suggestion\" to the Agent call if that better matches the task's actual depth. Advisory only — this is a cost/latency suggestion (see AGENTS.md's model-role-routing ceiling note), not a correctness requirement."
jq -n --arg ctx "$ctx" '{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":$ctx}}'
exit 0
