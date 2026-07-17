#!/bin/bash
# Render the pinned srt settings template into a per-worker settings file.
#
# Usage: render-settings.sh <worktree> <scratch> <primary_git> <out_path>
#
# Substitutes %%WORKTREE%%, %%SCRATCH%%, %%PRIMARY_GIT%%, %%HOME%% and
# %%TMPDIR%%, strips the template's // comments (srt parses with JSON.parse,
# which rejects them) and validates the result with jq before writing it.
#
# NOT a hook guard — this is a spawn-path script, so it fails fast and loudly
# rather than failing open.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="$SCRIPT_DIR/srt-settings.json.template"

die() { printf 'render-settings: %s\n' "$1" >&2; exit 1; }

# ─── Preconditions ──────────────────────────────────────────────────────────
[ "$#" -eq 4 ] || die "expected 4 args (worktree scratch primary_git out_path), got $#"

worktree="$1"; scratch="$2"; primary_git="$3"; out_path="$4"

# Each of the three input paths must be an absolute, existing directory. Named
# per-argument so a failure says which one and why, not just "bad input".
check_dir() { # label path
  case "$2" in
    /*) ;;
    *) die "$1 must be an absolute path, got: $2" ;;
  esac
  [ -d "$2" ] || die "$1 is not an existing directory: $2"
}
check_dir "worktree" "$worktree"
check_dir "scratch" "$scratch"
check_dir "primary_git" "$primary_git"

[ -f "$TEMPLATE" ] || die "template not found: $TEMPLATE"
command -v jq >/dev/null 2>&1 || die "jq not found on PATH (required to validate rendered settings)"

# srt uses ripgrep for deny-path detection on macOS; without it the sandbox
# misbehaves at spawn rather than here, so fail now with the actionable hint.
if [ "$(uname -s)" = "Darwin" ]; then
  command -v rg >/dev/null 2>&1 || die "ripgrep (rg) not found — srt needs it on macOS for deny-path detection. Install: brew install ripgrep"
fi

: "${HOME:?render-settings: HOME must be set}"
# $TMPDIR is unset in some non-interactive contexts (cron, launchd); /tmp is the
# POSIX default and matches what those processes actually use.
tmpdir="${TMPDIR:-/tmp}"
# Trailing slash (macOS exports TMPDIR with one) would render a path srt
# compares literally against syscall paths that carry no trailing slash.
tmpdir="${tmpdir%/}"

# Claude Code keeps per-project state under /tmp/claude-<uid>/<slug-of-cwd>,
# where the slug is the worker's cwd with every '/' replaced by '-'. This path
# is NOT configurable by flag and sits OUTSIDE $TMPDIR (macOS resolves /tmp to
# /private/tmp, which is not the /var/folders/... TMPDIR), so it is not covered
# by the %%TMPDIR%% grant. Without it a sandboxed worker writes its first file
# fine and then dies at the next tool call with
# "EPERM: operation not permitted, mkdir '/private/tmp/claude-<uid>/<slug>'"
# — observed live in the E2 end-to-end probe. Grant ONLY this worker's own slug
# subdir, never the whole /tmp/claude-<uid> tree (that would hand every worker
# read/write over every other project's session state).
claude_state_root="/private/tmp/claude-$(id -u)"
claude_project_state="$claude_state_root/$(printf '%s' "$worktree" | sed 's|/|-|g')"
mkdir -p "$claude_project_state" || die "could not create claude project-state dir: $claude_project_state"

# ─── Render ─────────────────────────────────────────────────────────────────
# Comment-strip first, then substitute: a path could legitimately contain "//"
# (a doubled slash), and stripping afterwards could eat part of it.
#
# Substitute with jq, not sed. sed needs a delimiter, and EVERY delimiter is a
# legal filename character — `s|%%WORKTREE%%|$worktree|g` dies with "bad flag in
# substitute command" the moment a path contains `|` (reproduced: a worktree
# under a dir named `pipe|dir`). Picking a rarer delimiter only moves the bug.
# sed also cannot JSON-escape: a path containing `"` or a backslash would render
# structurally-invalid JSON, and one containing `"` sequences could in
# principle inject an allowlist entry. jq fixes both at once — it substitutes
# and emits each value as a correctly-escaped JSON string, so the path is data,
# never syntax. This is the same reasoning as the no-shell-injection rule one
# layer up: never build a structured format by string-splicing.
rendered=$(
  grep -v '^[[:space:]]*//' "$TEMPLATE" \
  | jq \
      --arg worktree "$worktree" \
      --arg scratch "$scratch" \
      --arg primary_git "$primary_git" \
      --arg home "$HOME" \
      --arg tmpdir "$tmpdir" \
      --arg claude_project_state "$claude_project_state" \
      '
      def subst:
        if type == "string" then
          gsub("%%WORKTREE%%"; $worktree)
          | gsub("%%SCRATCH%%"; $scratch)
          | gsub("%%PRIMARY_GIT%%"; $primary_git)
          | gsub("%%HOME%%"; $home)
          | gsub("%%TMPDIR%%"; $tmpdir)
          | gsub("%%CLAUDE_PROJECT_STATE%%"; $claude_project_state)
        elif type == "array" then map(subst)
        elif type == "object" then map_values(subst)
        else . end;
      subst
      ' 2>/dev/null
) || die "jq substitution failed — the template is not valid JSON once comments are stripped, or a path broke the render"

# No placeholder may survive: an unsubstituted %%…%% would reach srt as a
# literal path and silently widen or narrow the policy.
if printf '%s' "$rendered" | grep -q '%%'; then
  die "unsubstituted placeholder(s) remain: $(printf '%s' "$rendered" | grep -o '%%[A-Z_]*%%' | sort -u | tr '\n' ' ')"
fi

# Validate BEFORE writing, so a broken render never lands on disk as a
# plausible-looking settings file.
printf '%s\n' "$rendered" | jq . >/dev/null 2>&1 || die "rendered settings are not valid JSON (template or substitution is broken)"

printf '%s\n' "$rendered" > "$out_path" || die "could not write settings to: $out_path"
printf '%s\n' "$out_path"
