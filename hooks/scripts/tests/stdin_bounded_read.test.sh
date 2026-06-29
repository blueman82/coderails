#!/bin/bash
# Behavioural test: hook scripts must not block forever when stdin has no EOF.
#
# Latent risk: `input=$(cat)` blocks until EOF. If Claude Code's parent process
# dies without closing stdin, the hook hangs forever. The fix is:
#   IFS= read -r -d '' -t 5 input || true
# which times out after 5s and returns normally.
#
# Test structure:
#   GUARD — open a pipe, hold the write-end open (no EOF), run the hook against the
#            read-end, assert the hook exits within 8s. Uses background-process
#            + bounded-poll (no `timeout` — absent on macOS).
#   FIDELITY — pipe a normal multi-line JSON payload and assert the hook's normal
#              allow/deny decision is unchanged, proving read -d '' preserves payload.
set -u
SCRIPTS="$(cd "$(dirname "$0")/.." && pwd)"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fails=0

check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# ---------------------------------------------------------------------------
# run_bounded <hook> <pipe_read_fd_path> <max_seconds> -> exit code or "HANG"
#
# Runs the hook with its stdin attached to the given named pipe (read end).
# The write end is held open in a background holder process (no data, no EOF).
# If the hook doesn't exit within max_seconds, we kill it and return "HANG".
# No `timeout` command (absent on macOS). No fractional sleep (bash 3.2
# rejects fractional -t; use perl for sub-second or integer sleep).
# ---------------------------------------------------------------------------
run_bounded() {  # hook_script pipe_read max_seconds -> rc | "HANG"
  local hook="$1" pipe_read="$2" max_s="$3"
  local hook_pid holder_pid elapsed rc

  # Start hook reading from the pipe.
  bash "$hook" < "$pipe_read" >/dev/null 2>/dev/null &
  hook_pid=$!

  # Poll for exit up to max_s seconds (integer poll).
  elapsed=0
  rc="HANG"
  while [ "$elapsed" -le "$max_s" ]; do
    if ! kill -0 "$hook_pid" 2>/dev/null; then
      wait "$hook_pid" 2>/dev/null
      rc=$?
      break
    fi
    sleep 1
    elapsed=$((elapsed + 1))
  done

  # If still running, kill it.
  if [ "$rc" = "HANG" ]; then
    kill "$hook_pid" 2>/dev/null
    wait "$hook_pid" 2>/dev/null
  fi

  printf '%s' "$rc"
}

# ---------------------------------------------------------------------------
# GUARD TESTS — prove each hook exits within 8s on a never-closing stdin.
# We test test_gate.sh as the representative PreToolUse hook.
# check_confidence_labels.sh as the representative Stop hook.
# ---------------------------------------------------------------------------

# Set up a named pipe. The write end is held open by a background process that
# never writes and never exits until we kill it.
PIPE="$TMP/stdin_pipe"
mkfifo "$PIPE"

# Open the write end in the background — keeps it open (no EOF for readers).
# Use exec in a subshell so we can track and kill the fd-holder.
( exec 3>"$PIPE"; while true; do sleep 60; done ) &
HOLDER_PID=$!

# Give the holder a moment to open the fd.
sleep 1

# test_gate.sh (PreToolUse hook): should exit quickly even with no EOF on stdin.
# The hook has no .claude/test_command in TMP, so it will exit 0 once it reads.
# With input=$(cat) it hangs; with read -d '' -t 5 it exits within 8s.
HOOK_RESULT=$(run_bounded "$SCRIPTS/test_gate.sh" "$PIPE" 8)
if [ "$HOOK_RESULT" = "HANG" ]; then
  printf 'FAIL - test_gate.sh: stdin with no EOF caused hook to hang (expected exit within 8s)\n'
  fails=$((fails+1))
else
  printf 'ok   - test_gate.sh: exited within 8s on never-closing stdin (rc=%s)\n' "$HOOK_RESULT"
fi

# check_confidence_labels.sh (Stop hook): same guard.
# With no transcript in the payload (read from stdin pipe with no EOF), it hangs on
# input=$(cat); with read -d '' -t 5 it exits quickly.
HOOK_RESULT=$(run_bounded "$SCRIPTS/check_confidence_labels.sh" "$PIPE" 8)
if [ "$HOOK_RESULT" = "HANG" ]; then
  printf 'FAIL - check_confidence_labels.sh: stdin with no EOF caused hook to hang\n'
  fails=$((fails+1))
