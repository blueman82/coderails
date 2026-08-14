#!/bin/bash
set -u

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HELPER="$ROOT/hooks/scripts/lib/graph_readiness.sh"
fails=0

check() {
  local provider="$1" case_name="$2" want="$3"; shift 3
  local fixture="$ROOT/packages/fixtures/$provider/$case_name.json" out rc
  out=$(bash "$HELPER" "$fixture" "$1"); rc=$?
  if [ "$out" = "$want" ] && { [ "$want" = ready ] && [ "$rc" -eq 0 ] || [ "$want" = blocked ] && [ "$rc" -eq 1 ]; }; then
    printf 'ok   - %s/%s: %s\n' "$provider" "$case_name" "$want"
  else
    printf 'FAIL - %s/%s: expected %s, got %s (exit %s)\n' "$provider" "$case_name" "$want" "$out" "$rc"
    fails=$((fails + 1))
  fi
}

for provider in claude codex; do
  check "$provider" ready ready next
  check "$provider" join-blocked blocked join
  check "$provider" retry ready retry
  check "$provider" stale blocked next
  check "$provider" missing-implementation blocked implementation
  check "$provider" dispatch ready dispatched
  check "$provider" completion-teardown ready teardown
done

[ "$fails" -eq 0 ] && { echo PASS; exit 0; }
echo "FAILED ($fails)"
exit 1
