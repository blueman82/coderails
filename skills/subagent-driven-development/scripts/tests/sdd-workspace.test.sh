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

# Unset/empty CLAUDE_CODE_SESSION_ID -> fail loud (non-idempotent fallback refused).
STDERR=$(cd "$TMP" && env -u CLAUDE_CODE_SESSION_ID bash "$SCRIPT" 2>&1 >/dev/null)
RC=0
(cd "$TMP" && env -u CLAUDE_CODE_SESSION_ID bash "$SCRIPT" >/dev/null 2>&1) || RC=$?
if [ "$RC" -ne 0 ] && printf '%s' "$STDERR" | grep -q "CLAUDE_CODE_SESSION_ID"; then
  printf 'ok   - unset CLAUDE_CODE_SESSION_ID -> non-zero exit, stderr names the var\n'
else
  printf 'FAIL - unset CLAUDE_CODE_SESSION_ID -> expected non-zero exit + stderr naming the var (rc=%s, stderr=%s)\n' "$RC" "$STDERR"
  fails=$((fails+1))
fi

# Helper stubbed to print nothing on exit 0 -> sdd-workspace must fail loud, not
# silently degrade to cwd. Stub via a temp copy of the repo layout so
# sdd-workspace's own dirname-based path-to-helper resolution finds the fake.
STUB_REPO=$(mktemp -d)
mkdir -p "$STUB_REPO/hooks/scripts/lib" "$STUB_REPO/skills/subagent-driven-development/scripts"
printf '#!/bin/bash\nexit 0\n' > "$STUB_REPO/hooks/scripts/lib/agentic_loop_path.sh"
chmod +x "$STUB_REPO/hooks/scripts/lib/agentic_loop_path.sh"
cp "$SCRIPT" "$STUB_REPO/skills/subagent-driven-development/scripts/sdd-workspace"
export CLAUDE_CODE_SESSION_ID="sess-A"
STUB_RC=0
STUB_STDERR=$(bash "$STUB_REPO/skills/subagent-driven-development/scripts/sdd-workspace" 2>&1 >/dev/null) || STUB_RC=$?
rm -rf "$STUB_REPO"
if [ "$STUB_RC" -ne 0 ] && printf '%s' "$STUB_STDERR" | grep -q "agentic_loop_path.sh"; then
  printf 'ok   - helper prints empty output on exit 0 -> sdd-workspace fails loud\n'
else
  printf 'FAIL - helper prints empty output on exit 0 -> expected non-zero exit (rc=%s, stderr=%s)\n' "$STUB_RC" "$STUB_STDERR"
  fails=$((fails+1))
fi

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
