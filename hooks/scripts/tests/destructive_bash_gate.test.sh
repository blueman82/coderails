#!/bin/bash
# Behavioural test for destructive_bash_gate.sh — feeds synthetic PreToolUse Bash
# payloads and asserts allow (no deny JSON) vs deny (permissionDecision=deny).
set -u
HOOK="$(cd "$(dirname "$0")/.." && pwd)/destructive_bash_gate.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fails=0

payload() { # command -> json
  jq -n --arg cmd "$1" '{"tool_name":"Bash","tool_input":{"command":$cmd}}'
}

run() { # json -> DENY|ALLOW
  local out
  out=$(printf '%s' "$1" | bash "$HOOK" 2>/dev/null)
  if printf '%s' "$out" | grep -q '"permissionDecision": *"deny"'; then echo DENY; else echo ALLOW; fi
}

check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# --- Blocked commands ---
check "rm -rf x -> deny"            DENY "$(run "$(payload "rm -rf /tmp/x")")"
check "rm -rf . -> deny"            DENY "$(run "$(payload "rm -rf .")")"
check "rm -r somedir -> deny"       DENY "$(run "$(payload "rm -r somedir")")"
check "git push --force -> deny"    DENY "$(run "$(payload "git push --force")")"
check "git push -f -> deny"         DENY "$(run "$(payload "git push origin main -f")")"
check "git push --force-with-lease -> deny" DENY "$(run "$(payload "git push --force-with-lease")")"
check "git reset --hard -> deny"    DENY "$(run "$(payload "git reset --hard HEAD~1")")"
check "DROP TABLE -> deny"          DENY "$(run "$(payload "DROP TABLE users;")")"
check "DROP DATABASE -> deny"       DENY "$(run "$(payload "DROP DATABASE mydb;")")"
check "TRUNCATE TABLE -> deny"      DENY "$(run "$(payload "TRUNCATE TABLE logs;")")"
check "dd if= -> deny"              DENY "$(run "$(payload "dd if=/dev/zero of=/dev/sda")")"
check "mkfs. -> deny"               DENY "$(run "$(payload "mkfs.ext4 /dev/sdb1")")"
check "chmod -R 777 -> deny"        DENY "$(run "$(payload "chmod -R 777 /var/www")")"
check "git commit --no-verify -> deny" DENY "$(run "$(payload "git commit -m 'wip' --no-verify")")"

# --- Allowed commands ---
check "ls -> allow"                 ALLOW "$(run "$(payload "ls -la")")"
check "git status -> allow"         ALLOW "$(run "$(payload "git status")")"
check "git push (no force) -> allow" ALLOW "$(run "$(payload "git push origin main")")"
check "git reset --soft -> allow"   ALLOW "$(run "$(payload "git reset --soft HEAD~1")")"
check "git commit (no --no-verify) -> allow" ALLOW "$(run "$(payload "git commit -m 'fix'")")"
check "echo hello -> allow"         ALLOW "$(run "$(payload "echo hello")")"
check "cat file.txt -> allow"       ALLOW "$(run "$(payload "cat file.txt")")"

# --- Edge cases ---
check "empty command -> allow"      ALLOW "$(run '{"tool_input":{"command":""}}')"
check "no command field -> allow"   ALLOW "$(run '{"tool_input":{}}')"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
