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

  # ─── Escape guard, BEHAVIOURAL (not a shape check) ─────────────────────────
  # The most safety-critical property in this feature, and until now it was
  # asserted only by jq-index'ing two strings out of denyWrite — a check that
  # stays green even if srt's denyWrite-over-allowWrite precedence silently
  # breaks, which is the exact regression this feature exists to prevent.
  #
  # The property: %%PRIMARY_GIT%% MUST be in allowWrite (a linked worktree's
  # objects/refs live in the primary .git — omit it and every commit fails), so
  # the ONLY thing stopping a worker from planting <primary>/.git/hooks/pre-commit
  # (which then executes UNSANDBOXED on the next git op) is denyWrite precedence.
  # Assert the DENIAL, and assert it by ground truth (no file on disk), not by
  # rc or stderr text alone.
  hook_target="$PRIMARY_GIT/hooks/escape-probe-behavioural"
  cfg_before=$(shasum -a 256 "$PRIMARY_GIT/config" 2>/dev/null | cut -d' ' -f1)

  rc=0
  out=$(cd "$WORKTREE" && npx --yes "@anthropic-ai/sandbox-runtime@$SRT_VERSION" \
    --settings "$SETTINGS" \
    bash -c "echo '#!/bin/sh' > '$hook_target'" 2>&1) || rc=$?
  check "escape guard: write to PRIMARY .git/hooks is DENIED" "0" \
    "$([ -e "$hook_target" ] && echo 1 || echo 0)"
  check_contains "escape guard: .git/hooks denial names the reason" "not permitted" "$out"

  rc=0
  out=$(cd "$WORKTREE" && npx --yes "@anthropic-ai/sandbox-runtime@$SRT_VERSION" \
    --settings "$SETTINGS" \
    bash -c "echo '[evil]' >> '$PRIMARY_GIT/config'" 2>&1) || rc=$?
  cfg_after=$(shasum -a 256 "$PRIMARY_GIT/config" 2>/dev/null | cut -d' ' -f1)
  check "escape guard: write to PRIMARY .git/config is DENIED" "$cfg_before" "$cfg_after"
  check_contains "escape guard: .git/config denial names the reason" "not permitted" "$out"

  # CONTROL — the guard must not be vacuous. A settings file that denied ALL
  # .git writes would pass both assertions above while breaking the feature
  # entirely (no worker could ever commit). Assert the allow side still works.
  rc=0
  out=$(cd "$WORKTREE" && npx --yes "@anthropic-ai/sandbox-runtime@$SRT_VERSION" \
    --settings "$SETTINGS" \
    bash -c "git -c user.email=t@t -c user.name=t commit -q --allow-empty -m 'escape-guard control'" 2>&1) || rc=$?
  check "escape guard CONTROL: ordinary commit still succeeds (guard is not deny-all)" "0" "$rc"

  git -C "$REPO" worktree remove --force "$WORKTREE" >/dev/null 2>&1
fi

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
