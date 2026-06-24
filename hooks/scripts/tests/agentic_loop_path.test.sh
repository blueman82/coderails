#!/bin/bash
# Unit test for agentic_loop_path.sh — path derivation + env override.
set -u
HELPER="$(cd "$(dirname "$0")/.." && pwd)/lib/agentic_loop_path.sh"
fails=0
check() { # desc, expected, actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n      expected: %s\n      actual:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# 1. Default base is $HOME/.claude/agentic-loop; slug replaces / with -.
unset CLAUDE_AGENTIC_LOOP_DIR
check "default base + slug" \
  "$HOME/.claude/agentic-loop/-Users-foo-bar/progress.json" \
  "$(bash "$HELPER" /Users/foo/bar)"

# 2. Env override redirects the base (used by the guard's behavioural tests).
check "env override base" \
  "/tmp/al/-Users-foo-bar/progress.json" \
  "$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" /Users/foo/bar)"

# 3. No-arg form defaults to the caller's PWD.
check "defaults to PWD" \
  "/tmp/al/$(printf '%s' "$PWD" | sed 's#/#-#g')/progress.json" \
  "$(cd "$PWD" && CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER")"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
