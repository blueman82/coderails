#!/bin/bash
# Behavioural test for verification_volume_ceiling.sh -- feeds synthetic
# PreToolUse Bash payloads and asserts the 1st/2nd invocation of
# hooks/scripts/tests/run_all.sh or a post_evals.sh validate-structure
# ceremony is allowed, and the 3rd+ is denied, per git branch.
set -u
HOOK="$(cd "$(dirname "$0")/.." && pwd)/verification_volume_ceiling.sh"
TMP=$(mktemp -d)
trap 'unlink_tree_exit' EXIT
fails=0

unlink_tree_exit() {
  find "$TMP" -type f -exec unlink {} \; 2>/dev/null
  find "$TMP" -depth -type d -exec rmdir {} \; 2>/dev/null
}

unlink_tree() {
  find "$1" -type f -exec unlink {} \; 2>/dev/null
  find "$1" -depth -type d -exec rmdir {} \; 2>/dev/null
}

new_fixture() { # branch_name -> prints fixture dir path
  local dir br="$1"
  dir=$(mktemp -d -p "$TMP")
  ( cd "$dir" && git init -q && git checkout -q -b "$br" ) >/dev/null 2>&1
  printf '%s' "$dir"
}

decision() { # cwd cmd -> "allow" | "deny"
  local cwd="$1" cmd="$2" out
  out=$(jq -n --arg cwd "$cwd" --arg cmd "$cmd" '{tool_name:"Bash",tool_input:{command:$cmd},cwd:$cwd}' | bash "$HOOK" 2>/dev/null)
  if [ -z "$out" ]; then
    printf 'allow'
    return
  fi
  printf '%s' "$out" | jq -r '.hookSpecificOutput.permissionDecision // "allow"'
}

check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# --- run_all.sh cap: 1st/2nd allow, 3rd deny, one branch ---
F1=$(new_fixture "unit-run-all")
STATE1=$(mktemp -d -p "$TMP")
export CLAUDE_AGENTIC_LOOP_DIR="$STATE1"
RA_CMD="bash hooks/scripts/tests/run_all.sh"
check "run_all.sh call 1 -> allow" allow "$(decision "$F1" "$RA_CMD")"
check "run_all.sh call 2 -> allow" allow "$(decision "$F1" "$RA_CMD")"
check "run_all.sh call 3 -> deny"  deny  "$(decision "$F1" "$RA_CMD")"
check "run_all.sh call 4 -> still deny" deny "$(decision "$F1" "$RA_CMD")"
unset CLAUDE_AGENTIC_LOOP_DIR

# --- post_evals.sh validate-structure cap: 1st/2nd allow, 3rd deny ---
F2=$(new_fixture "unit-post-evals")
STATE2=$(mktemp -d -p "$TMP")
export CLAUDE_AGENTIC_LOOP_DIR="$STATE2"
PE_CMD="./scripts/post_evals.sh validate-structure evals.json 5 abc123"
check "post_evals.sh validate-structure call 1 -> allow" allow "$(decision "$F2" "$PE_CMD")"
check "post_evals.sh validate-structure call 2 -> allow" allow "$(decision "$F2" "$PE_CMD")"
check "post_evals.sh validate-structure call 3 -> deny"  deny  "$(decision "$F2" "$PE_CMD")"
unset CLAUDE_AGENTIC_LOOP_DIR

# --- Other post_evals.sh subcommands are never counted or denied ---
F3=$(new_fixture "unit-other-subcommands")
STATE3=$(mktemp -d -p "$TMP")
export CLAUDE_AGENTIC_LOOP_DIR="$STATE3"
for i in 1 2 3 4 5; do
  check "compute-result call $i -> allow" allow "$(decision "$F3" "./scripts/post_evals.sh compute-result evals.json")"
done
for i in 1 2 3 4 5; do
  check "validate-discriminating call $i -> allow" allow "$(decision "$F3" "./scripts/post_evals.sh validate-discriminating evals.json")"
done
for i in 1 2 3 4 5; do
  check "validate-embed call $i -> allow" allow "$(decision "$F3" "./scripts/post_evals.sh validate-embed evals.json /tmp/body.md")"
done
unset CLAUDE_AGENTIC_LOOP_DIR

# --- Per-branch isolation: unit A's calls don't leak into unit B's counter ---
FA=$(new_fixture "unit-a")
FB=$(new_fixture "unit-b")
STATE4=$(mktemp -d -p "$TMP")
export CLAUDE_AGENTIC_LOOP_DIR="$STATE4"
check "unit A call 1 -> allow" allow "$(decision "$FA" "$RA_CMD")"
check "unit A call 2 -> allow" allow "$(decision "$FA" "$RA_CMD")"
check "unit B call 1 -> allow (isolated from A)" allow "$(decision "$FB" "$RA_CMD")"
unset CLAUDE_AGENTIC_LOOP_DIR

# --- Mention, not invocation: grep/cat/echo referencing the path never counts ---
F5=$(new_fixture "unit-mentions")
STATE5=$(mktemp -d -p "$TMP")
export CLAUDE_AGENTIC_LOOP_DIR="$STATE5"
for i in 1 2 3 4 5; do
  check "grep mention $i -> allow" allow "$(decision "$F5" "grep -n run_all.sh hooks/hooks.json")"
done
for i in 1 2 3 4 5; do
  check "cat mention $i -> allow" allow "$(decision "$F5" "cat hooks/scripts/tests/run_all.sh")"
done
unset CLAUDE_AGENTIC_LOOP_DIR

# --- Unrelated Bash calls never trip the gate ---
F6=$(new_fixture "unit-unrelated")
STATE6=$(mktemp -d -p "$TMP")
export CLAUDE_AGENTIC_LOOP_DIR="$STATE6"
for i in 1 2 3; do
  check "unrelated npm test $i -> allow" allow "$(decision "$F6" "npm test")"
done
unset CLAUDE_AGENTIC_LOOP_DIR

if [ "$fails" -eq 0 ]; then
  echo "PASS"
else
  echo "FAILED ($fails)"
fi
[ "$fails" -eq 0 ]
