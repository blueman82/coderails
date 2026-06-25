#!/bin/bash
# Behavioural test for no_edit_on_main.sh — feeds synthetic PreToolUse payloads
# against a temp git repo on a known branch and asserts allow vs deny. All state
# lives under a temp dir, never the repo tree.
set -u
HOOK="$(cd "$(dirname "$0")/.." && pwd)/no_edit_on_main.sh"
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
export CLAUDE_DISCIPLINE_LOG="$TMP/discipline.log"
REPO="$TMP/repo"
mkdir -p "$REPO"
git -C "$REPO" init -q
git -C "$REPO" config user.email t@t.t
git -C "$REPO" config user.name t
git -C "$REPO" commit -q --allow-empty -m init
git -C "$REPO" branch -M main
fails=0

payload() { # tool file_path -> json
  printf '{"tool_name":"%s","tool_input":{"file_path":"%s"},"cwd":"%s"}' "$1" "$2" "$REPO"
}
checkout() { git -C "$REPO" checkout -q "$1" 2>/dev/null || git -C "$REPO" checkout -q -b "$1"; }
run() { # payload -> DENY|ALLOW
  local out
  out=$(printf '%s' "$1" | bash "$HOOK" 2>/dev/null)
  if printf '%s' "$out" | grep -q '"permissionDecision": *"deny"'; then echo DENY; else echo ALLOW; fi
}
check() { # desc expected actual
  if [ "$2" = "$3" ]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s (expected %s, got %s)\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# On a feature branch, code edits are allowed.
checkout feature
check "feature branch, .py edit -> allow" ALLOW "$(run "$(payload Edit src/app.py)")"

# On main, every blocked code extension is denied.
checkout main
for ext in py ts tsx js jsx go; do
  check "main, .$ext edit -> deny" DENY "$(run "$(payload Edit "src/file.$ext")")"
done

# On main, docs/config pass (the docs-only carve-out = only code exts are blocked).
check "main, .md edit -> allow"   ALLOW "$(run "$(payload Edit README.md)")"
check "main, .json edit -> allow" ALLOW "$(run "$(payload Write config.json)")"

# Empty file_path -> nothing to judge -> allow.
check "main, empty file_path -> allow" ALLOW "$(run "$(payload Edit "")")"

# master is treated like main (alternate default branch name).
checkout master
check "master, .js edit -> deny" DENY "$(run "$(payload MultiEdit web/x.js)")"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
