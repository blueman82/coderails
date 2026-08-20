#!/bin/bash
# Behavioural test for scripts/lib/config.sh — the shared workflow.config.yaml
# resolver (walk-up from a start dir to the git root). Guards against the
# infinite-loop hang where the start dir and git's canonical root differ by a
# symlink prefix (macOS /tmp -> /private/tmp): the walk-up's `d == git_root`
# terminator never matched, dirname bottomed out at "/", and the loop spun
# forever. Each resolver call runs under a watchdog so a regression surfaces as
# a FAIL (timeout), never an actual hang of the suite.
set -u
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
LIB="$ROOT/scripts/lib/config.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fails=0

check() { # desc expected actual
    if [ "$2" = "$3" ]; then
        printf 'ok   - %s\n' "$1"
    else
        printf 'FAIL - %s (expected [%s], got [%s])\n' "$1" "$2" "$3"
        fails=$((fails + 1))
    fi
}

# Resolve with a hard 5s watchdog. Echoes the function's stdout, or the literal
# TIMEOUT if it hangs (the regression we are pinning). No `timeout(1)` dependency
# (absent on stock macOS) — use a background job + sleeper.
resolve() { # start_dir -> config_path | "" | "TIMEOUT"
    local start="$1" out rc
    out=$(
        {
            (
                bash -c '. "'"$LIB"'"; coderails::config_path "'"$start"'"' &
                p=$!
                (
                    sleep 5
                    kill -9 $p 2>/dev/null
                ) &
                w=$!
                wait $p 2>/dev/null
                rc=$?
                # Tear down the watchdog by killing its `sleep` child directly. Killing the
                # subshell ($w) instead orphans the sleep, which keeps the $() pipe's write
                # fd open until it exits naturally — so $() blocks the full 5s on every
                # happy-path call. pkill -P $w kills the sleep, closing that fd; the now-
                # childless subshell exits and `wait $w` reaps it (zombie hygiene only).
                # The outer { } 2>/dev/null swallows the job-control "Terminated: sleep"
                # notice the parent shell prints when it reaps the killed background job.
                pkill -P $w 2>/dev/null
                wait $w 2>/dev/null
                [ $rc -eq 137 ] && printf 'TIMEOUT'
            )
        } 2>/dev/null
    )
    printf '%s' "$out"
}

# A repo reached via a symlinked path, so `git rev-parse --show-toplevel`
# (canonical, /private/...) differs from the start dir (/var/... or /tmp/...).
# On macOS `mktemp -d` already gives a symlinked path, but force it explicitly so
# the test reproduces the hang on any OS: build the repo under a symlink.
REAL="$TMP/real"
mkdir -p "$REAL"
git -C "$REAL" init -q
LINK="$TMP/link"
ln -s "$REAL" "$LINK" # $LINK/... resolves to $REAL/... but is not string-equal

# ── The hang reproducer: symlinked start, NO config → must return empty, not hang.
check "symlinked start, no config -> empty (no hang)" "" "$(resolve "$LINK")"

# ── Symlinked start WITH a config at the root → must find it (not hang, not miss).
mkdir -p "$REAL/.coderails"
: >"$REAL/.coderails/workflow.config.yaml"
got=$(resolve "$LINK")
# The found path is canonical ($REAL), since git_root is canonical. Assert it ends
# with the expected suffix rather than pinning the /private prefix.
case "$got" in
*/.coderails/workflow.config.yaml) found=yes ;;
TIMEOUT) found=TIMEOUT ;;
*) found=no ;;
esac
check "symlinked start, config at root -> found (no hang)" yes "$found"

# ── Non-symlinked plain repo, config present → found (the happy path still works).
PLAIN="$TMP/plain"
mkdir -p "$PLAIN/.coderails"
git -C "$PLAIN" init -q
: >"$PLAIN/.coderails/workflow.config.yaml"
case "$(resolve "$PLAIN")" in
*/.coderails/workflow.config.yaml) p=yes ;; *) p=no ;;
esac
check "plain repo, config at root -> found" yes "$p"

# ── Plain repo, config in a SUBDIR, start below it → walk-up finds it.
sub="$PLAIN/apps/web"
mkdir -p "$sub"
case "$(resolve "$sub")" in
*/.coderails/workflow.config.yaml) s=yes ;; *) s=no ;;
esac
check "plain repo, start in subdir -> walk-up finds root config" yes "$s"

# ── Not a git repo at all → empty (no hang, no crash).
NOGIT="$TMP/nogit"
mkdir -p "$NOGIT"
check "non-git start -> empty" "" "$(resolve "$NOGIT")"

# Legacy provider paths are deliberately not runtime fallbacks.
LEGACY="$TMP/legacy"
mkdir -p "$LEGACY/.claude" "$LEGACY/.codex"
git -C "$LEGACY" init -q
: >"$LEGACY/.claude/workflow.config.yaml"
: >"$LEGACY/.codex/workflow.config.yaml"
check "legacy configs are ignored" "" "$(resolve "$LEGACY")"

# Runtime state stays ignored at root and in nested project scopes, while the
# canonical config remains committable at both levels.
IGNORES="$TMP/ignores"
mkdir -p "$IGNORES/.coderails" "$IGNORES/nested/.coderails"
git -C "$IGNORES" init -q
cp "$ROOT/.gitignore" "$IGNORES/.gitignore"
: >"$IGNORES/.coderails/progress.json"
: >"$IGNORES/.coderails/workflow.config.yaml"
: >"$IGNORES/nested/.coderails/progress.json"
: >"$IGNORES/nested/.coderails/workflow.config.yaml"
check "root runtime state is ignored" ignored "$(git -C "$IGNORES" check-ignore -q .coderails/progress.json && printf ignored || printf committable)"
check "root canonical config is committable" committable "$(git -C "$IGNORES" check-ignore -q .coderails/workflow.config.yaml && printf ignored || printf committable)"
check "nested runtime state is ignored" ignored "$(git -C "$IGNORES" check-ignore -q nested/.coderails/progress.json && printf ignored || printf committable)"
check "nested canonical config is committable" committable "$(git -C "$IGNORES" check-ignore -q nested/.coderails/workflow.config.yaml && printf ignored || printf committable)"

if [ "$fails" -eq 0 ]; then
    echo "PASS"
    exit 0
else
    echo "FAILED ($fails)"
    exit 1
fi
