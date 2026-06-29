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

# --- Extract declared timeouts for hooks/scripts/ commands via jq ---
# Filter: entries whose command references hooks/scripts/ AND have a non-null timeout.
# Hooks with no declared timeout default to 60s (safe) and are intentionally excluded.
# jq computes count and min natively (handles floats correctly); bash never does -lt on a float.
jq_result=$(jq -r --argjson floor "$READ_T_FLOOR" '
  [.hooks | to_entries[] | .value[] | .hooks[]?
   | select(.command | test("hooks/scripts/"))
   | select(.timeout != null)
   | .timeout]
  | { count: length, min: (if length > 0 then min else null end),
      below_floor: (if length > 0 then (min < $floor) else false end) }
  | "\(.count) \(if .min != null then (.min | tostring) else "null" end) \(.below_floor)"
' "$HOOKS_JSON")

count=$(echo "$jq_result" | awk '{print $1}')
min_timeout=$(echo "$jq_result" | awk '{print $2}')
below_floor=$(echo "$jq_result" | awk '{print $3}')

# --- Guard: non-empty extraction required ---
if [ "$count" -eq 0 ]; then
  printf 'FAIL - no hooks/scripts/ timeouts found — jq filter may be broken or hooks.json structure changed\n'
  fails=$((fails+1))
  [ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
fi

# --- Assert each declared timeout >= READ_T_FLOOR (comparison done in jq, float-safe) ---
if [ "$below_floor" = "true" ]; then
  printf 'FAIL - hooks.json declares a timeout (%s) below the read -t %d in-process backstop floor — lower the read -t bound or raise the timeout\n' \
    "$min_timeout" "$READ_T_FLOOR"
  fails=$((fails+1))
else
  check "min declared hooks/scripts/ timeout ($min_timeout) >= read -t $READ_T_FLOOR floor" "ok" "ok"
fi

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
