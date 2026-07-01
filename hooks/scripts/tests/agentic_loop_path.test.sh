#!/bin/bash
# Unit test for agentic_loop_path.sh — path derivation + env override.
set -u
HELPER="$(cd "$(dirname "$0")/.." && pwd)/lib/agentic_loop_path.sh"
fails=0
check() { # desc, expected, actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n      expected: %s\n      actual:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# 1. Default base is $HOME/.claude/agentic-loop; slug replaces / with -; session_id
#    passed explicitly as arg 2.
unset CLAUDE_AGENTIC_LOOP_DIR CLAUDE_CODE_SESSION_ID
check "default base + slug + explicit session_id" \
  "$HOME/.claude/agentic-loop/-Users-foo-bar/S1/progress.json" \
  "$(bash "$HELPER" /Users/foo/bar S1)"

# 2. Env override redirects the base (used by the guard's behavioural tests).
check "env override base" \
  "/tmp/al/-Users-foo-bar/S1/progress.json" \
  "$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" /Users/foo/bar S1)"

# 3. No-arg form defaults cwd to the caller's PWD.
check "defaults cwd to PWD" \
  "/tmp/al/$(printf '%s' "$PWD" | sed 's#/#-#g')/S1/progress.json" \
  "$(cd "$PWD" && CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" "" S1)"

# 4. session_id defaults to $CLAUDE_CODE_SESSION_ID when arg 2 is omitted — this is
#    what lets the orchestrator's Bash calls resolve the path without ever typing
#    out its own session_id.
check "session_id defaults to CLAUDE_CODE_SESSION_ID env var" \
  "/tmp/al/-Users-foo-bar/S_ENV/progress.json" \
  "$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al CLAUDE_CODE_SESSION_ID=S_ENV bash "$HELPER" /Users/foo/bar)"

# 5. Two different session ids for the same cwd resolve to two different paths —
#    the actual fix: concurrent sessions in one directory no longer collide.
p1=$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" /Users/foo/bar S1)
p2=$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" /Users/foo/bar S2)
if [ "$p1" != "$p2" ]; then printf 'ok   - %s\n' "distinct sessions -> distinct paths"
else printf 'FAIL - %s\n      both resolved to: %s\n' "distinct sessions -> distinct paths" "$p1"; fails=$((fails+1)); fi

# 6. Same cwd + same session_id resolves to the same path every time — a single
#    session recovers its own file across compaction/restart within one conversation.
p3=$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" /Users/foo/bar S1)
check "same session_id -> stable path" "$p1" "$p3"

# 7. Two invocations that both have NO real session_id available (empty arg 2,
#    no CLAUDE_CODE_SESSION_ID env var) must NOT collide on a shared fixed
#    sentinel — each must get its own unique fallback so two genuinely different
#    sessions hitting this edge case never share one progress.json.
unset CLAUDE_CODE_SESSION_ID
q1=$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" /Users/foo/bar "")
q2=$(CLAUDE_AGENTIC_LOOP_DIR=/tmp/al bash "$HELPER" /Users/foo/bar "")
if [ "$q1" != "$q2" ]; then printf 'ok   - %s\n' "missing session_id -> unique fallback, no collision"
else printf 'FAIL - %s\n      both resolved to: %s\n' "missing session_id -> unique fallback, no collision" "$q1"; fails=$((fails+1)); fi

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
