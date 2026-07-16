#!/bin/bash
# Launch a headless `claude -p` worker wrapped by @anthropic-ai/sandbox-runtime
# (srt), version-pinned, so its filesystem writes are OS-contained outside its
# worktree/scratch/primary-.git/claude-home allowlist (see
# docs/coderails/specs/sandbox-workers-spec.md).
#
# Usage: spawn-sandboxed-worker.sh <worktree> <prompt_file> <model>
#
# NOT a hook guard — this is a spawn-path script, so it fails fast and loudly
# rather than failing open.
set -euo pipefail

# Pinned per docs/coderails/plans/sandbox-workers-plan.md: srt's config schema
# is beta and may change between versions. Bump deliberately, in its own PR —
# never floated.
SRT_VERSION="0.0.65"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RENDER_SETTINGS="$SCRIPT_DIR/render-settings.sh"

die() { printf 'spawn-sandboxed-worker: %s\n' "$1" >&2; exit 1; }

# ─── Preconditions ──────────────────────────────────────────────────────────
[ "$#" -eq 3 ] || die "expected 3 args (worktree prompt_file model), got $#: usage: spawn-sandboxed-worker.sh <worktree> <prompt_file> <model>"

worktree="$1"; prompt_file="$2"; model="$3"

[ -d "$worktree" ] || die "worktree is not an existing directory: $worktree"
[ -f "$prompt_file" ] || die "prompt_file is not an existing file: $prompt_file"
[ -f "$RENDER_SETTINGS" ] || die "render-settings.sh not found: $RENDER_SETTINGS"

# Resolves the PRIMARY repo's .git (not the worktree's own pointer file) —
# a linked worktree's object/ref writes land in the primary's
# .git/worktrees/<name> and shared object store.
primary_git=$(git -C "$worktree" rev-parse --path-format=absolute --git-common-dir 2>&1) \
  || die "worktree is not inside a git repo (git-common-dir resolution failed for $worktree): $primary_git"

command -v npx >/dev/null 2>&1 || die "npx not found on PATH (required to run srt)"
command -v gh >/dev/null 2>&1 || die "gh not found on PATH (required to obtain GH_TOKEN)"

# ─── Per-worker scratch ─────────────────────────────────────────────────────
# On macOS $TMPDIR is the per-user /var/folders/... dir, NOT /tmp — /tmp stays
# denied by the rendered settings, so scratch must land under $TMPDIR.
base_tmpdir="${TMPDIR:-/tmp}"
base_tmpdir="${base_tmpdir%/}"
scratch=$(mktemp -d "$base_tmpdir/sandbox-worker.XXXXXX") \
  || die "could not create scratch dir under $base_tmpdir"

settings_path="$scratch/srt-settings.json"
"$RENDER_SETTINGS" "$worktree" "$scratch" "$primary_git" "$settings_path" >/dev/null \
  || die "render-settings.sh failed for worktree=$worktree scratch=$scratch primary_git=$primary_git"

# XDG_CACHE_HOME redirected to scratch so claude -p's own cache need is met
# WITHOUT allowlisting ~/.cache (correction 3, verified live srt 0.0.65:
# without this the worker's claude process emits empty output and silently
# exits 0 — the directory must exist AND be writable before exec, or the
# same silent failure re-triggers).
xdg_cache_home="$scratch/xdg-cache"
mkdir -p "$xdg_cache_home" || die "could not create XDG_CACHE_HOME dir: $xdg_cache_home"

# GH_TOKEN obtained here, OUTSIDE the sandbox — the worker itself must never
# call `gh` (the Go/trustd TLS fork fails inside srt; in-worker GitHub calls
# go through curl instead, per the spec's decision rule).
gh_token=$(gh auth token 2>&1) || die "gh auth token failed: $gh_token"

log_file="$scratch/worker.log"

# cd into the worktree: srt's filesystem policy is evaluated against the
# process's actual paths, and the worker (and any relative-path behaviour in
# claude -p) must run with the worktree as cwd, not the orchestrator's cwd —
# which sits outside every allowlisted path and would EPERM on first write.
cd "$worktree" || die "could not cd into worktree: $worktree"

# The ambient environment is passed through as-is rather than reset with
# env -i: claude -p's auth needs more of it than just PATH/HOME (verified
# live — env -i PATH=... HOME=... alone yields "Not logged in", while the
# unstripped environment authenticates). GH_TOKEN and XDG_CACHE_HOME are
# layered on top; CODERAILS_HEADLESS_RUN is force-unset regardless of any
# inherited value, since a second set-site for it is a security finding
# (AGENTS.md). A subshell + `unset` is used instead of `env -u`, which is a
# GNU-only flag absent from macOS's BSD env.
export GH_TOKEN="$gh_token"
export XDG_CACHE_HOME="$xdg_cache_home"
unset CODERAILS_HEADLESS_RUN

set +e
npx --yes "@anthropic-ai/sandbox-runtime@$SRT_VERSION" \
  --settings "$settings_path" \
  claude -p "$(cat "$prompt_file")" --model "$model" \
  2>&1 | tee "$log_file"
rc="${PIPESTATUS[0]}"
set -e

exit "$rc"
