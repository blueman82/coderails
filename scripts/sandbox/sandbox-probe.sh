#!/bin/bash
# First-class negative control: proves a probe run discriminates the SANDBOX,
# not merely the filesystem (evals E1/E3 in
# docs/coderails/specs/sandbox-workers-spec.md).
#
# Usage: sandbox-probe.sh <worktree>
#
# Writes then deletes <worktree>/.sandbox-probe (must succeed — inside the
# allowlist). Then attempts $HOME/.sandbox-escape-probe and
# <primary-repo-parent>/escape-probe (both must fail — outside the
# allowlist). rc 0 iff the inside write succeeded AND both outside attempts
# failed. rc 1 with a named reason on any other combination. rc 2 with
# "not sandboxed?" when run BARE (outside srt), i.e. when an outside write
# unexpectedly succeeds — the meaningful case only exists under the sandbox.
#
# NOT a hook guard — this is a probe script, so it fails fast and loudly.
set -euo pipefail

die() { printf 'sandbox-probe: %s\n' "$1" >&2; exit 1; }
not_sandboxed() { printf 'sandbox-probe: %s (not sandboxed?)\n' "$1" >&2; exit 2; }

[ "$#" -eq 1 ] || die "expected 1 arg (worktree), got $#: usage: sandbox-probe.sh <worktree>"

worktree="$1"
[ -d "$worktree" ] || die "worktree is not an existing directory: $worktree"

primary_git=$(git -C "$worktree" rev-parse --path-format=absolute --git-common-dir 2>&1) \
  || die "worktree is not inside a git repo (git-common-dir resolution failed for $worktree): $primary_git"
primary_repo="$(dirname "$primary_git")"
primary_parent="$(dirname "$primary_repo")"

inside_target="$worktree/.sandbox-probe"
home_target="$HOME/.sandbox-escape-probe"
parent_target="$primary_parent/escape-probe"

# ─── Inside write: must succeed ─────────────────────────────────────────────
if ! printf 'probe\n' > "$inside_target" 2>/dev/null; then
  die "inside write to $inside_target failed — worktree should be allowlisted"
fi
rm -f "$inside_target"

# ─── Outside writes: must fail ──────────────────────────────────────────────
home_escaped=0
if printf 'probe\n' > "$home_target" 2>/dev/null; then
  home_escaped=1
  rm -f "$home_target"
fi

parent_escaped=0
if printf 'probe\n' > "$parent_target" 2>/dev/null; then
  parent_escaped=1
  rm -f "$parent_target"
fi

if [ "$home_escaped" -eq 1 ] || [ "$parent_escaped" -eq 1 ]; then
  reason=""
  [ "$home_escaped" -eq 1 ] && reason="write to $home_target succeeded"
  [ "$parent_escaped" -eq 1 ] && reason="${reason:+$reason; }write to $parent_target succeeded"
  not_sandboxed "$reason"
fi

exit 0
