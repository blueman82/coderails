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
# $REPO is a plugin repo — it carries the plugin marker. The markdown arm only
# gates files whose repo has this marker; the code arm gates regardless.
mkdir -p "$REPO/.claude-plugin"
printf '{"name":"test"}\n' > "$REPO/.claude-plugin/plugin.json"

# $WIKI — a SEPARATE, non-plugin repo that happens to have commands/ and skills/
# dirs (like the coderails wiki). On main, no marker. Used for the cross-repo cases.
WIKI="$TMP/wiki"
mkdir -p "$WIKI"
git -C "$WIKI" init -q
git -C "$WIKI" config user.email t@t.t
git -C "$WIKI" config user.name t
git -C "$WIKI" commit -q --allow-empty -m init
git -C "$WIKI" branch -M main

# $OTHER — some unrelated repo on a feature branch, used as a MISMATCHED cwd to
# prove the branch decision keys off the file's repo, not the session cwd.
OTHER="$TMP/other"
mkdir -p "$OTHER"
git -C "$OTHER" init -q
git -C "$OTHER" config user.email t@t.t
git -C "$OTHER" config user.name t
git -C "$OTHER" commit -q --allow-empty -m init
git -C "$OTHER" checkout -q -b feature
fails=0

payload() { # tool file_path -> json (cwd defaults to $REPO)
  printf '{"tool_name":"%s","tool_input":{"file_path":"%s"},"cwd":"%s"}' "$1" "$2" "$REPO"
}
payload_cwd() { # tool file_path cwd -> json (explicit cwd, for cross-repo cases)
  printf '{"tool_name":"%s","tool_input":{"file_path":"%s"},"cwd":"%s"}' "$1" "$2" "$3"
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

# On main, plugin source carried in markdown is gated like code (skills/*/SKILL.md, commands/*.md).
check "main, skills SKILL.md (relative) -> deny" DENY "$(run "$(payload Edit skills/agentic-loop/SKILL.md)")"
check "main, skills SKILL.md (absolute) -> deny" DENY "$(run "$(payload Edit "$REPO/skills/foo/SKILL.md")")"
check "main, commands .md edit -> deny"          DENY "$(run "$(payload Edit commands/push.md)")"

# On main, plain docs/config still pass (carve-out narrowed to plugin source only, not all .md).
check "main, README.md edit -> allow"        ALLOW "$(run "$(payload Edit README.md)")"
check "main, docs/REFERENCE.md edit -> allow" ALLOW "$(run "$(payload Edit docs/REFERENCE.md)")"
check "main, other skill .md (not SKILL) -> allow" ALLOW "$(run "$(payload Edit skills/foo/references/x.md)")"
check "main, .json edit -> allow" ALLOW "$(run "$(payload Write config.json)")"

# Plugin-source markdown on a feature branch is allowed (branch check still applies).
checkout feature
check "feature branch, SKILL.md edit -> allow" ALLOW "$(run "$(payload Edit skills/agentic-loop/SKILL.md)")"
checkout main

# Empty file_path -> nothing to judge -> allow.
check "main, empty file_path -> allow" ALLOW "$(run "$(payload Edit "")")"

# master is treated like main (alternate default branch name).
checkout master
check "master, .js edit -> deny" DENY "$(run "$(payload MultiEdit web/x.js)")"
checkout main

# ─── Cross-repo cases (the bug this fix addresses) ──────────────────────────────
# The decision must key off the FILE's repo, and the markdown arm must require the
# plugin marker. $REPO stays on main throughout; the wiki is a separate repo.

# False-positive fix: a non-plugin repo's commands/skills markdown is NOT plugin
# source — never gated, even on its own main, even when the session cwd is $REPO
# (coderails) sitting on main. This is the exact reported incident.
check "wiki commands/*.md, cwd=coderails-on-main -> allow" \
  ALLOW "$(run "$(payload_cwd Edit "$WIKI/commands/init.md" "$REPO")")"
check "wiki skills/*/SKILL.md, cwd=coderails-on-main -> allow" \
  ALLOW "$(run "$(payload_cwd Edit "$WIKI/skills/foo/SKILL.md" "$REPO")")"

# No gap: code files ARE gated in ANY repo on main, marker or not — the code arm
# is a universal discipline, unaffected by the marker.
check "wiki .py on main (no marker) -> deny" \
  DENY "$(run "$(payload_cwd Edit "$WIKI/src/app.py" "$REPO")")"

# False-negative fix: genuine plugin markdown on main is gated even when the
# session cwd is a DIFFERENT repo on a feature branch (old code keyed off cwd and
# wrongly allowed this).
check "plugin commands/*.md on main, cwd=other-on-feature -> deny" \
  DENY "$(run "$(payload_cwd Edit "$REPO/commands/push.md" "$OTHER")")"

# Walk-up terminates OUTSIDE any git repo: an absolute path whose entire ancestry is
# non-git ($TMP itself is not a repo) -> branch comes back empty -> allow (the safe
# fail-open direction). Exercises the loop's "/" / non-empty guards + the non-repo path.
check "code file under non-git ancestry -> allow" \
  ALLOW "$(run "$(payload_cwd Edit "$TMP/loose/dir/app.py" "$REPO")")"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
