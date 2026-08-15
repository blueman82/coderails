#!/bin/bash
# prompt_entrypoints.test.sh — every .github/prompts/<id>.prompt.md file must
# be a thin router: its skill_id (the filename minus .prompt.md) must resolve
# via skill_route.sh against skills/index.yaml, and the resolved path must
# actually appear in the prompt file's body and exist on disk. This proves
# the prompt file stays in sync with index.yaml rather than duplicating or
# drifting from the canonical provider-native skill body.
#
# Usage: bash prompt_entrypoints.test.sh
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
cd "$REPO_ROOT" || exit 1

INDEX="skills/index.yaml"
ROUTE="hooks/scripts/lib/skill_route.sh"

fails=0
count=0

for f in .github/prompts/*.prompt.md; do
  [ -e "$f" ] || continue
  count=$((count+1))
  id="$(basename "$f" .prompt.md)"

  resolved=$(bash "$ROUTE" "$INDEX" "$id" claude 2>/dev/null)
  rc=$?
  if [ "$rc" -ne 0 ]; then
    printf 'FAIL - %s: skill_id "%s" did not resolve against claude in %s\n' "$f" "$id" "$INDEX"
    fails=$((fails+1))
    continue
  fi

  if [ ! -f "$resolved" ]; then
    printf 'FAIL - %s: resolved path "%s" does not exist on disk\n' "$f" "$resolved"
    fails=$((fails+1))
    continue
  fi

  if ! grep -qF "$resolved" "$f"; then
    printf 'FAIL - %s: resolved path "%s" is not referenced in the prompt body\n' "$f" "$resolved"
    fails=$((fails+1))
    continue
  fi

  printf 'ok   - %s routes to %s\n' "$f" "$resolved"
done

if [ "$count" -eq 0 ]; then
  printf 'FAIL - no .github/prompts/*.prompt.md files found\n'
  fails=$((fails+1))
fi

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
