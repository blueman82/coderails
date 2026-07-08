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
#          any git failure OR non-absolute output (non-zero exit, empty output,
#          git binary missing, or a pre-2.31 git that doesn't recognise
#          --path-format and echoes it back with a relative path on exit 0 — the
#          output is validated to actually be an absolute path before use) — this
#          keying scheme supersedes PR #86's rejected cwd-keying-instability
#          concern (2026-07-01) now that mid-session EnterWorktree is a prescribed
#          part of the shared-checkout workflow; see PR body / SKILL.md for the
#          fuller rationale.
#
# Resolution (which of the candidate paths is printed):
#   1. Compute the CANONICAL path from the slug above.
#   2. If a progress.json EXISTS at the canonical path -> print it.
#   3. Else PROBE <base>/*/<session_id>/progress.json — state that a PRIOR
#      version of THIS helper (or a mid-loop cwd/repo-ness drift) parked under a
#      DIFFERENT slug for the same session. session_id is unique per session, so
#      it is a sufficient key on its own. Existing matches are deduped by the
#      physical identity of their containing dir (the same file can appear under
#      several slugs via the orchestrator's workaround symlinks — realpath
#      collapses them); if DISTINCT real files somehow exist, the pick is
#      deterministic (lexicographically smallest path). Print the match.
#   4. Else (no state anywhere) -> print the canonical path, so a fresh loop
#      registers there.
# The probe is why session_id sanitisation (below) must run BEFORE the glob: the
# already-sanitised <session_id> segment cannot expand into a sibling/parent dir.
#
# Accepted limitation (design invariant, not a bug): this helper is stateless
# and re-derives the slug from the CURRENT repo state on every call. The
# session_id probe (step 3) now HEALS the common case of that slug changing
# mid-loop — a session that `git init`s an until-then-non-git cwd (or whose .git
# disappears) shifts to a new slug, but its already-written progress.json is
# still found under the old slug by session_id, so the loop's state no longer
# splits. The one residual gap: if NO progress.json has been written yet when
# the slug changes, there is nothing to probe for, and the fresh registration
# lands at the new canonical path (as it should). Rare and self-inflicted (a
# session altering its own repo state mid-loop before registering) — documented
# so it isn't mistaken for a fresh bug later.
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
# ACCEPTED TRADEOFF: this transform is lossy — e.g. "foo/bar" and "foo_bar"
# both sanitise to "foo_bar" — so two distinct raw ids can collide. Given
# session_id is harness-owned, this residual collision is accepted rather
# than adding a re-uniquifying suffix, which would defeat the "replace, don't
# orphan" goal by making a malformed id's sanitised form unpredictable/unstable
# across calls. Keep this transform in lockstep with the duplicate copy in
# als_sanitise_session_id (hooks/scripts/lib/loop_state_common.sh) — this file
# stays dependency-free (no `source` of that lib) by design, so the two-line
# transform is intentionally duplicated, not unified; update both on any change.
session_id=$(printf '%s' "$session_id" | tr '/' '_')
session_id=$(printf '%s' "$session_id" | sed 's/\.\.//g')
base="${CLAUDE_AGENTIC_LOOP_DIR:-$HOME/.claude/agentic-loop}"
git_common_dir=$(command -v git >/dev/null 2>&1 && git -C "$cwd" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
# A git older than 2.31 doesn't recognise --path-format and echoes it back
# verbatim alongside a RELATIVE .git path, exiting 0 (not a failure by exit
# code) — trusting any non-empty stdout would collapse every repo on such a
# host onto one garbage slug. Require the captured value to actually be an
# absolute path; anything else (garbage, relative, empty) falls through to
# the cwd-slug fallback below, same as an outright git failure.
case "$git_common_dir" in
  /*) ;;
  *) git_common_dir="" ;;
esac
if [ -n "$git_common_dir" ]; then
  slug=$(printf '%s' "$git_common_dir" | sed 's#/#-#g')
else
  slug=$(printf '%s' "$cwd" | sed 's#/#-#g')
fi
canonical="$base/$slug/$session_id/progress.json"

# If canonical state exists, use it — unchanged behaviour. Otherwise, probe for
# state a PRIOR helper version (or a mid-loop cwd drift) may have parked under a
# DIFFERENT slug for THIS session. session_id is unique per session, so
# <base>/*/<session_id>/progress.json is a sufficient key on its own. This heals
# the 2026-07-08 split-slug incident: a loop registered under the old raw-cwd
# slug but read back under the git-common-dir slug, blinding the Stop guards.
# The session_id sanitisation ABOVE is load-bearing here: it has already
# stripped "/" and collapsed "..", so the glob's <session_id> segment cannot
# expand into a sibling/parent directory. If canonical exists OR no state is
# found anywhere, print canonical (a fresh loop registers at the canonical path).
if [ -e "$canonical" ]; then
  printf '%s\n' "$canonical"
else
  # Collect existing matches under other slugs, deduped by PHYSICAL identity of
  # the containing dir (the orchestrator's live workaround symlinks the SAME
  # progress.json under multiple slugs — realpath collapses them to one). A
  # glob that matches nothing yields the literal pattern, which `[ -e ]` rejects.
  match=""
  seen=""
  for candidate in "$base"/*/"$session_id"/progress.json; do
    [ -e "$candidate" ] || continue
    real=$(cd "$(dirname "$candidate")" 2>/dev/null && pwd -P) || continue
    case "$seen" in
      *"|$real|"*) continue ;;
    esac
    seen="$seen|$real|"
    # Deterministic pick if multiple DISTINCT real files somehow exist: keep the
    # lexicographically smallest printable path (glob order is already sorted,
    # but choose explicitly so it does not depend on shell glob-sort locale).
    if [ -z "$match" ] || [ "$candidate" \< "$match" ]; then
      match="$candidate"
    fi
  done
  if [ -n "$match" ]; then
    printf '%s\n' "$match"
  else
    printf '%s\n' "$canonical"
  fi
fi
