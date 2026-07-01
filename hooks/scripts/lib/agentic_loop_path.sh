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
# Usage: agentic_loop_path.sh [cwd]   (cwd defaults to $PWD)
# Path:  <base>/<slug>/progress.json
#   base = $CLAUDE_AGENTIC_LOOP_DIR (override for tests) or $HOME/.claude/agentic-loop
#   slug = cwd with every "/" replaced by "-" (mirrors Claude Code's own project-dir
#          convention, e.g. /Users/x/y -> -Users-x-y); deterministic, tool-free,
#          and debuggable (you can read which project a file belongs to).
#
# Single-loop-per-directory invariant: this path is keyed on cwd only, not session,
# so two concurrent agentic-loop sessions in the same directory will race for
# ownership of the same progress.json (last-writer-wins). Isolate concurrent loops
# via separate git worktrees (coderails:using-git-worktrees) — this script does not
# lock.

cwd="${1:-$PWD}"
base="${CLAUDE_AGENTIC_LOOP_DIR:-$HOME/.claude/agentic-loop}"
slug=$(printf '%s' "$cwd" | sed 's#/#-#g')
printf '%s/%s/progress.json\n' "$base" "$slug"
