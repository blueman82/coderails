#!/bin/bash
# skills/dashboard/scripts/run-builder.sh <buildDir>
#
# Owns the build lifecycle state machine for one approved
# workflow-audit:propose-skill queue entry. Invoked detached by
# src/lib/build/spawn.ts's claimAndSpawnBuild after the dashboard route
# claims a builds/<hash>/ directory. Never invoked directly by a human.
#
# Bash 3.2 compatible: no mapfile, no associative arrays, no ${var,,}.
set -uo pipefail

BUILD_DIR="$1"

LOCKS_DIR="${CODERAILS_BUILDER_LOCKS_DIR:-$HOME/.codex/coderails-dashboard/locks}"
LOCK_PATH="$LOCKS_DIR/builder.lock"
QUEUE_TIMEOUT_SECS="${BUILDER_QUEUE_TIMEOUT_SECS:-14400}" # 4h
POLL_INTERVAL_SECS="${BUILDER_POLL_INTERVAL_SECS:-15}"
WALL_CLOCK_SECS="${BUILDER_WALL_CLOCK_SECS:-2700}" # 45m

TERMINAL_STATE_WRITTEN=0
LOCK_HELD=0
WATCHDOG_TERMINATED=0
HEARTBEAT_PID=""
WATCHDOG_PID=""

write_state() {
    # write_state <state> [failureReason] [stderrTail]
    local state="$1"
    local reason="${2:-}"
    local tail="${3:-}"
    local hash
    hash=$(jq -r '.hash // "unknown"' "$BUILD_DIR/state.json" 2>/dev/null || echo "unknown")
    jq -n --arg hash "$hash" --arg state "$state" --arg reason "$reason" --arg tail "$tail" '
    {schemaVersion: 1, hash: $hash, state: $state}
    + (if $reason != "" then {failureReason: $reason} else {} end)
    + (if $tail != "" then {stderrTail: $tail} else {} end)
  ' >"$BUILD_DIR/state.json.tmp"
    mv "$BUILD_DIR/state.json.tmp" "$BUILD_DIR/state.json"
}

fail_terminal() {
    write_state "failed" "$1"
    TERMINAL_STATE_WRITTEN=1
    exit 1
}

# Guarantees a terminal state.json is on disk no matter how the script
# exits (explicit fail_terminal, an unexpected command failure, or a
# direct TERM to the wrapper's own PID). The watchdog's normal timeout
# path kills the codex child specifically (see Step 6) and is caught
# there via WATCHDOG_TERMINATED, not via this trap — but a stray external
# TERM to $$ is still handled here as a defensive backstop. Without this
# trap, any command that fails between "claimed" and the deliberate
# terminal writes below (e.g. git fetch/worktree add) would otherwise leave
# the build permanently stuck at a non-terminal state with nothing to
# signal the dashboard.
#
# IMPORTANT: `$?` must be captured on a bare assignment BEFORE any other
# statement runs in this function — `local exit_code=$?` would clobber `$?`
# with `local`'s own (successful) exit status before the right-hand side is
# ever read, silently losing the real exit code (a classic bash trap
# pitfall).
on_exit() {
    EXIT_CODE=$?
    [ -n "$HEARTBEAT_PID" ] && kill "$HEARTBEAT_PID" 2>/dev/null
    [ -n "$WATCHDOG_PID" ] && kill "$WATCHDOG_PID" 2>/dev/null
    if [ "$TERMINAL_STATE_WRITTEN" -eq 0 ]; then
        if [ "$WATCHDOG_TERMINATED" -eq 1 ]; then
            write_state "failed" "timeout"
        elif [ "$EXIT_CODE" -ne 0 ]; then
            write_state "failed" "unexpected_exit:$EXIT_CODE"
        fi
    fi
    [ "$LOCK_HELD" -eq 1 ] && rm -f "$LOCK_PATH"
}

# Runs on SIGTERM (the watchdog's wall-clock kill). Records that this was a
# timeout specifically — set BEFORE exiting, so on_exit (which the EXIT
# trap still fires afterward) can tell a watchdog kill apart from any other
# nonzero exit and report failureReason "timeout" instead of a generic
# "unexpected_exit:<code>".
on_term() {
    WATCHDOG_TERMINATED=1
    exit 143
}

# --- Step 1: global serialization ---
mkdir -p "$LOCKS_DIR"