else
  printf 'ok   - check_confidence_labels.sh: exited within 8s on never-closing stdin (rc=%s)\n' "$HOOK_RESULT"
fi

# Tear down the holder process.
kill "$HOLDER_PID" 2>/dev/null
wait "$HOLDER_PID" 2>/dev/null

# ---------------------------------------------------------------------------
# FIDELITY TESTS — prove the new read preserves multi-line JSON payloads.
# Pipe a normal payload and assert the hook's allow/deny decision is unchanged.
# ---------------------------------------------------------------------------

run_with_payload() {  # hook_script json -> DENY|ALLOW|rc
  local hook="$1" json="$2" out
  out=$(printf '%s' "$json" | bash "$hook" 2>/dev/null)
  if printf '%s' "$out" | grep -q '"permissionDecision": *"deny"'; then
    printf 'DENY'
  else
    printf 'ALLOW'
  fi
}

# test_gate.sh fidelity (deny path): git commit with a failing test_command -> deny.
# This proves read -d '' preserves the payload AND the gate's real deny logic fires.
FIDELITY_DIR="$TMP/fidelity_proj"
mkdir -p "$FIDELITY_DIR/.claude"
printf 'false\n' > "$FIDELITY_DIR/.claude/test_command"
PAYLOAD=$(jq -n --arg cmd "git commit -m 'fix'" '{"tool_name":"Bash","tool_input":{"command":$cmd}}')
# Run from FIDELITY_DIR so test_gate.sh finds the failing .claude/test_command.
GATE_DENY_RESULT=$(cd "$FIDELITY_DIR" && run_with_payload "$SCRIPTS/test_gate.sh" "$PAYLOAD")
check "fidelity: test_gate.sh failing test_command -> deny (payload preserved, gate fires)" "DENY" "$GATE_DENY_RESULT"

# destructive_bash_gate.sh fidelity: rm -rf -> deny.
PAYLOAD_DENY=$(jq -n --arg cmd "rm -rf /tmp/x" '{"tool_name":"Bash","tool_input":{"command":$cmd}}')
DENY_RESULT=$(run_with_payload "$SCRIPTS/destructive_bash_gate.sh" "$PAYLOAD_DENY")
check "fidelity: destructive_bash_gate.sh rm -rf -> deny (payload preserved)" "DENY" "$DENY_RESULT"

# destructive_bash_gate.sh fidelity: safe command -> allow.
PAYLOAD_ALLOW=$(jq -n --arg cmd "git status" '{"tool_name":"Bash","tool_input":{"command":$cmd}}')
ALLOW_RESULT=$(run_with_payload "$SCRIPTS/destructive_bash_gate.sh" "$PAYLOAD_ALLOW")
check "fidelity: destructive_bash_gate.sh git status -> allow (payload preserved)" "ALLOW" "$ALLOW_RESULT"

# fail-open invariant: empty stdin -> deny-first hook must stand aside (exit 0, no deny).
# Locks in "empty/stalled input -> allow" so a future fail-closed change is caught.
FAIL_OPEN_OUT=$(printf '' | bash "$SCRIPTS/destructive_bash_gate.sh" 2>/dev/null)
FAIL_OPEN_RC=$?
if [ "$FAIL_OPEN_RC" -eq 0 ] && ! printf '%s' "$FAIL_OPEN_OUT" | grep -q '"permissionDecision": *"deny"'; then
  FAIL_OPEN_RESULT="ALLOW"
else
  FAIL_OPEN_RESULT="BLOCK"
fi
check "fail-open: empty stdin -> destructive_bash_gate.sh stands aside (exit 0, no deny)" "ALLOW" "$FAIL_OPEN_RESULT"

# check_confidence_labels.sh fidelity: short payload -> allow (no block on short text).
# The hook exits 0 (no block) when text < MIN_LEN chars. Feed empty transcript path.
PAYLOAD_LABELS=$(jq -n '{"hook_event_name":"Stop","session_id":"test","transcript_path":"/nonexistent/path"}')
LABELS_RESULT=$(printf '%s' "$PAYLOAD_LABELS" | bash "$SCRIPTS/check_confidence_labels.sh" 2>/dev/null; echo $?)
check "fidelity: check_confidence_labels.sh missing transcript -> allow (exit 0)" "0" "$LABELS_RESULT"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
