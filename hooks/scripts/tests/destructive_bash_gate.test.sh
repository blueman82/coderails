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

# payload_with_cwd <command> <cwd> -> json (for branch-aware tests)
payload_with_cwd() {
  jq -n --arg cmd "$1" --arg cwd "$2" '{"tool_name":"Bash","tool_input":{"command":$cmd},"cwd":$cwd}'
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

# --- Change #4: extended destructive blocklist ---
# git clean with force flags
check "git clean -fdx -> deny"      DENY  "$(run "$(payload "git clean -fdx")")"
check "git clean -f -> deny"        DENY  "$(run "$(payload "git clean -f .")")"
check "git clean -fd -> deny"       DENY  "$(run "$(payload "git clean -fd src/")")"
check "git clean -xf -> deny"       DENY  "$(run "$(payload "git clean -xf")")"
# benign git clean lookalikes
check "git cleanup script -> allow" ALLOW "$(run "$(payload "bash git-cleanup.sh")")"
check "git clean (no force) -> allow" ALLOW "$(run "$(payload "git clean -n")")"
check "git clean -n -> allow"       ALLOW "$(run "$(payload "git clean -n -d")")"
# find --delete / -delete
check "find -delete -> deny"        DENY  "$(run "$(payload "find . -name '*.tmp' -delete")")"
check "find --delete -> deny"       DENY  "$(run "$(payload "find /tmp --delete")")"
# benign find
check "findings -> allow"           ALLOW "$(run "$(payload "cat findings.txt")")"
check "find without delete -> allow" ALLOW "$(run "$(payload "find . -name '*.sh'")")"
# truncate -s
check "truncate -s0 -> deny"        DENY  "$(run "$(payload "truncate -s0 logfile.txt")")"
check "truncate -s 0 -> deny"       DENY  "$(run "$(payload "truncate -s 0 logfile.txt")")"
# shred
check "shred file -> deny"          DENY  "$(run "$(payload "shred secret.key")")"
check "shred -u -> deny"            DENY  "$(run "$(payload "shred -u credentials.txt")")"

# --- Change #3: branch-aware in-Bash source edits on main ---
# Set up a temp git repo on main and one on a feature branch for testing.
MAIN_REPO="$TMP/main_repo"
FEAT_REPO="$TMP/feat_repo"

git init "$MAIN_REPO" -q
git -C "$MAIN_REPO" checkout -b main -q 2>/dev/null || true

git init "$FEAT_REPO" -q
git -C "$FEAT_REPO" checkout -b feat/my-feature -q 2>/dev/null || git -C "$FEAT_REPO" checkout -b feat/my-feature 2>/dev/null || true

run_cwd() { # payload_json cwd -> DENY|ALLOW
  local out
  out=$(printf '%s' "$1" | bash "$HOOK" 2>/dev/null)
  if printf '%s' "$out" | grep -q '"permissionDecision": *"deny"'; then echo DENY; else echo ALLOW; fi
}

# on main — sed -i on a source file -> DENY
check "main: sed -i on .py -> deny"   DENY  "$(run_cwd "$(payload_with_cwd "sed -i 's/a/b/' foo.py" "$MAIN_REPO")" "$MAIN_REPO")"
# on main — redirect > into a .ts file -> DENY
check "main: redirect > .ts -> deny"  DENY  "$(run_cwd "$(payload_with_cwd "echo x > bar.ts" "$MAIN_REPO")" "$MAIN_REPO")"
# on main — tee into a SKILL.md -> DENY
check "main: tee SKILL.md -> deny"    DENY  "$(run_cwd "$(payload_with_cwd "tee skills/mything/SKILL.md" "$MAIN_REPO")" "$MAIN_REPO")"
# on main — tee into a command -> DENY
check "main: tee commands/x.md -> deny" DENY "$(run_cwd "$(payload_with_cwd "tee commands/prep.md" "$MAIN_REPO")" "$MAIN_REPO")"
# on main — sed -i on README.md (non-source) -> ALLOW
check "main: sed -i README.md -> allow" ALLOW "$(run_cwd "$(payload_with_cwd "sed -i 's/a/b/' README.md" "$MAIN_REPO")" "$MAIN_REPO")"
# on feature branch — same commands -> ALLOW
check "feat: sed -i on .py -> allow"  ALLOW "$(run_cwd "$(payload_with_cwd "sed -i 's/a/b/' foo.py" "$FEAT_REPO")" "$FEAT_REPO")"
check "feat: redirect > .ts -> allow" ALLOW "$(run_cwd "$(payload_with_cwd "echo x > bar.ts" "$FEAT_REPO")" "$FEAT_REPO")"
check "feat: tee SKILL.md -> allow"   ALLOW "$(run_cwd "$(payload_with_cwd "tee skills/mything/SKILL.md" "$FEAT_REPO")" "$FEAT_REPO")"
# perl -i on main -> DENY
check "main: perl -i on .go -> deny"  DENY  "$(run_cwd "$(payload_with_cwd "perl -i -pe 's/old/new/g' main.go" "$MAIN_REPO")" "$MAIN_REPO")"
# >> append into source on main -> DENY
check "main: >> into .js -> deny"     DENY  "$(run_cwd "$(payload_with_cwd "echo 'foo' >> app.js" "$MAIN_REPO")" "$MAIN_REPO")"

# --- F1: git clean long/separated force flags ---
check "git clean --force -> deny"          DENY  "$(run "$(payload "git clean --force")")"
check "git clean -d -f -> deny"            DENY  "$(run "$(payload "git clean -d -f")")"
check "git clean -d --force -> deny"       DENY  "$(run "$(payload "git clean -d --force")")"
check "git clean bare -> allow"            ALLOW "$(run "$(payload "git clean")")"
check "git clean --dry-run -> allow"       ALLOW "$(run "$(payload "git clean --dry-run")")"
check "git clean -i -> allow"              ALLOW "$(run "$(payload "git clean -i")")"

# --- F2: truncate --size long flag ---
check "truncate --size=0 x -> deny"        DENY  "$(run "$(payload "truncate --size=0 file.txt")")"
check "truncate --size 0 x -> deny"        DENY  "$(run "$(payload "truncate --size 0 file.txt")")"

# --- F3: cwd fallback (cwd absent → hook resolves branch from $PWD) ---
# When .cwd is absent, the hook falls back to $PWD (destructive_bash_gate.sh:96).
# The branch outcome therefore depends on $PWD, so we pin $PWD to a known repo via
# a subshell `cd` rather than relying on the ambient branch of the coderails
# checkout — which previously made this test flip ALLOW/DENY depending on whether
# coderails itself was on main.
check "no-cwd payload, PWD on feat -> allow" ALLOW "$(cd "$FEAT_REPO" && run "$(payload "sed -i 's/a/b/' foo.py")")"
check "no-cwd payload, PWD on main -> deny"  DENY  "$(cd "$MAIN_REPO" && run "$(payload "sed -i 's/a/b/' foo.py")")"

# --- F3: target-repo resolution (file in feature-branch repo, session cwd on main) ---
# Target file is in FEAT_REPO (on a feature branch). The hook must not over-block.
check "F3 feature-repo target, main cwd -> allow" ALLOW "$(run_cwd "$(payload_with_cwd "sed -i 's/a/b/' $FEAT_REPO/foo.py" "$MAIN_REPO")" "$MAIN_REPO")"

# --- F4: redirect extension anchored to end-of-token ---
check "F4 echo > output.go.log -> allow"        ALLOW "$(run_cwd "$(payload_with_cwd "echo x > output.go.log" "$MAIN_REPO")" "$MAIN_REPO")"
check "F4 echo > foo.py.bak -> allow"           ALLOW "$(run_cwd "$(payload_with_cwd "echo x > foo.py.bak" "$MAIN_REPO")" "$MAIN_REPO")"
check "F4 echo > changes.py.txt -> allow"       ALLOW "$(run_cwd "$(payload_with_cwd "echo x > changes.py.txt" "$MAIN_REPO")" "$MAIN_REPO")"
check "F4 echo > real.py -> deny"               DENY  "$(run_cwd "$(payload_with_cwd "echo x > real.py" "$MAIN_REPO")" "$MAIN_REPO")"
check "F4 find && echo --delete -> allow"       ALLOW "$(run "$(payload "find . -name x && echo --delete")")"
check "F4 find; rm --delete-like -> allow"      ALLOW "$(run "$(payload "find . -name tmp; echo done --delete-style")")"

# --- F5: cp/mv/dd write-to-source on main vs feature branch ---
check "F5 main: cp to foo.py -> deny"           DENY  "$(run_cwd "$(payload_with_cwd "cp /tmp/x foo.py" "$MAIN_REPO")" "$MAIN_REPO")"
check "F5 main: mv to foo.go -> deny"           DENY  "$(run_cwd "$(payload_with_cwd "mv /tmp/x foo.go" "$MAIN_REPO")" "$MAIN_REPO")"
check "F5 main: dd of=foo.py -> deny"           DENY  "$(run_cwd "$(payload_with_cwd "dd of=foo.py if=/tmp/x" "$MAIN_REPO")" "$MAIN_REPO")"
check "F5 feat: cp to foo.py -> allow"          ALLOW "$(run_cwd "$(payload_with_cwd "cp /tmp/x foo.py" "$FEAT_REPO")" "$FEAT_REPO")"
check "F5 feat: mv to foo.go -> allow"          ALLOW "$(run_cwd "$(payload_with_cwd "mv /tmp/x foo.go" "$FEAT_REPO")" "$FEAT_REPO")"
check "F5 feat: dd of=foo.py -> allow"          ALLOW "$(run_cwd "$(payload_with_cwd "dd of=foo.py if=/tmp/x" "$FEAT_REPO")" "$FEAT_REPO")"
check "F5 main: cp to SKILL.md -> deny"         DENY  "$(run_cwd "$(payload_with_cwd "cp /tmp/x skills/mything/SKILL.md" "$MAIN_REPO")" "$MAIN_REPO")"
check "F5 main: mv to commands/x.md -> deny"    DENY  "$(run_cwd "$(payload_with_cwd "mv /tmp/x commands/prep.md" "$MAIN_REPO")" "$MAIN_REPO")"
# cp/mv to a non-source file on main -> allow
check "F5 main: cp to README.md -> allow"       ALLOW "$(run_cwd "$(payload_with_cwd "cp /tmp/x README.md" "$MAIN_REPO")" "$MAIN_REPO")"

# --- F6: backtick/$() command-substitution in workflow-script free-text args ---
# push.sh/merge.sh/post_review.sh/post_evals.sh take a free-text message argument.
# A backtick or $() inside that argument executes as live command substitution
# when the invoking command line is interpolated into bash — the same injection
# class as the $ARGUMENTS render-time bug (PR #97), but triggered by the model's
# own Bash tool_input rather than a render-time !`cmd` line.
check "F6 push.sh with backtick in message -> deny" DENY \
  "$(run "$(payload 'bash "scripts/push.sh" "fix thing, uses \`git rev-parse\` under the hood"')")"
check "F6 push.sh with \$(...) in message -> deny" DENY \
  "$(run "$(payload 'bash "scripts/push.sh" "fix thing, runs $(whoami) as part of it"')")"
check "F6 merge.sh with backtick in message -> deny" DENY \
  "$(run "$(payload 'bash "scripts/merge.sh" "19" "note: \`rm -rf /\` should never run"')")"
check "F6 post_review.sh with backtick -> deny" DENY \
  "$(run "$(payload 'bash "scripts/post_review.sh" validate "/tmp/x" "uses \`foo\`"')")"
check "F6 post_evals.sh with backtick -> deny" DENY \
  "$(run "$(payload 'bash "scripts/post_evals.sh" validate-structure "/tmp/x.json" "19" "\`sha\`"')")"
# Clean invocations (no backtick/$()) must still be allowed.
check "F6 push.sh clean message -> allow" ALLOW \
  "$(run "$(payload 'bash "scripts/push.sh" "fix thing, uses git rev-parse show-toplevel under the hood"')")"
check "F6 merge.sh clean args -> allow" ALLOW \
  "$(run "$(payload 'bash "scripts/merge.sh" "19"')")"
# Backticks/$() in unrelated commands (not these 4 scripts) must not be blocked by this check.
check "F6 unrelated command with backtick -> allow" ALLOW \
  "$(run "$(payload 'echo "just a note about \`code\` formatting"')")"

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