if [ -f "$LOCK_PATH" ]; then
    LOCK_PID=$(cat "$LOCK_PATH" 2>/dev/null || echo "")
    if [ -n "$LOCK_PID" ] && ! kill -0 "$LOCK_PID" 2>/dev/null; then
        rm -f "$LOCK_PATH"
    fi
fi

waited=0
while ! (
    set -o noclobber
    echo "$$" >"$LOCK_PATH"
) 2>/dev/null; do
    write_state "queued"
    if [ "$waited" -ge "$QUEUE_TIMEOUT_SECS" ]; then
        fail_terminal "queue_timeout"
    fi
    sleep "$POLL_INTERVAL_SECS"
    waited=$((waited + POLL_INTERVAL_SECS))
done
LOCK_HELD=1
trap on_exit EXIT
trap on_term TERM

# --- Step 2: deterministic hash re-validation, before any LLM runs ---
if [ ! -f "$BUILD_DIR/snapshot.json" ]; then
    fail_terminal "unparseable_entry:snapshot.json"
fi
STORED_HASH=$(jq -r '.hash // empty' "$BUILD_DIR/snapshot.json" 2>/dev/null)
if [ -z "$STORED_HASH" ]; then
    fail_terminal "unparseable_entry:snapshot.json"
fi
# Canonicalisation must match the queue producer's convention exactly
# (skills/workflow-audit/scripts/write_queue_entry.sh): capture jq's output
# through a $(...) command substitution first, which strips the trailing
# newline jq emits, THEN hash that. Piping jq directly into shasum would hash
# the trailing newline too and never match the stored hash.
CANONICAL_TOOL_INPUT=$(jq -S -c '.toolInput' "$BUILD_DIR/snapshot.json" 2>/dev/null)
COMPUTED_HASH=$(printf '%s' "$CANONICAL_TOOL_INPUT" | shasum -a 256 | awk '{print $1}')
if [ "$COMPUTED_HASH" != "$STORED_HASH" ]; then
    fail_terminal "hash_mismatch:$STORED_HASH"
fi

# --- Step 3: filter re-assert ---
STATUS=$(jq -r '.status // empty' "$BUILD_DIR/snapshot.json")
TOOLNAME=$(jq -r '.toolName // empty' "$BUILD_DIR/snapshot.json")
if [ "$STATUS" != "approved" ] || [ "$TOOLNAME" != "workflow-audit:propose-skill" ]; then
    fail_terminal "filter_mismatch"
fi

# --- Step 4: worktree ---
ABS_REPO_PATH="${CODERAILS_BUILDER_REPO_PATH:?CODERAILS_BUILDER_REPO_PATH must be set}"
# Distinct bad_repo_path suffixes (matching the script's reason:detail
# convention) because state.json's failureReason is the operator's only
# diagnostic — the wrapper runs with stdio ignored. A bare .git FILE (a
# linked worktree) also lands in no_git: the path must be the primary
# checkout.
if [ ! -d "$ABS_REPO_PATH/.git" ]; then
    fail_terminal "bad_repo_path:no_git"
fi
# The Codex plugin identity lives in packages/codex. The name is compared exactly:
# a substring grep would let any repo that merely mentions coderails
# (a keyword, a description) pass the one guard that decides where the
# unattended builder runs.
PLUGIN_JSON="$ABS_REPO_PATH/packages/codex/.codex-plugin/plugin.json"
# Reject a symlinked identity file or a symlinked .codex-plugin dir: the
# guard's job is to confirm this path IS the real primary checkout, and a
# symlink to the genuine plugin.json would let an otherwise-foreign repo
# borrow coderails's identity and run the unattended builder.
if [ ! -f "$PLUGIN_JSON" ] || [ -L "$PLUGIN_JSON" ] || [ -L "$ABS_REPO_PATH/packages/codex/.codex-plugin" ]; then
    fail_terminal "bad_repo_path:no_identity_file"
fi
if [ "$(jq -r '.name // empty' "$PLUGIN_JSON" 2>/dev/null)" != "coderails-codex" ]; then
    fail_terminal "bad_repo_path:wrong_identity"
fi
PROPOSED_NAME=$(jq -r '.toolInput.proposed_name // empty' "$BUILD_DIR/snapshot.json")
# Every other snapshot-derived invariant (hash, status, toolName) is
# independently re-asserted by the wrapper rather than trusted from
# spawn.ts's upstream check — proposed_name, which becomes a branch name
# and path segment, gets the same treatment rather than being the one
# exception.
if ! echo "$PROPOSED_NAME" | grep -Eq '^[a-z0-9][a-z0-9-]{0,63}$'; then
    fail_terminal "invalid_proposed_name"
