#!/bin/bash
# Pins the enforce_pr_workflow "enforcement ceiling" note in CLAUDE.md so the
# honest boundary cannot silently vanish: the hook checks evidence of INVOCATION,
# not completion (a hollow invocation can satisfy it; a hook can't be tamper-proof
# against an agent in its own trust domain), so it is a redirect-and-audit layer —
# the real "no unreviewed change reaches main" guarantee is server-side GitHub
# branch protection. Pins stable marker phrases.
set -u
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
CLAUDE_MD="$ROOT/CLAUDE.md"
fails=0

check() {  # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails + 1)); fi
}

if [ ! -f "$CLAUDE_MD" ]; then
  printf 'FAIL - CLAUDE.md not found at %s\n' "$CLAUDE_MD"
  echo "FAILED (1)"; exit 1
fi

grep -q 'redirect-and-audit layer' "$CLAUDE_MD" && present=yes || present=no
check "ceiling note present (redirect-and-audit layer)" yes "$present"

grep -qi 'branch protection' "$CLAUDE_MD" && bp=yes || bp=no
check "branch-protection named as the real guarantee" yes "$bp"

grep -qi 'invocation' "$CLAUDE_MD" && inv=yes || inv=no
check "invocation-not-completion boundary noted" yes "$inv"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
