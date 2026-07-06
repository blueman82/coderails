#!/bin/bash
set -u
SCRIPT="$(cd "$(dirname "$0")/.." && pwd)/sdd-workspace"
fails=0
check() { if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"; else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi; }

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_AGENTIC_LOOP_DIR="$TMP/state"

# Same session_id + same cwd -> same dir (two calls agree).
export CLAUDE_CODE_SESSION_ID="sess-A"
DIR1=$(cd "$TMP" && bash "$SCRIPT")
DIR2=$(cd "$TMP" && bash "$SCRIPT")
check "same session+cwd -> same dir" "$DIR1" "$DIR2"

# Different session_id -> different dir.
export CLAUDE_CODE_SESSION_ID="sess-B"
DIR3=$(cd "$TMP" && bash "$SCRIPT")
if [ "$DIR1" = "$DIR3" ]; then
  printf 'FAIL - different session_id produced the same dir (%s)\n' "$DIR1"; fails=$((fails+1))
else
  printf 'ok   - different session_id -> different dir\n'
fi

# Dir is created and writable.
if [ -d "$DIR1" ] && [ -w "$DIR1" ]; then
  printf 'ok   - resolved dir exists and is writable\n'
else
  printf 'FAIL - resolved dir missing or not writable: %s\n' "$DIR1"; fails=$((fails+1))
fi

# Dir sits beside progress.json's own directory (dirname of agentic_loop_path.sh's output).
export CLAUDE_CODE_SESSION_ID="sess-A"
REPO_ROOT="$(cd "$(dirname "$SCRIPT")/../../.." && pwd)"
PROGRESS_PATH=$(cd "$TMP" && bash "$REPO_ROOT/hooks/scripts/lib/agentic_loop_path.sh")
EXPECTED_DIR=$(dirname "$PROGRESS_PATH")
check "sdd-workspace dir == dirname(agentic_loop_path.sh output)" "$EXPECTED_DIR" "$DIR1"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
