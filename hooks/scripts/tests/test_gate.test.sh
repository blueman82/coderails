#!/bin/bash
# Behavioural test for test_gate.sh — feeds synthetic PreToolUse Bash payloads
# from temp project directories with/without .claude/test_command and asserts
# allow (exit 0) vs deny (permissionDecision=deny).
set -u
HOOK="$(cd "$(dirname "$0")/.." && pwd)/test_gate.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fails=0

# test_gate.sh reads ".claude/test_command" relative to its cwd (the project root).
# We simulate this by running the hook from a scratch project directory.

payload() { # command -> json
  jq -n --arg cmd "$1" '{"tool_name":"Bash","tool_input":{"command":$cmd}}'
}

run_from() { # dir json -> DENY|ALLOW
  local dir="$1" json="$2" out
  out=$(cd "$dir" && printf '%s' "$json" | bash "$HOOK" 2>/dev/null)
  if printf '%s' "$out" | grep -q '"permissionDecision": *"deny"'; then echo DENY; else echo ALLOW; fi
}

check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# --- Project with no .claude/test_command ---
PROJ_NONE="$TMP/proj_none"
mkdir -p "$PROJ_NONE"

check "no config, git commit -> allow" ALLOW "$(run_from "$PROJ_NONE" "$(payload "git commit -m 'fix'")")"
check "no config, git status -> allow" ALLOW "$(run_from "$PROJ_NONE" "$(payload "git status")")"

# --- Project with .claude/test_command and a PASSING test command ---
PROJ_PASS="$TMP/proj_pass"
mkdir -p "$PROJ_PASS/.claude"
printf 'true\n' > "$PROJ_PASS/.claude/test_command"   # 'true' always succeeds

check "passing tests, git commit -> allow" ALLOW "$(run_from "$PROJ_PASS" "$(payload "git commit -m 'fix'")")"
check "passing tests, non-commit -> allow" ALLOW "$(run_from "$PROJ_PASS" "$(payload "git status")")"

# --- Project with .claude/test_command and a FAILING test command ---
PROJ_FAIL="$TMP/proj_fail"
mkdir -p "$PROJ_FAIL/.claude"
printf 'false\n' > "$PROJ_FAIL/.claude/test_command"  # 'false' always fails

check "failing tests, git commit -> deny" DENY "$(run_from "$PROJ_FAIL" "$(payload "git commit -m 'fix'")")"
check "failing tests, non-commit cmd -> allow" ALLOW "$(run_from "$PROJ_FAIL" "$(payload "ls -la")")"
check "failing tests, git push -> allow"  ALLOW "$(run_from "$PROJ_FAIL" "$(payload "git push origin main")")"

# --- Project with empty .claude/test_command ---
PROJ_EMPTY="$TMP/proj_empty"
mkdir -p "$PROJ_EMPTY/.claude"
: > "$PROJ_EMPTY/.claude/test_command"   # empty file

check "empty test_command, git commit -> allow" ALLOW "$(run_from "$PROJ_EMPTY" "$(payload "git commit -m 'fix'")")"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
