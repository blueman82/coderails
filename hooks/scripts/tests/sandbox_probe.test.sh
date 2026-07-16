#!/bin/bash
# Behavioural tests for scripts/sandbox/sandbox-probe.sh — the first-class
# negative control that proves a probe run actually discriminates the
# SANDBOX, not merely the filesystem (E3 in evals.json). Bare run (no srt
# wrapper) must exit 2; under the srt wrapper with Task 2's rendered settings
# it must exit 0. The sandbox-exec case is supported-platform-only (Darwin
# Seatbelt or Linux bubblewrap) and skips cleanly elsewhere.
set -u

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
PROBE="$REPO_ROOT/scripts/sandbox/sandbox-probe.sh"
RENDER_SETTINGS="$REPO_ROOT/scripts/sandbox/render-settings.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fails=0

check() { # desc expected actual
  if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected: %s\n  actual:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

check_contains() { # desc needle haystack
  if printf '%s' "$3" | grep -qF "$2"; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected to contain: %s\n  actual:              %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# Disposable git repo + worktree so the probe's primary-repo-parent target is real.
REPO="$TMP/repo"
mkdir -p "$REPO"
git -C "$REPO" init -q
git -C "$REPO" config user.email test@example.com
git -C "$REPO" config user.name test
git -C "$REPO" commit --allow-empty -q -m init

WORKTREE="$TMP/wt"
git -C "$REPO" worktree add -q "$WORKTREE" -b test-branch >/dev/null 2>&1

# ─── Bare run (no sandbox) → rc 2, "not sandboxed?" ─────────────────────────
rc=0; out=$("$PROBE" "$WORKTREE" 2>&1) || rc=$?
check "bare run -> rc 2 (not sandboxed)" "2" "$rc"
check_contains "bare run -> names 'not sandboxed?'" "not sandboxed?" "$out"

# Bare run must clean up any escape artifact it created on the real filesystem.
check "bare run -> no leftover \$HOME/.sandbox-escape-probe" "0" \
  "$([ -e "$HOME/.sandbox-escape-probe" ] && echo 1 || echo 0)"
check "bare run -> no leftover escape-probe next to primary repo" "0" \
  "$([ -e "$(dirname "$REPO")/escape-probe" ] && echo 1 || echo 0)"

# ─── Under the srt wrapper → rc 0 (supported-platform-only) ─────────────────
platform_supported=0
case "$(uname -s)" in
  Darwin|Linux) platform_supported=1 ;;
esac

if [ "$platform_supported" -ne 1 ]; then
  printf 'SKIP - sandboxed-run case: unsupported platform (%s)\n' "$(uname -s)"
else
  PRIMARY_GIT=$(git -C "$WORKTREE" rev-parse --path-format=absolute --git-common-dir)
  SETTINGS="$TMP/srt-settings.json"
  # Scratch must be NARROWER than $TMP (which holds the disposable repo/parent
  # target): passing $TMP itself as scratch would allowlist the very directory
  # the probe's outside-write is supposed to find denied. TMPDIR is overridden
  # to the same narrow scratch so %%TMPDIR%% doesn't re-widen the allowlist
  # back to the whole real $TMPDIR (which $TMP is a child of) — this mirrors
  # production, where the primary repo's parent sits outside every allowlisted
  # path, not inside it.
  SCRATCH="$TMP/scratch"
  mkdir -p "$SCRATCH"
  TMPDIR="$SCRATCH" "$RENDER_SETTINGS" "$WORKTREE" "$SCRATCH" "$PRIMARY_GIT" "$SETTINGS" >/dev/null

  SRT_VERSION="0.0.65"
  rc=0
  out=$(cd "$WORKTREE" && npx --yes "@anthropic-ai/sandbox-runtime@$SRT_VERSION" \
    --settings "$SETTINGS" \
    "$PROBE" "$WORKTREE" 2>&1) || rc=$?

  check "sandboxed run -> rc 0" "0" "$rc"

  git -C "$REPO" worktree remove --force "$WORKTREE" >/dev/null 2>&1
fi

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
