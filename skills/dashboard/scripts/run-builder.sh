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

LOCKS_DIR="${CODERAILS_BUILDER_LOCKS_DIR:-$HOME/.claude/coderails-dashboard/locks}"
LOCK_PATH="$LOCKS_DIR/builder.lock"
QUEUE_TIMEOUT_SECS="${BUILDER_QUEUE_TIMEOUT_SECS:-14400}"   # 4h
POLL_INTERVAL_SECS="${BUILDER_POLL_INTERVAL_SECS:-15}"
WALL_CLOCK_SECS="${BUILDER_WALL_CLOCK_SECS:-2700}"          # 45m

TERMINAL_STATE_WRITTEN=0
LOCK_HELD=0
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
  ' > "$BUILD_DIR/state.json.tmp"
  mv "$BUILD_DIR/state.json.tmp" "$BUILD_DIR/state.json"
}

fail_terminal() {
  write_state "failed" "$1"
  TERMINAL_STATE_WRITTEN=1
  exit 1
}

# Guarantees a terminal state.json is on disk no matter how the script
# exits (explicit fail_terminal, an unexpected command failure under `set
# -e`-equivalent checks below, or a TERM from the watchdog). Without this,
# any command that fails between "claimed" and the deliberate terminal
# writes below (e.g. git fetch/worktree add) would otherwise leave the
# build permanently stuck at a non-terminal state with nothing to signal
# the dashboard.
on_exit() {
  local exit_code=$?
  [ -n "$HEARTBEAT_PID" ] && kill "$HEARTBEAT_PID" 2>/dev/null
  [ -n "$WATCHDOG_PID" ] && kill "$WATCHDOG_PID" 2>/dev/null
  if [ "$TERMINAL_STATE_WRITTEN" -eq 0 ] && [ "$exit_code" -ne 0 ]; then
    write_state "failed" "unexpected_exit:$exit_code"
  fi
  [ "$LOCK_HELD" -eq 1 ] && rm -f "$LOCK_PATH"
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
while ! ( set -o noclobber; echo "$$" > "$LOCK_PATH" ) 2>/dev/null; do
  write_state "queued"
  if [ "$waited" -ge "$QUEUE_TIMEOUT_SECS" ]; then
    fail_terminal "queue_timeout"
  fi
  sleep "$POLL_INTERVAL_SECS"
  waited=$((waited + POLL_INTERVAL_SECS))
done
LOCK_HELD=1
trap on_exit EXIT

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
if [ ! -d "$ABS_REPO_PATH/.git" ]; then
  fail_terminal "bad_repo_path"
fi
if ! grep -q '"coderails"' "$ABS_REPO_PATH/package.json" 2>/dev/null && \
   ! grep -q 'name.*coderails' "$ABS_REPO_PATH/package.json" 2>/dev/null; then
  fail_terminal "bad_repo_path"
fi
PROPOSED_NAME=$(jq -r '.toolInput.proposed_name // empty' "$BUILD_DIR/snapshot.json")
HASH8=$(echo "$STORED_HASH" | cut -c1-8)
WORKTREE_DIR="$ABS_REPO_PATH/.claude/worktrees/skill-build-$HASH8"
if ! git -C "$ABS_REPO_PATH" fetch origin; then
  fail_terminal "worktree_setup_failed:fetch"
fi
if ! git -C "$ABS_REPO_PATH" worktree add "$WORKTREE_DIR" -b "workflow-audit/skill-$PROPOSED_NAME" origin/main; then
  fail_terminal "worktree_setup_failed:add"
fi

# --- Step 5: record + heartbeat + watchdog ---
CLAUDE_VERSION=$(claude --version 2>/dev/null || echo "unknown")
jq -n --arg hash "$STORED_HASH" --arg v "$CLAUDE_VERSION" --arg t "$(date +%s000)" --arg pid "$$" '
  {schemaVersion: 1, hash: $hash, state: "running", startedAt: ($t|tonumber), claudeVersion: $v, pid: ($pid|tonumber)}
' > "$BUILD_DIR/state.json"

( while true; do touch "$BUILD_DIR/heartbeat"; sleep "${BUILDER_HEARTBEAT_SECS:-30}"; done ) &
HEARTBEAT_PID=$!
( sleep "$WALL_CLOCK_SECS" && kill -TERM $$ 2>/dev/null ) &
WATCHDOG_PID=$!

# --- Step 6: spawn claude ---
cd "$WORKTREE_DIR" || fail_terminal "worktree_setup_failed:cd"
claude -p "$(cat "$BUILD_DIR/prompt.md")" \
  --dangerously-skip-permissions \
  --max-budget-usd 25 \
  --output-format json \
  > "$BUILD_DIR/result.json" 2> "$BUILD_DIR/build.log"
CLAUDE_EXIT=$?

# --- Step 7: terminal state from artifacts ---
if [ "$CLAUDE_EXIT" -eq 0 ] && [ -f "$BUILD_DIR/pr_url" ]; then
  PR_URL=$(cat "$BUILD_DIR/pr_url")
  jq -n --arg hash "$STORED_HASH" --arg v "$CLAUDE_VERSION" --arg pr "$PR_URL" '
    {schemaVersion: 1, hash: $hash, state: "pr_open", claudeVersion: $v, prUrl: $pr}
  ' > "$BUILD_DIR/state.json"
  TERMINAL_STATE_WRITTEN=1
else
  STDERR_TAIL=$(tail -20 "$BUILD_DIR/build.log" 2>/dev/null)
  FAILURE_REASON="nonzero_exit"
  if grep -q "error_max_budget_usd" "$BUILD_DIR/result.json" 2>/dev/null; then
    FAILURE_REASON="budget_exceeded"
  fi
  jq -n --arg hash "$STORED_HASH" --arg reason "$FAILURE_REASON" --arg tail "$STDERR_TAIL" '
    {schemaVersion: 1, hash: $hash, state: "failed", failureReason: $reason, stderrTail: $tail}
  ' > "$BUILD_DIR/state.json"
  TERMINAL_STATE_WRITTEN=1
  exit 1
fi
