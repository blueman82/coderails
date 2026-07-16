#!/bin/bash
# Behavioural tests for scripts/sandbox/spawn-sandboxed-worker.sh — the
# headless sandboxed-worker launcher. Cases (a)/(b) are precondition checks
# that run everywhere (no srt exec). Cases (c)/(d) and the child-inheritance
# case (Task 5) exec the real srt sandbox with a stubbed `claude`, so they are
# supported-platform-only (Darwin Seatbelt or Linux bubblewrap) and skip
# cleanly elsewhere.
set -u

REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
SPAWN="$REPO_ROOT/scripts/sandbox/spawn-sandboxed-worker.sh"
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

# Preconditions (a)/(b) never fetch a token, so a dummy is safe and keeps
# these cases hermetic against whether `gh` is authenticated on the runner.
GH_TOKEN="${GH_TOKEN:-dummy-test-token}"
export GH_TOKEN

PROMPT_FILE="$TMP/prompt.txt"
printf 'say ok\n' > "$PROMPT_FILE"

# ─── (a) missing worktree arg → rc non-zero + named error ──────────────────
rc=0; err=$("$SPAWN" 2>&1) || rc=$?
check "missing all args -> non-zero" "1" "$([ "$rc" -ne 0 ] && echo 1 || echo 0)"
check_contains "missing all args -> error names worktree" "worktree" "$err"

# ─── (b) non-git worktree → named error mentioning git-common-dir ──────────
NOT_A_REPO="$TMP/not-a-repo"
mkdir -p "$NOT_A_REPO"
rc=0; err=$("$SPAWN" "$NOT_A_REPO" "$PROMPT_FILE" "claude-haiku-4-5-20251001" 2>&1) || rc=$?
check "non-git worktree -> non-zero" "1" "$([ "$rc" -ne 0 ] && echo 1 || echo 0)"
check_contains "non-git worktree -> error mentions git-common-dir" "git-common-dir" "$err"

# ─── Supported-platform-only cases ─────────────────────────────────────────
platform_supported=0
case "$(uname -s)" in
  Darwin|Linux) platform_supported=1 ;;
esac

if [ "$platform_supported" -ne 1 ]; then
  printf 'SKIP - (c)/(d) srt-exec cases: unsupported platform (%s)\n' "$(uname -s)"
else
  # Build a disposable git repo + worktree so PRIMARY_GIT resolution is real.
  REPO="$TMP/repo"
  mkdir -p "$REPO"
  git -C "$REPO" init -q
  git -C "$REPO" config user.email test@example.com
  git -C "$REPO" config user.name test
  git -C "$REPO" commit --allow-empty -q -m init

  WORKTREE="$TMP/wt"
  git -C "$REPO" worktree add -q "$WORKTREE" -b test-branch >/dev/null 2>&1

  STUBDIR="$TMP/stubbin"
  mkdir -p "$STUBDIR"

  # ─── (c) inside write succeeds, outside ($HOME) write denied ────────────
  cat > "$STUBDIR/claude" <<'STUB'
#!/bin/bash
echo "inside" > "$PWD/inside-probe.txt"
echo "escape attempt" > "$HOME/escape-probe" 2>&1
echo "stub-claude-ran"
STUB
  chmod +x "$STUBDIR/claude"

  rc=0
  out=$(PATH="$STUBDIR:$PATH" "$SPAWN" "$WORKTREE" "$PROMPT_FILE" "claude-haiku-4-5-20251001" 2>&1) || rc=$?

  check "(c) spawn exits 0 with stub claude" "0" "$rc"
  check "(c) inside-file was written" "1" \
    "$([ -f "$WORKTREE/inside-probe.txt" ] && echo 1 || echo 0)"
  check "(c) HOME escape file does NOT exist" "0" \
    "$([ -e "$HOME/escape-probe" ] && echo 1 || echo 0)"
  check_contains "(c) stderr shows the escape denial" "Operation not permitted" "$out"

  # ─── (d) stub-claude rc propagates ───────────────────────────────────────
  cat > "$STUBDIR/claude" <<'STUB'
#!/bin/bash
echo "failing on purpose"
exit 42
STUB
  chmod +x "$STUBDIR/claude"

  rc=0
  PATH="$STUBDIR:$PATH" "$SPAWN" "$WORKTREE" "$PROMPT_FILE" "claude-haiku-4-5-20251001" >/dev/null 2>&1 || rc=$?
  check "(d) worker rc 42 propagates" "42" "$rc"

  # ─── Correction 3 guard: XDG_CACHE_HOME set + writable, ~/.cache untouched ─
  # Locks in the containment win from correction 3: the spawn script must set
  # XDG_CACHE_HOME to a writable per-worker scratch dir so claude -p's own
  # cache need is met WITHOUT allowlisting ~/.cache. Verified live (srt
  # 0.0.65): omitting this env var, with ~/.cache absent from allowWrite,
  # makes claude -p silently emit empty output and still exit 0 — rc alone
  # can't catch that, so this asserts on the stub's actual observed content.
  cat > "$STUBDIR/claude" <<'STUB'
#!/bin/bash
if [ -z "${XDG_CACHE_HOME:-}" ]; then
  echo "XDG_CACHE_HOME-not-set" >&2
  exit 1
fi
if [ ! -d "$XDG_CACHE_HOME" ] || [ ! -w "$XDG_CACHE_HOME" ]; then
  echo "XDG_CACHE_HOME-not-writable-dir: $XDG_CACHE_HOME" >&2
  exit 1
fi
echo "cache-probe" > "$XDG_CACHE_HOME/cache-probe.txt" || exit 1
echo "xdg-cache-ok:$XDG_CACHE_HOME"
STUB
  chmod +x "$STUBDIR/claude"

  rc=0
  out=$(PATH="$STUBDIR:$PATH" "$SPAWN" "$WORKTREE" "$PROMPT_FILE" "claude-haiku-4-5-20251001" 2>&1) || rc=$?
  check "XDG_CACHE_HOME guard: spawn exits 0" "0" "$rc"
  check_contains "XDG_CACHE_HOME guard: stub observed it set + writable" "xdg-cache-ok:" "$out"

  git -C "$REPO" worktree remove --force "$WORKTREE" >/dev/null 2>&1
fi

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
