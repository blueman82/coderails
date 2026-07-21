#!/bin/bash
# Guard test: every declared hooks.json timeout for hooks/scripts/ commands must
# be >= 5 (the `read -t 5` in-process backstop floor added in PR #76).
# If a timeout is declared BELOW 5, the harness kills the hook before the
# in-process backstop can fire, silently breaking the invariant.
# Hooks with NO declared timeout use Claude Code's default (60s) — safe, excluded.
#
# Also guards the OTHER half of the invariant (PR #79): every hook script that
# contains the bounded-read backstop must use exactly `read -t READ_T_FLOOR`.
# This makes both halves tamper-evident:
#   half A: min(hooks.json declared timeout) >= floor
#   half B: every hook's actual `read -t N` value == floor
#
# Usage: bash hooks_json_timeout_floor.test.sh [path/to/hooks.json]
#   Default path: hooks/hooks.json relative to the repo root (two dirs up).
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
HOOKS_JSON="${1:-$REPO_ROOT/hooks/hooks.json}"
READ_T_FLOOR=5
EXPECTED_BACKSTOP_COUNT=16

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

# --- Half B: assert every hook's `read -t N` backstop matches READ_T_FLOOR ---
# Discover all hook scripts in hooks/scripts/ that contain the bounded-read backstop idiom,
# excluding tests/ and lib/ subdirectories.
SCRIPTS_DIR="$REPO_ROOT/hooks/scripts"

# Collect hook files containing the backstop idiom; one file per line.
backstop_files=$(grep -rl "IFS= read -r -d '' -t" "$SCRIPTS_DIR" --include="*.sh" \
  | grep -v "/tests/" | grep -v "/lib/" | sort)

backstop_count=$(echo "$backstop_files" | grep -c . 2>/dev/null)

# Assert backstop count == EXPECTED_BACKSTOP_COUNT (14 known hooks).
if [ "$backstop_count" -ne "$EXPECTED_BACKSTOP_COUNT" ]; then
  printf 'FAIL - expected %d hook scripts with the bounded-read backstop, found %d — a hook may have gained or lost the backstop unexpectedly\n' \
    "$EXPECTED_BACKSTOP_COUNT" "$backstop_count"
  fails=$((fails+1))
else
  check "exactly $EXPECTED_BACKSTOP_COUNT hook scripts carry the bounded-read backstop" "ok" "ok"
fi

# Assert every hook's read -t value equals READ_T_FLOOR.
while IFS= read -r hook_file; do
  [ -z "$hook_file" ] && continue
  # Extract the integer N from `IFS= read -r -d '' -t N` — tolerates end-of-line (no trailing token).
  n=$(grep "IFS= read -r -d '' -t" "$hook_file" \
      | grep -oE "read -r -d '' -t [0-9]+" | grep -oE '[0-9]+$' | head -1)
  hook_name=$(basename "$hook_file")
  if [ "$n" != "$READ_T_FLOOR" ]; then
    printf 'FAIL - %s uses read -t %s but floor is %d — both halves of the timeout invariant must match\n' \
      "$hook_name" "$n" "$READ_T_FLOOR"
    fails=$((fails+1))
  else
    check "$hook_name: read -t $n == floor ($READ_T_FLOOR)" "ok" "ok"
  fi
done <<< "$backstop_files"

# --- Guard: UserPromptSubmit registers exactly two hooks (inject_context.sh,
# crack_on_gate.sh) ---
# discipline_catchup.sh was retired with no shim/flag/fallback (clean break);
# this pins the registration so a re-add or a stray extra entry fails loud.
# crack_on_gate.sh joined as the deliberate second entry (raw-prompt crack-on
# stamping — a SEPARATE hook, not a change to inject_context's job).
# Checks the matcher-array length too — a re-add as a SECOND matcher object
# (UserPromptSubmit[1]) would otherwise sail past a check that only looks
# inside [0].hooks.
ups_matchers=$(jq -r '.hooks.UserPromptSubmit | length' "$HOOKS_JSON")
check "UserPromptSubmit matcher-array length" "1" "$ups_matchers"

ups_result=$(jq -r '
  .hooks.UserPromptSubmit[0].hooks
  | "\(length) \(.[0].command) \(.[1].command // "missing")"
' "$HOOKS_JSON")
ups_count=$(echo "$ups_result" | awk '{print $1}')
ups_cmd0=$(echo "$ups_result" | awk '{print $2}')
ups_cmd1=$(echo "$ups_result" | awk '{print $3}')

check "UserPromptSubmit[0].hooks length" "2" "$ups_count"
case "$ups_cmd0" in
  *inject_context.sh*) check "UserPromptSubmit[0] hook 1 references inject_context.sh" "ok" "ok" ;;
  *) check "UserPromptSubmit[0] hook 1 references inject_context.sh" "ok" "FAIL:$ups_cmd0" ;;
esac
case "$ups_cmd1" in
  *crack_on_gate.sh*) check "UserPromptSubmit[0] hook 2 references crack_on_gate.sh" "ok" "ok" ;;
  *) check "UserPromptSubmit[0] hook 2 references crack_on_gate.sh" "ok" "FAIL:$ups_cmd1" ;;
esac

# --- Guard: plugin.json and marketplace.json versions stay in lockstep ---
# PR #155 bumped only plugin.json, breaking the invariant; this pins both
# together so a future single-file bump fails loud instead of drifting again.
# Both jq reads degrade identically on a missing file or absent key (empty
# string, or the literal "null") — an equality check alone would pass
# vacuously in that case instead of catching the underlying breakage, so each
# side must first be asserted non-empty and not "null".
PLUGIN_JSON="$REPO_ROOT/.claude-plugin/plugin.json"
MARKETPLACE_JSON="$REPO_ROOT/.claude-plugin/marketplace.json"
plugin_version=$(jq -r '.version' "$PLUGIN_JSON" 2>/dev/null)
marketplace_version=$(jq -r '.plugins[0].version' "$MARKETPLACE_JSON" 2>/dev/null)

if [ -z "$plugin_version" ] || [ "$plugin_version" = "null" ]; then
  printf 'FAIL - could not read a version from %s (got [%s])\n' "$PLUGIN_JSON" "$plugin_version"
  fails=$((fails+1))
elif [ -z "$marketplace_version" ] || [ "$marketplace_version" = "null" ]; then
  printf 'FAIL - could not read a version from %s (got [%s])\n' "$MARKETPLACE_JSON" "$marketplace_version"
  fails=$((fails+1))
else
  check "plugin.json version ($plugin_version) matches marketplace.json plugin version ($marketplace_version)" "$plugin_version" "$marketplace_version"
fi

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
