#!/bin/bash
# Pins the enforce_pr_workflow "enforcement ceiling" note in AGENTS.md so the
# honest boundary cannot silently vanish: the hook checks evidence of INVOCATION,
# not completion (a hollow invocation can satisfy it; a hook can't be tamper-proof
# against an agent in its own trust domain), so it is a redirect-and-audit layer —
# the real "no unreviewed change reaches main" guarantee is server-side GitHub
# branch protection. Pins stable marker phrases. (The working guide consolidated
# into AGENTS.md; CLAUDE.md is now a thin pointer to it.)
set -u
ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
GUIDE_MD="$ROOT/AGENTS.md"
fails=0

check() {  # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails + 1)); fi
}

if [ ! -f "$GUIDE_MD" ]; then
  printf 'FAIL - AGENTS.md not found at %s\n' "$GUIDE_MD"
  echo "FAILED (1)"; exit 1
fi

grep -q 'redirect-and-audit layer' "$GUIDE_MD" && present=yes || present=no
check "ceiling note present (redirect-and-audit layer)" yes "$present"

grep -qi 'branch protection' "$GUIDE_MD" && bp=yes || bp=no
check "branch-protection named as the real guarantee" yes "$bp"

grep -qi 'invocation' "$GUIDE_MD" && inv=yes || inv=no
check "invocation-not-completion boundary noted" yes "$inv"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