fi
HASH8=$(echo "$STORED_HASH" | cut -c1-8)
WORKTREE_DIR="$ABS_REPO_PATH/.codex/worktrees/skill-build-$HASH8"
if ! git -C "$ABS_REPO_PATH" fetch origin; then
    fail_terminal "worktree_setup_failed:fetch"
fi
if ! git -C "$ABS_REPO_PATH" worktree add "$WORKTREE_DIR" -b "workflow-audit/skill-$PROPOSED_NAME" origin/main; then
    fail_terminal "worktree_setup_failed:add"
fi

# --- Step 5: record + heartbeat + watchdog ---
CODEX_VERSION=$(codex --version 2>/dev/null || echo "unknown")
jq -n --arg hash "$STORED_HASH" --arg v "$CODEX_VERSION" --arg t "$(date +%s000)" --arg pid "$$" '
  {schemaVersion: 1, hash: $hash, state: "running", startedAt: ($t|tonumber), codexVersion: $v, pid: ($pid|tonumber)}
' >"$BUILD_DIR/state.json"

(while true; do
    touch "$BUILD_DIR/heartbeat"
    sleep "${BUILDER_HEARTBEAT_SECS:-30}"
done) &
HEARTBEAT_PID=$!

# --- Step 6: spawn codex ---
cd "$WORKTREE_DIR" || fail_terminal "worktree_setup_failed:cd"

# codex runs as a background job (not foreground), and the watchdog kills
# that job's PID specifically (not $$) — bash only checks for a pending
# trap between commands, and while blocked on a FOREGROUND child it does
# not interrupt early even after the trap's signal arrives. `wait` on a
# background job's PID returns promptly once that specific process is
# killed, which is what lets the wall-clock timeout actually cut a
# long-running codex session short instead of silently waiting the full
# duration out.
#
# The builder stays inside Codex's workspace-write sandbox. Network access
# and Git metadata writes remain blocked, so delivery is a separate human
# step after local edits and tests complete. The prompt fence and wall-clock
# watchdog remain additional bounds on the approved proposal and run time.
codex exec \
    --sandbox workspace-write \
    -c sandbox_workspace_write.network_access=false \
    --json \
    -- "$(cat "$BUILD_DIR/prompt.md")" \
    >"$BUILD_DIR/result.json" 2>"$BUILD_DIR/build.log" &
CODEX_PID=$!
(sleep "$WALL_CLOCK_SECS" && kill -TERM "$CODEX_PID" 2>/dev/null) &
WATCHDOG_PID=$!

set +e
wait "$CODEX_PID"
CODEX_EXIT=$?
set -e
if [ "$CODEX_EXIT" -gt 128 ]; then
    # codex was killed by a signal (the watchdog's TERM, most likely) —
    # report this as a timeout rather than falling through to the generic
    # nonzero_exit path, regardless of whether the watchdog's own subshell
    # happened to still be racing to fire when this check runs.
    WATCHDOG_TERMINATED=1
fi

# --- Step 7: terminal state ---
if [ "$CODEX_EXIT" -eq 0 ]; then
    jq -n --arg hash "$STORED_HASH" --arg v "$CODEX_VERSION" --arg worktree "$WORKTREE_DIR" '
    {schemaVersion: 1, hash: $hash, state: "ready_for_review", codexVersion: $v, worktreePath: $worktree}
  ' >"$BUILD_DIR/state.json"
    TERMINAL_STATE_WRITTEN=1
else
    STDERR_TAIL=$(tail -20 "$BUILD_DIR/build.log" 2>/dev/null)
    if [ "$WATCHDOG_TERMINATED" -eq 1 ]; then
        FAILURE_REASON="timeout"
    elif grep -q "unknown option" "$BUILD_DIR/build.log" 2>/dev/null; then
        # Verified empirically: this codex CLI version rejects an unrecognized
        # flag loudly before a session starts rather than silently ignoring it.
        FAILURE_REASON="codex_cli_flag_rejected"
    else
        FAILURE_REASON="nonzero_exit"
    fi
    jq -n --arg hash "$STORED_HASH" --arg reason "$FAILURE_REASON" --arg tail "$STDERR_TAIL" '
    {schemaVersion: 1, hash: $hash, state: "failed", failureReason: $reason, stderrTail: $tail}
  ' >"$BUILD_DIR/state.json"
    TERMINAL_STATE_WRITTEN=1
    exit 1
fi
