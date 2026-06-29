#!/bin/bash
# Guard test: every declared hooks.json timeout for hooks/scripts/ commands must
# be >= 5 (the `read -t 5` in-process backstop floor added in PR #76).
# If a timeout is declared BELOW 5, the harness kills the hook before the
# in-process backstop can fire, silently breaking the invariant.
# Hooks with NO declared timeout use Claude Code's default (60s) — safe, excluded.
#
# Usage: bash hooks_json_timeout_floor.test.sh [path/to/hooks.json]
#   Default path: hooks/hooks.json relative to the repo root (two dirs up).
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
HOOKS_JSON="${1:-$REPO_ROOT/hooks/hooks.json}"
READ_T_FLOOR=5

fails=0

check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# --- Validate prerequisites ---
if ! command -v jq >/dev/null 2>&1; then
  printf 'FAIL - jq is required but not found in PATH\n'
  exit 1
fi

if [ ! -f "$HOOKS_JSON" ]; then
  printf 'FAIL - hooks.json not found: %s\n' "$HOOKS_JSON"
  exit 1
fi

# --- Extract all declared timeouts for hooks/scripts/ commands ---
# Filter: entries whose command references hooks/scripts/ AND have a non-null timeout.
# Hooks with no declared timeout default to 60s (safe) and are intentionally excluded.
declared_timeouts=$(jq -r '
  [.hooks | to_entries[] | .value[] | .hooks[]?
   | select(.command | test("hooks/scripts/"))
   | select(.timeout != null)
   | .timeout]
  | .[]
' "$HOOKS_JSON")

if [ -z "$declared_timeouts" ]; then
  printf 'ok   - no declared timeouts found for hooks/scripts/ entries (all default to 60s — safe)\n'
  [ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
fi

# --- Assert each declared timeout >= READ_T_FLOOR ---
min_timeout=""
while IFS= read -r t; do
  [ -z "$t" ] && continue
  if [ -z "$min_timeout" ] || [ "$t" -lt "$min_timeout" ]; then
    min_timeout="$t"
  fi
done <<EOF
$declared_timeouts
EOF

if [ -n "$min_timeout" ] && [ "$min_timeout" -lt "$READ_T_FLOOR" ]; then
  printf 'FAIL - hooks.json declares a timeout (%d) below the read -t %d in-process backstop floor — lower the read -t bound or raise the timeout\n' \
    "$min_timeout" "$READ_T_FLOOR"
  fails=$((fails+1))
else
  check "min declared hooks/scripts/ timeout ($min_timeout) >= read -t $READ_T_FLOOR floor" "ok" "ok"
fi

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
