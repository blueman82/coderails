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
#   slug = cwd with every "/" replaced by "-" (mirrors Claude Code's own project-dir
#          convention, e.g. /Users/x/y -> -Users-x-y); deterministic, tool-free,
#          and debuggable (you can read which project a file belongs to).
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
base="${CLAUDE_AGENTIC_LOOP_DIR:-$HOME/.claude/agentic-loop}"
slug=$(printf '%s' "$cwd" | sed 's#/#-#g')
printf '%s/%s/%s/progress.json\n' "$base" "$slug" "$session_id"
