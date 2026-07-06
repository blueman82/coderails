#!/bin/bash
# Sole authority for the agentic-loop progress.json path.
#
# A model cannot reproduce a cwd-derived key, so it must NEVER compute this path.
# Both the loop_state_guard Stop hook (reader) and the orchestrator (writer, via a
# Bash call) call this script so the path is computed in exactly one place.
#
# Pure: prints the path, creates nothing. The writer (orchestrator's Write tool)
# creates the parent directory.
#
# Usage: agentic_loop_path.sh [cwd] [session_id]
#   cwd        defaults to $PWD
#   session_id defaults to $CLAUDE_CODE_SESSION_ID (set in every Claude Code Bash
#              tool call, so the orchestrator rarely needs to pass it explicitly).
#              Hook scripts receive session_id via the Stop-hook JSON payload
#              instead, and pass it explicitly.
# Path:  <base>/<slug>/<session_id>/progress.json
#   base = $CLAUDE_AGENTIC_LOOP_DIR (override for tests) or $HOME/.claude/agentic-loop
#   slug = when cwd is inside a git repo, `git -C "$cwd" rev-parse
#          --path-format=absolute --git-common-dir` (slugified the same way, "/" ->
#          "-") — keys the path to the REPO, not the raw cwd, so a worktree hop
#          (git worktree add) resolves to the SAME progress.json as its primary
#          checkout, since both share one --git-common-dir. Falls back to cwd with
#          every "/" replaced by "-" (today's plain transform, mirroring Claude
#          Code's own project-dir convention) when cwd is outside a repo, or on
#          ANY git failure (non-zero exit, empty output, git binary missing) — this
#          keying scheme supersedes PR #86's rejected cwd-keying-instability
#          concern (2026-07-01) now that mid-session EnterWorktree is a prescribed
#          part of the shared-checkout workflow; see PR body / SKILL.md for the
#          fuller rationale.
#
# Keying on session_id (stable across compaction/restart within one continuous
# conversation — Claude Code's own $CLAUDE_CODE_SESSION_ID and the Stop-hook
# session_id field agree for the life of a conversation) gives two concurrent
# agentic-loop sessions in the same directory independent progress.json files,
# while a single session's own file survives its own compaction/restart. See
# skills/agentic-loop/SKILL.md's "Context-window persistence" section.
#
# When no real session_id is available at all (arg 2 empty AND
# $CLAUDE_CODE_SESSION_ID unset), a FIXED fallback string would make every such
# call collide onto one shared path, defeating session-scoped isolation for the
# exact callers that need it most. So the fallback is generated fresh per
# invocation (PID + high-res timestamp) instead of a shared constant.

cwd="${1:-$PWD}"
session_id="${2:-${CLAUDE_CODE_SESSION_ID:-}}"
if [ -z "$session_id" ]; then
  session_id="unknown-$$-$(date +%s%N 2>/dev/null || date +%s)"
fi
# session_id is harness-owned (Stop payload / env), not attacker-controlled —
# this sanitisation is defence-in-depth against payload anomalies, not a
# security boundary. Replace (not fresh-fallback) so a malformed id doesn't
# silently orphan its real session: strip "/" (no extra path segment / no
# traversal into a sibling dir) and collapse ".." (no traversal upward).
session_id=$(printf '%s' "$session_id" | tr '/' '_')
session_id=$(printf '%s' "$session_id" | sed 's/\.\.//g')
base="${CLAUDE_AGENTIC_LOOP_DIR:-$HOME/.claude/agentic-loop}"
git_common_dir=$(command -v git >/dev/null 2>&1 && git -C "$cwd" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
if [ -n "$git_common_dir" ]; then
  slug=$(printf '%s' "$git_common_dir" | sed 's#/#-#g')
else
  slug=$(printf '%s' "$cwd" | sed 's#/#-#g')
fi
printf '%s/%s/%s/progress.json\n' "$base" "$slug" "$session_id"
