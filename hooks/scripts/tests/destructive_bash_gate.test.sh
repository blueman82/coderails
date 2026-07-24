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

# run_reason: json -> the permissionDecisionReason text (empty if allowed)
run_reason() {
  printf '%s' "$1" | bash "$HOOK" 2>/dev/null | jq -r '.hookSpecificOutput.permissionDecisionReason // ""'
}

# run_pattern_id: json -> the hookSpecificOutput.patternId field (empty if allowed/absent)
run_pattern_id() {
  printf '%s' "$1" | bash "$HOOK" 2>/dev/null | jq -r '.hookSpecificOutput.patternId // ""'
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
# Combined short-flag cluster (git's own getopt-style clustering, e.g. -uf ==
# -u -f), no --force-with-lease in play at all — mirrors the file's existing
# git-clean force detector's own combined-flag handling (line 47) rather than
# only recognising -f as a standalone complete token.
check "git push -uf cluster (no fwl) -> deny" DENY "$(run "$(payload "git push -uf origin main")")"
check "git push --force-with-lease -> deny" DENY "$(run "$(payload "git push --force-with-lease")")"
check "git reset --hard -> deny"    DENY "$(run "$(payload "git reset --hard HEAD~1")")"
check "DROP TABLE -> deny"          DENY "$(run "$(payload "DROP TABLE users;")")"
check "DROP DATABASE -> deny"       DENY "$(run "$(payload "DROP DATABASE mydb;")")"
check "TRUNCATE TABLE -> deny"      DENY "$(run "$(payload "TRUNCATE TABLE logs;")")"
check "dd if= -> deny"              DENY "$(run "$(payload "dd if=/dev/zero of=/dev/sda")")"
check "mkfs. -> deny"               DENY "$(run "$(payload "mkfs.ext4 /dev/sdb1")")"
check "chmod -R 777 -> deny"        DENY "$(run "$(payload "chmod -R 777 /var/www")")"
check "git commit --no-verify -> deny" DENY "$(run "$(payload "git commit -m 'wip' --no-verify")")"

# --- Deny messages must name a concrete safe route per pattern family, not a
# single generic sentence appended to every message (the gap this file's
# deny() fix closes: a stated prohibition with no named way around it). ---
reset_reason=$(run_reason "$(payload "git reset --hard HEAD~1")")
check "git reset --hard message names keep+backup route" DENY \
  "$(printf '%s' "$reset_reason" | grep -qiE 'keep' && printf '%s' "$reset_reason" | grep -qiE 'backup' && echo DENY || echo MISSING)"

rm_reason=$(run_reason "$(payload "rm -rf /tmp/x")")
check "rm -rf message names unlink+temp route" DENY \
  "$(printf '%s' "$rm_reason" | grep -qiE 'unlink' && printf '%s' "$rm_reason" | grep -qiE 'temp' && echo DENY || echo MISSING)"

push_reason=$(run_reason "$(payload "git push --force origin main")")
check "git push --force message names force-with-lease route" DENY \
  "$(printf '%s' "$push_reason" | grep -qiE 'force-with-lease' && printf '%s' "$push_reason" | grep -qiE 'allowlist' && echo DENY || echo MISSING)"

# The force-with-lease route the message recommends must not itself be a dead
# end: the hook denies --force-with-lease BY DEFAULT (no allowlist file), so
# the message must say so and name the opt-in step — not just the bare flag.
check "push message flags that fwl is itself blocked without the allowlist opt-in" DENY \
  "$(printf '%s' "$push_reason" | grep -qi 'destructive_allowlist' && echo DENY || echo MISSING)"

# --- Deliverable A: a route for every remaining blockable pattern. Each check
# asserts the deny message contains a route AND does NOT contain the generic
# "No specific safe route is recorded" fallback text — the two-part test the
# task calls for, so a pattern that never got a route arm (falling through to
# the generic case) fails here rather than passing silently.
assert_specific_route() { # description command must_contain...
  local desc="$1" cmd="$2"
  shift 2
  local reason
  reason=$(run_reason "$(payload "$cmd")")
  local ok=1
  if printf '%s' "$reason" | grep -qi 'no specific safe route'; then
    ok=0
  fi
  for needle in "$@"; do
    printf '%s' "$reason" | grep -qi -- "$needle" || ok=0
  done
  check "$desc" DENY "$( [ "$ok" -eq 1 ] && echo DENY || echo MISSING)"
}

# git clean (force) has a genuine safe route: the gate itself already permits
# -n (dry-run/preview) and -i (interactive) — see lines 72-76 of the gate —
# so the message must point at those rather than the generic fallback.
# Needles are multi-char, route-specific literals ('git clean -n', 'git clean
# -i', and the distinctive prose "dry-run"/"interactive prompt") rather than
# bare '-n'/'-i' — those two-char substrings match incidentally inside
# unrelated words and were proven (by a reviewer, confirmed here) to let a
# fabricated, unrelated route pass undetected.
assert_specific_route "git clean message names -n preview and -i interactive route" \
  "git clean -fdx" "git clean -n" "dry-run" "git clean -i" "interactive prompt"

# find -delete: no safe equivalent to deletion itself — honest route points at
# previewing the match set first and at the settings.json escape hatch.
# Needles are specific to THIS route's own wording (not just the shared
# "no safe equivalent"/"settings.json" phrases every honest route repeats) so
# a copy-paste-wrong route swapped in from a different pattern still fails.
assert_specific_route "find -delete message names -print preview + settings.json route" \
  "find . -name '*.tmp' -delete" "no safe equivalent" "-print" "xargs" "settings.json"

# truncate -s/--size: destroys file content, no safe equivalent — honest route.
assert_specific_route "truncate -s message names no-safe-equivalent + settings.json route" \
  "truncate -s0 logfile.txt" "no safe equivalent" "file content in place" "rotate the log" "settings.json"

# shred: secure overwrite/delete is the point of the command — no safe
# equivalent — honest route.
assert_specific_route "shred message names no-safe-equivalent + settings.json route" \
  "shred secret.key" "no safe equivalent" "unrecoverable" "securely wipe" "settings.json"

# DROP TABLE/DATABASE/SCHEMA: destructive DDL, no safe equivalent — honest route.
assert_specific_route "DROP TABLE message names no-safe-equivalent + settings.json route" \
  "DROP TABLE users;" "no safe equivalent" "destructive ddl" "settings.json"
assert_specific_route "DROP DATABASE message names no-safe-equivalent + settings.json route" \
  "DROP DATABASE mydb;" "no safe equivalent" "destructive ddl" "settings.json"
assert_specific_route "DROP SCHEMA message names no-safe-equivalent + settings.json route" \
  "DROP SCHEMA public CASCADE;" "no safe equivalent" "destructive ddl" "settings.json"

# TRUNCATE TABLE: destroys all rows, no safe equivalent — honest route.
assert_specific_route "TRUNCATE TABLE message names no-safe-equivalent + settings.json route" \
  "TRUNCATE TABLE logs;" "no safe equivalent" "removes all rows" "scoped delete" "settings.json"

# dd if=: raw block-device copy, no safe equivalent — honest route.
assert_specific_route "dd if= message names no-safe-equivalent + settings.json route" \
  "dd if=/dev/zero of=/dev/sda" "no safe equivalent" "raw bytes" "of= target" "settings.json"

# mkfs.: reformats a filesystem, no safe equivalent — honest route.
assert_specific_route "mkfs. message names no-safe-equivalent + settings.json route" \
  "mkfs.ext4 /dev/sdb1" "no safe equivalent" "reformats a filesystem" "settings.json"

# chmod -R 777: genuine safer alternative exists — narrower recursive bits.
assert_specific_route "chmod -R 777 message names narrower-permission route" \
  "chmod -R 777 /var/www" "u+rwx" "go+rx" "world-writable"

# git commit --no-verify: genuine safe alternative — fix the failing hook.
assert_specific_route "git commit --no-verify message names fix-the-hook route" \
  "git commit -m 'wip' --no-verify" "fix the failing pre-commit hook" "don't skip it"

# --- RCA item 12: .env secret-file access (read OR write) ------------------
# The gate is command-AGNOSTIC here: it matches the .env path token, not a
# list of reader/writer verbs, so every case below is a distinct BOUNDARY
# being exercised (left boundary, right boundary, suffix handling), not the
# same regex re-hit through a different verb.
#
# Every positive asserts DENY (the decision), not merely a non-zero exit —
# run() reads permissionDecision out of the hook's JSON, so a hook that
# emitted a malformed decision or simply crashed would read ALLOW and fail
# these, rather than passing on the crash.

# READS — the exfiltration direction. Verb variety here is deliberate
# coverage of the "no verb enumeration" property: a verb-list detector would
# have to name every one of these, and the awk/sed/editor cases are exactly
# the ones such a list forgets.
check ".env: cat -> deny"           DENY "$(run "$(payload "cat .env")")"
check ".env: less -> deny"          DENY "$(run "$(payload "less .env")")"
check ".env: head -> deny"          DENY "$(run "$(payload "head -5 .env")")"
check ".env: tail -> deny"          DENY "$(run "$(payload "tail .env")")"
check ".env: grep -> deny"          DENY "$(run "$(payload "grep API_KEY .env")")"
check ".env: source -> deny"        DENY "$(run "$(payload "source .env")")"
check ".env: awk -> deny"           DENY "$(run "$(payload "awk '{print}' .env")")"
check ".env: editor -> deny"        DENY "$(run "$(payload "nano .env")")"

# WRITES — the destroy/replace direction.
check ".env: redirect > -> deny"    DENY "$(run "$(payload "echo 'X=1' > .env")")"
check ".env: append >> -> deny"     DENY "$(run "$(payload "echo 'X=1' >> .env")")"
check ".env: no-space redirect -> deny" DENY "$(run "$(payload "echo 'X=1' >.env")")"
check ".env: cp onto it -> deny"    DENY "$(run "$(payload "cp secrets .env")")"
check ".env: mv it -> deny"         DENY "$(run "$(payload "mv .env /tmp/x")")"
check ".env: rm it -> deny"         DENY "$(run "$(payload "rm .env")")"

# LEFT-BOUNDARY path variants — each is a different left-boundary character
# class in the regex ("/" for the path forms, quote chars, "=").
check ".env: ./ relative -> deny"   DENY "$(run "$(payload "cat ./.env")")"
check ".env: ../ parent -> deny"    DENY "$(run "$(payload "cat ../.env")")"
check ".env: absolute path -> deny" DENY "$(run "$(payload "cat /Users/x/proj/.env")")"
check ".env: single-quoted -> deny" DENY "$(run "$(payload "cat '.env'")")"
check ".env: double-quoted -> deny" DENY "$(run "$(payload "cat \".env\"")")"
check ".env: VAR= assignment -> deny" DENY "$(run "$(payload "VAR=.env cat \$VAR")")"

# RIGHT-BOUNDARY: a shell separator immediately after the token (no space)
# must still terminate it — these confirm the right-boundary class, not the
# verb.
check ".env: semicolon after -> deny" DENY "$(run "$(payload "cat .env;echo done")")"
check ".env: pipe after -> deny"      DENY "$(run "$(payload "cat .env|grep KEY")")"
check ".env: && after -> deny"        DENY "$(run "$(payload "cat .env && echo ok")")"

# SUFFIXED forms — the separate bash-side suffix branch (POSIX ERE has no
# negative lookahead, so these cannot be caught by the bare-token regex).
check ".env.local -> deny"          DENY "$(run "$(payload "cat .env.local")")"
check ".env.production -> deny"     DENY "$(run "$(payload "cat .env.production")")"
# .env.local.bak: a BACKUP of a real secret file. Its first suffix segment is
# "local", so the ${suffix%%.*} first-segment comparison must still deny it —
# this is the case that a naive "allow anything with a dotted suffix" or a
# whole-suffix comparison against the template list would get wrong.
check ".env.local.bak -> deny"      DENY "$(run "$(payload "cat .env.local.bak")")"

# --- Near-miss ALLOW controls (over-blocking is the worse failure here) ----
# .envrc is direnv's file — a DIFFERENT file that shares the ".env" prefix.
# This is the single most important control in this block: it is what forces
# the right boundary to exclude word characters.
check ".envrc -> allow"             ALLOW "$(run "$(payload "cat .envrc")")"
check ".envrc via direnv -> allow"  ALLOW "$(run "$(payload "direnv allow .envrc")")"
# Committed templates — no real secrets, must stay readable.
check ".env.example -> allow"       ALLOW "$(run "$(payload "cat .env.example")")"
check ".env.sample -> allow"        ALLOW "$(run "$(payload "cat .env.sample")")"
check ".env.template -> allow"      ALLOW "$(run "$(payload "cat .env.template")")"
check ".env.dist -> allow"          ALLOW "$(run "$(payload "cat .env.dist")")"
# A docs file ABOUT the template: first suffix segment is "example", so the
# first-segment comparison allows it. A whole-suffix comparison would deny.
check ".env.example.md -> allow"    ALLOW "$(run "$(payload "cat .env.example.md")")"
# No leading dot at all — these never contain the literal ".env" as a
# dotfile token.
check "environment.yml -> allow"    ALLOW "$(run "$(payload "cat environment.yml")")"
check "env.example -> allow"        ALLOW "$(run "$(payload "cat env.example")")"
check "docs/environment.md -> allow" ALLOW "$(run "$(payload "cat docs/environment.md")")"
# Bare env / printenv — unrelated commands that print the environment.
check "bare env -> allow"           ALLOW "$(run "$(payload "env")")"
check "env piped -> allow"          ALLOW "$(run "$(payload "env | sort")")"
check "printenv -> allow"           ALLOW "$(run "$(payload "printenv")")"
check "npm run env -> allow"        ALLOW "$(run "$(payload "npm run env")")"
# A non-dotfile *.env: left boundary requires a non-word char before the dot,
# so "myapp.env.example" is not treated as a .env dotfile at all.
check "myapp.env.example -> allow"  ALLOW "$(run "$(payload "cat myapp.env.example")")"
# .venv (python virtualenv dir) merely starts with ".ven".
check ".venv -> allow"              ALLOW "$(run "$(payload "python -m venv .venv")")"

# CASE VARIANCE. macOS (APFS) and Windows are case-INSENSITIVE by default, so
# ".ENV" opens the very same inode as ".env" — a case-sensitive matcher is
# defeated by pressing shift. The rest of this file's detectors already use
# grep -i, so matching case-insensitively here is the house convention.
check ".ENV upper -> deny"          DENY "$(run "$(payload "cat .ENV")")"
check ".Env mixed -> deny"          DENY "$(run "$(payload "cat .Env")")"
check ".ENV.LOCAL suffixed -> deny" DENY "$(run "$(payload "cat .ENV.LOCAL")")"
# The template allow-list must be case-insensitive TOO, or making the matcher
# case-blind converts these benign files from allowed into over-blocked.
check ".ENV.EXAMPLE -> allow"       ALLOW "$(run "$(payload "cat .ENV.EXAMPLE")")"
check ".Env.Sample -> allow"        ALLOW "$(run "$(payload "cat .Env.Sample")")"
# .ENVRC is direnv's file in caps — the right boundary (a word char follows)
# must keep excluding it regardless of case.
check ".ENVRC -> allow"             ALLOW "$(run "$(payload "cat .ENVRC")")"
check ".VENV -> allow"              ALLOW "$(run "$(payload "python -m venv .VENV")")"

# EDITOR BACKUPS / AUTOSAVES. These hold a byte-identical copy of the secret
# and appear in a repo without anyone choosing to create them. "~" (vim) and
# "#" (emacs autosave, which brackets the name on BOTH sides) were absent
# from the boundary classes, so the copies were reachable while the original
# was denied.
check ".env~ vim backup -> deny"    DENY "$(run "$(payload "cat .env~")")"
check "#.env# emacs autosave -> deny" DENY "$(run "$(payload "cat '#.env#'")")"
# The dotted backup forms already deny via the suffix branch (their first
# suffix segment is not on the template allow-list). Locked here as
# regressions, not as new coverage.
check ".env.swp -> deny"            DENY "$(run "$(payload "cat .env.swp")")"
check ".env.bak -> deny"            DENY "$(run "$(payload "cat .env.bak")")"
check ".env.save -> deny"           DENY "$(run "$(payload "cat .env.save")")"

# NOT-OVER-BLOCKED. Case-insensitivity plus wider boundaries must not turn
# the gate into a blunt instrument on ordinary paths that merely contain
# "env" or a "~"/"#" character.
check "README.md -> allow"          ALLOW "$(run "$(payload "cat README.md")")"
check ".environment -> allow"       ALLOW "$(run "$(payload "cat .environment")")"
check "envsubst -> allow"           ALLOW "$(run "$(payload "envsubst < config.tmpl")")"
check "home-dir tilde path -> allow" ALLOW "$(run "$(payload "cat ~/notes.md")")"
check "comment containing env -> allow" ALLOW "$(run "$(payload "echo hi # set env vars")")"

# THE SHARPEST DISCRIMINATOR: one command line carrying BOTH an allow-token
# (.env.example) and a deny-token (bare .env). Any implementation that greps
# the whole line for a template name and exempts the line wholesale gets this
# WRONG (it would allow writing the real secret file). Must DENY.
check "cp .env.example .env (mixed) -> deny" DENY "$(run "$(payload "cp .env.example .env")")"
# The inverse: template -> template, no real secret file named. Must ALLOW.
check "cp .env.example .env.sample (both templates) -> allow" \
  ALLOW "$(run "$(payload "cp .env.example .env.sample")")"

# Deny MESSAGE must name a concrete route, not the generic fallback — same
# two-part assertion the other patterns get.
assert_specific_route ".env message names template-read + settings.json route" \
  "cat .env" ".env.example" "settings.json"

# (the pattern_id assertion for dotenv-access lives with the other
# assert_pattern_id calls further down — that helper is defined below.)

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
# lookalike plugin-path filenames that merely CONTAIN "skills/"/"commands/" as a
# substring, not the actual plugin directory at a token boundary -> ALLOW
check "main: tee xcommands/prep.md -> allow"        ALLOW "$(run_cwd "$(payload_with_cwd "tee xcommands/prep.md" "$MAIN_REPO")" "$MAIN_REPO")"
check "main: tee not-skills/x/SKILL.md -> allow"    ALLOW "$(run_cwd "$(payload_with_cwd "tee not-skills/x/SKILL.md" "$MAIN_REPO")" "$MAIN_REPO")"
check "main: tee docs/notcommands/x.md -> allow"    ALLOW "$(run_cwd "$(payload_with_cwd "tee docs/notcommands/x.md" "$MAIN_REPO")" "$MAIN_REPO")"
# genuine nested plugin path (real skills/ dir under an unrelated parent) -> DENY
check "main: tee vendor/skills/x/SKILL.md -> deny"  DENY  "$(run_cwd "$(payload_with_cwd "tee vendor/skills/x/SKILL.md" "$MAIN_REPO")" "$MAIN_REPO")"
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

# --- git clean long/separated force flags ---
check "git clean --force -> deny"          DENY  "$(run "$(payload "git clean --force")")"
check "git clean -d -f -> deny"            DENY  "$(run "$(payload "git clean -d -f")")"
check "git clean -d --force -> deny"       DENY  "$(run "$(payload "git clean -d --force")")"
check "git clean bare -> allow"            ALLOW "$(run "$(payload "git clean")")"
check "git clean --dry-run -> allow"       ALLOW "$(run "$(payload "git clean --dry-run")")"
check "git clean -i -> allow"              ALLOW "$(run "$(payload "git clean -i")")"

# --- truncate --size long flag ---
check "truncate --size=0 x -> deny"        DENY  "$(run "$(payload "truncate --size=0 file.txt")")"
check "truncate --size 0 x -> deny"        DENY  "$(run "$(payload "truncate --size 0 file.txt")")"

# --- cwd fallback (cwd absent → hook resolves branch from $PWD) ---
# When .cwd is absent, the hook falls back to $PWD (destructive_bash_gate.sh:96).
# The branch outcome therefore depends on $PWD, so we pin $PWD to a known repo via
# a subshell `cd` rather than relying on the ambient branch of the coderails
# checkout — which previously made this test flip ALLOW/DENY depending on whether
# coderails itself was on main.
check "no-cwd payload, PWD on feat -> allow" ALLOW "$(cd "$FEAT_REPO" && run "$(payload "sed -i 's/a/b/' foo.py")")"
check "no-cwd payload, PWD on main -> deny"  DENY  "$(cd "$MAIN_REPO" && run "$(payload "sed -i 's/a/b/' foo.py")")"

# --- target-repo resolution (file in feature-branch repo, session cwd on main) ---
# Target file is in FEAT_REPO (on a feature branch). The hook must not over-block.
check "feature-repo target, main cwd -> allow" ALLOW "$(run_cwd "$(payload_with_cwd "sed -i 's/a/b/' $FEAT_REPO/foo.py" "$MAIN_REPO")" "$MAIN_REPO")"

# --- redirect extension anchored to end-of-token ---
check "echo > output.go.log -> allow"        ALLOW "$(run_cwd "$(payload_with_cwd "echo x > output.go.log" "$MAIN_REPO")" "$MAIN_REPO")"
check "echo > foo.py.bak -> allow"           ALLOW "$(run_cwd "$(payload_with_cwd "echo x > foo.py.bak" "$MAIN_REPO")" "$MAIN_REPO")"
check "echo > changes.py.txt -> allow"       ALLOW "$(run_cwd "$(payload_with_cwd "echo x > changes.py.txt" "$MAIN_REPO")" "$MAIN_REPO")"
check "echo > real.py -> deny"               DENY  "$(run_cwd "$(payload_with_cwd "echo x > real.py" "$MAIN_REPO")" "$MAIN_REPO")"
check "find && echo --delete -> allow"       ALLOW "$(run "$(payload "find . -name x && echo --delete")")"
check "find; rm --delete-like -> allow"      ALLOW "$(run "$(payload "find . -name tmp; echo done --delete-style")")"

# --- cp/mv/dd write-to-source on main vs feature branch ---
check "main: cp to foo.py -> deny"           DENY  "$(run_cwd "$(payload_with_cwd "cp /tmp/x foo.py" "$MAIN_REPO")" "$MAIN_REPO")"
check "main: mv to foo.go -> deny"           DENY  "$(run_cwd "$(payload_with_cwd "mv /tmp/x foo.go" "$MAIN_REPO")" "$MAIN_REPO")"
check "main: dd of=foo.py -> deny"           DENY  "$(run_cwd "$(payload_with_cwd "dd of=foo.py if=/tmp/x" "$MAIN_REPO")" "$MAIN_REPO")"
check "feat: cp to foo.py -> allow"          ALLOW "$(run_cwd "$(payload_with_cwd "cp /tmp/x foo.py" "$FEAT_REPO")" "$FEAT_REPO")"
check "feat: mv to foo.go -> allow"          ALLOW "$(run_cwd "$(payload_with_cwd "mv /tmp/x foo.go" "$FEAT_REPO")" "$FEAT_REPO")"
check "feat: dd of=foo.py -> allow"          ALLOW "$(run_cwd "$(payload_with_cwd "dd of=foo.py if=/tmp/x" "$FEAT_REPO")" "$FEAT_REPO")"
check "main: cp to SKILL.md -> deny"         DENY  "$(run_cwd "$(payload_with_cwd "cp /tmp/x skills/mything/SKILL.md" "$MAIN_REPO")" "$MAIN_REPO")"
check "main: mv to commands/x.md -> deny"    DENY  "$(run_cwd "$(payload_with_cwd "mv /tmp/x commands/prep.md" "$MAIN_REPO")" "$MAIN_REPO")"
# cp/mv to a non-source file on main -> allow
check "main: cp to README.md -> allow"       ALLOW "$(run_cwd "$(payload_with_cwd "cp /tmp/x README.md" "$MAIN_REPO")" "$MAIN_REPO")"

# --- backtick/$() command-substitution in workflow-script free-text args ---
# push.sh/merge.sh/post_review.sh/post_evals.sh take a free-text message argument.
# A backtick or $() inside that argument executes as live command substitution
# when the invoking command line is interpolated into bash — the same injection
# class as a render-time !`cmd` line, but triggered by the model's own Bash
# tool_input rather than at render time.
check "push.sh with backtick in message -> deny" DENY \
  "$(run "$(payload 'bash "scripts/push.sh" "fix thing, uses \`git rev-parse\` under the hood"')")"
check "push.sh with \$(...) in message -> deny" DENY \
  "$(run "$(payload 'bash "scripts/push.sh" "fix thing, runs $(whoami) as part of it"')")"
check "merge.sh with backtick in message -> deny" DENY \
  "$(run "$(payload 'bash "scripts/merge.sh" "19" "note: \`rm -rf /\` should never run"')")"
check "post_review.sh with backtick -> deny" DENY \
  "$(run "$(payload 'bash "scripts/post_review.sh" validate "/tmp/x" "uses \`foo\`"')")"
check "post_evals.sh with backtick -> deny" DENY \
  "$(run "$(payload 'bash "scripts/post_evals.sh" validate-structure "/tmp/x.json" "19" "\`sha\`"')")"
# Clean invocations (no backtick/$()) must still be allowed.
check "push.sh clean message -> allow" ALLOW \
  "$(run "$(payload 'bash "scripts/push.sh" "fix thing, uses git rev-parse show-toplevel under the hood"')")"
check "merge.sh clean args -> allow" ALLOW \
  "$(run "$(payload 'bash "scripts/merge.sh" "19"')")"
# Backticks/$() in unrelated commands (not these 4 scripts) must not be blocked by this check.
check "unrelated command with backtick -> allow" ALLOW \
  "$(run "$(payload 'echo "just a note about \`code\` formatting"')")"

# --- False positives: substitution not inside the script's own argument ---
# Negative control (genuine in-argument substitution must still deny) already
# covered above at "push.sh with $(...) in message -> deny" (line 171-172).

# Quoted-literal mention: script name appears in prose, and a $() sits
# elsewhere on the line describing something unrelated to the script's args.
check "prose mentions push.sh, unrelated \$(...) elsewhere -> allow" ALLOW \
  "$(run "$(payload 'echo "this note documents scripts/push.sh and separately shows an example like $(date) for timestamps"')")"

# Stdout-capture: the entire script invocation's stdout is captured into a
# variable via $(...) wrapping the invocation, not the message argument itself.
check "stdout-capture of push.sh invocation -> allow" ALLOW \
  "$(run "$(payload 'out=$(bash scripts/push.sh "clean message with no substitution")')")"

# --- Regression: an unrelated, already-CLOSED substitution earlier on the
# line must not disable scoping for a genuine later in-argument substitution.
# (An earlier open-and-still-open substitution legitimately wraps the whole
# invocation per the stdout-capture case above; a closed one does not.)
check "closed backtick earlier, real substitution in post_review.sh arg -> deny" DENY \
  "$(run "$(payload 'echo `date`; bash scripts/post_review.sh validate "/tmp/x" "uses `foo` here"')")"
check "closed \$(...) earlier, real substitution in merge.sh arg -> deny" DENY \
  "$(run "$(payload 'echo $(pwd); bash scripts/merge.sh "19" "note with $(whoami)"')")"

# --- Regression: quoting style of the malicious argument must not matter. ---
check "single-quoted arg with \$(...) still denies" DENY \
  "$(run "$(payload "bash scripts/push.sh 'fix thing \$(whoami)'")")"
check "unquoted arg with \$(...) still denies" DENY \
  "$(run "$(payload 'bash scripts/push.sh fix-thing-$(whoami)-done')")"

# --- Chained shape: a fully-CLOSED substitution earlier in the command,
# followed by a script invocation whose OWN arguments contain no substitution
# characters at all. The earlier substitution neither wraps the invocation
# (it's closed) nor shares a quoted segment with the script mention (the
# script name here is a bare, unquoted token) — so it must not deny.
check "closed \$(...) assignment earlier, clean post_evals.sh args -> allow" ALLOW \
  "$(run "$(payload 'TIER=$(jq -r .tier /tmp/e.json) && bash scripts/post_evals.sh post 19 "tier zero clean note"')")"
check "closed \$(...) earlier, unrelated prose mentions merge.sh -> allow" ALLOW \
  "$(run "$(payload 'echo $(date) && echo see scripts/merge.sh docs')")"

# --- SECURITY: a genuine in-argument substitution wrapped in an outer
# stdout-capture must still DENY. The prior fix's "unclosed substitution
# before the script name means the whole invocation is being captured"
# heuristic treated ANY unclosed-looking prefix as proof the argument itself
# was clean — but an outer capture can wrap an invocation whose OWN argument
# independently carries a live substitution. This is the exact command-
# substitution injection class the gate exists to block, merely wrapped in
# an extra layer: out=$(bash scripts/merge.sh 19 "note with $(whoami)") — the
# whoami call is live regardless of the outer $(...) capturing the script's
# stdout into $out.
check "in-arg substitution wrapped in outer stdout-capture -> deny" DENY \
  "$(run "$(payload 'out=$(bash scripts/merge.sh 19 "note with $(whoami)")')")"

# --- SECURITY: two script mentions on one line, each in its own && segment —
# a clean first call must not mask a genuine substitution in a later call's
# own argument. Each mention is covered by "first match to end-of-line".
check "two script mentions, second has real substitution -> deny" DENY \
  "$(run "$(payload 'bash scripts/merge.sh "19" && bash scripts/post_evals.sh post 19 "note with $(whoami)"')")"

# --- SECURITY: a shell operator character (&&, ;, ||) sitting INSIDE the
# quoted message argument itself must not be treated as a segment boundary.
# A segment-splitting approach (tried and reverted) is quote-blind — it cuts
# the line at these characters even when they're ordinary prose inside the
# argument, severing the script-name token from its own argument's
# substitution and reopening the injection this check exists to block.
check "&& inside quoted message argument -> deny" DENY \
  "$(run "$(payload 'bash scripts/push.sh "fix A && $(whoami)"')")"
check "; inside quoted message argument -> deny" DENY \
  "$(run "$(payload 'bash scripts/push.sh "note; $(whoami)"')")"
check "|| inside quoted message argument -> deny" DENY \
  "$(run "$(payload 'bash scripts/merge.sh 19 "a || `id`"')")"

# --- SECURITY: the prose exemption must not fire for a genuine invocation
# merely because the invoked script's own message argument happens to also
# mention one of the four script names. Only a script-name mention actually
# INSIDE a quoted string (i.e. text, not a bare command token) is eligible
# for the prose exemption — this is a real call to merge.sh whose own 2nd
# argument contains a live substitution, not documentation about merge.sh.
check "real invocation whose own arg also names the script -> deny" DENY \
  "$(run "$(payload 'bash scripts/merge.sh 19 "see scripts/merge.sh docs for $(cmd) syntax"')")"

# --- SECURITY: a genuine invocation with NO bash/sh interpreter prefix at
# all (the script called directly, or via a leading ./) must still deny when
# its own argument carries a live substitution. An earlier version of this
# fix only recognised "bash scripts/X.sh" / "sh scripts/X.sh" as invocation
# position, which a direct call with no interpreter word evaded, falling
# through to the prose exemption incorrectly.
check "direct invocation, no interpreter prefix -> deny" DENY \
  "$(run "$(payload 'scripts/push.sh "reference to scripts/push.sh with $(whoami)"')")"
check "./ direct invocation, no interpreter prefix -> deny" DENY \
  "$(run "$(payload './scripts/merge.sh 19 "see ./scripts/merge.sh for $(id)"')")"

# --- SECURITY: a prose statement mentioning a script name (with its own
# example substitution) followed by a SEPARATE, genuine invocation later on
# the same line must still deny — the prose exemption is scoped to lines
# with exactly ONE script mention; two or more is always invocation-bearing.
check "prose mention then separate genuine invocation -> deny" DENY \
  "$(run "$(payload 'echo "documentation mentions scripts/push.sh uses $(date)"; bash scripts/push.sh "injected: $(id)"')")"

# --- SECURITY: an earlier closed backtick pair whose closing character
# happens to land adjacent to a quote must not let the quoted-segment
# extraction misread quote boundaries and grant an undeserved exemption.
check "backtick adjacent to quote boundary before real invocation -> deny" DENY \
  "$(run "$(payload 'echo `"`; bash scripts/push.sh "msg $(whoami)"')")"

# --- SECURITY: a hash character inside the one prose segment must not break
# the "is every substitution confined to this segment" check. An earlier
# version removed the segment via a sed substitution delimited by #, which a
# literal # inside the segment's own text broke, causing sed to emit a
# parse error whose stderr text (containing no substitution character) was
# silently read as "nothing left outside the segment" — masking a real,
# separate substitution elsewhere on the line.
check "hash character in prose segment does not mask a separate substitution -> deny" DENY \
  "$(run "$(payload 'echo "note scripts/push.sh has $(date) example #hashtag" && echo $(whoami)')")"

# --- SECURITY (7th-round audit): process substitution <(...) / >(...) inside
# a script argument executes eagerly, exactly like $(...) or backticks, but
# contains NEITHER character — the detector's only trigger is
# grep -qE '`|\$\(', so a payload using <(...) or >(...) alone sails through
# undetected while still running arbitrary commands the instant the line is
# interpreted by bash (confirmed via `: <(touch marker)` executing the touch
# with no $( or backtick anywhere on the line).
check "process substitution <(...) in push.sh arg -> deny" DENY \
  "$(run "$(payload 'bash scripts/push.sh "note" <(touch /tmp/pwned)')")"
check "process substitution >(...) in merge.sh arg -> deny" DENY \
  "$(run "$(payload 'bash scripts/merge.sh 19 "note >(touch /tmp/pwned)"')")"
check "process substitution >(...) as trailing redirect -> deny" DENY \
  "$(run "$(payload 'bash scripts/merge.sh 19 "note" > >(cat > /tmp/exfil)')")"
check "process substitution <(...) still allowed for unrelated commands" ALLOW \
  "$(run "$(payload 'diff <(echo a) <(echo b)')")"
check "process substitution <(...) as leading redirect -> deny" DENY \
  "$(run "$(payload 'bash scripts/push.sh "note" < <(echo hi)')")"

# --- SECURITY (7th-round audit, review follow-up): the prose-exemption's
# "is every substitution confined to this one quoted segment" comparison
# counts substitution occurrences in $cmd_flat vs. in $script_segment
# (destructive_bash_gate.sh, the whole_subst/segment_subst lines). That
# counting pattern must independently include <(/>( too, not just $(/
# backtick — a fix that widened only the DETECTION trigger (subst_re) but
# left the COUNTING pattern at the old $(/backtick-only set would still
# pass every other test in this file (confirmed: such a half-fixed mutant
# passes all other checks here) while wrongly granting the prose exemption
# whenever an unconfined <( or >( sits outside the one quoted segment,
# because whole_subst couldn't see it and would equal segment_subst by
# omission. These two cases pin the counting pattern itself.
check "<(...) confined to the one prose segment, nothing else on line -> allow" ALLOW \
  "$(run "$(payload 'echo "doc mentions scripts/push.sh e.g. <(date)"')")"
check "<(...) confined to prose segment PLUS a second unconfined <(...) -> deny" DENY \
  "$(run "$(payload 'echo "doc mentions scripts/push.sh e.g. <(date)" && diff <(x) <(y)')")"

# --- SECURITY (7th-round audit, review follow-up): the total_mentions > 1
# path (script name appears more than once, so the prose exemption never
# applies at all) is untested for both new bug classes. Confirms neither
# process substitution nor the multi-line flattening accidentally weakens
# that already-conservative path.
check "two mentions, second call carries <(...) -> deny" DENY \
  "$(run "$(payload 'bash scripts/merge.sh "19" && bash scripts/post_evals.sh post 19 "note <(touch pwned)"')")"
check "two mentions via heredoc, second on later physical line -> deny" DENY \
  "$(run "$(payload 'bash scripts/merge.sh 19 "clean" <<EOF
scripts/merge.sh <(touch pwned)
EOF')")"

# --- SECURITY (7th-round audit): multi-line commands defeat the sed/grep
# line-scoped scoping logic. Both `sed -E 's#pattern.*##'` and
# `grep -oE "pattern.*"` operate on $cmd as text, but `.` never crosses a
# newline in POSIX/BSD sed or grep without -z — so when the real script
# argument (carrying a live substitution) lands on a DIFFERENT physical line
# than the script-name mention, "before_script" wrongly absorbs the
# argument's own line (inflating quote_count to an accidental even parity)
# while "from_script" is truncated to end-of-first-line and never sees the
# substitution at all. Two independent real-world triggers for this same
# root cause: a heredoc body (unquoted delimiter, so it still expands) and
# ordinary backslash line-continuation joining one logical command across
# physical lines.
check "heredoc-embedded substitution in push.sh arg -> deny" DENY \
  "$(run "$(payload 'bash scripts/push.sh "clean message" <<EOF
$(id -u)
EOF')")"
# NOTE: a quoted heredoc delimiter (<<'EOF') genuinely suppresses expansion
# in real bash — this $(...) never executes. The fix conservatively denies
# it anyway: distinguishing a quoted from an unquoted heredoc delimiter
# would need new parsing logic, and every previous narrow refinement to
# this block's scoping has itself introduced a fresh bypass under
# adversarial review (see the block's own comments above). A false-positive
# deny on a literal, inert heredoc body is the accepted conservative
# trade-off — correctness over UX, matching this file's stated bias.
check "quoted heredoc delimiter (no expansion) -> still denies (conservative)" DENY \
  "$(run "$(payload 'bash scripts/push.sh "clean" <<'"'"'EOF'"'"'
$(whoami)
EOF')")"
check "backslash line-continuation splits mention from live subst -> deny" DENY \
  "$(run "$(payload 'bash scripts/push.sh \
"note $(whoami)"')")"
check "backslash line-continuation, merge.sh -> deny" DENY \
  "$(run "$(payload 'bash scripts/merge.sh \
19 "note $(whoami)"')")"
check "backslash line-continuation, post_evals.sh -> deny" DENY \
  "$(run "$(payload 'bash scripts/post_evals.sh post 19 \
"note $(whoami)"')")"
check "backslash continuation before mention, clean arg -> allow" ALLOW \
  "$(run "$(payload 'bash \
scripts/push.sh "clean message"')")"

# --- git push --force-with-lease allowlist carve-out ---
# .claude/destructive_allowlist lets an owner opt in to --force-with-lease
# without ever permitting naked --force/-f. Uses a scratch repo fixture (its
# own .claude/ dir) so these tests are isolated from the real coderails
# checkout's own .claude/ directory (test-isolation risk: the hook resolves
# the allowlist path via git rev-parse --show-toplevel of the payload cwd —
# if these tests ran against $PWD without a scoped fixture repo, a
# developer's own real allowlist file could silently flip results).
ALLOWLIST_REPO="$TMP/allowlist_repo"
git init "$ALLOWLIST_REPO" -q
git -C "$ALLOWLIST_REPO" checkout -b feat/allowlist-test -q 2>/dev/null || true

# 1. No allowlist file present -> force-with-lease still denied (regression guard)
check "no allowlist: force-with-lease -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git push --force-with-lease" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"

# 2. Allowlist present with keyword -> force-with-lease allowed
mkdir -p "$ALLOWLIST_REPO/.claude"
printf 'git-push-force-with-lease\n' > "$ALLOWLIST_REPO/.claude/destructive_allowlist"
check "allowlist present: force-with-lease -> allow" ALLOW \
  "$(run_cwd "$(payload_with_cwd "git push --force-with-lease" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"

# 3. SECURITY — allowlist present, naked --force still denied
check "allowlist present: naked --force -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git push --force" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"

# 4. SECURITY — allowlist present, BOTH flags on one line still denied
check "allowlist present: --force + --force-with-lease -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git push --force --force-with-lease" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"

# 5. SECURITY — allowlist present, -f short flag still denied
check "allowlist present: -f short flag -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git push origin main -f" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"

# 5b. SECURITY — allowlist present, -f placed directly before --force-with-lease
# still denied. Regression guard for a bypass found in review: the naked-force
# exclusion regex required a literal space token (`push +`) immediately before
# the alternation, which left no character available for the `(^|[^-])`
# lookbehind-substitute to consume when -f sat right after that mandatory
# space — so `git push -f --force-with-lease` slipped through as "no naked
# force detected" even though -f is right there. Both orderings are checked.
check "allowlist present: -f before --force-with-lease -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git push -f --force-with-lease" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"
check "allowlist present: --force-with-lease before -f -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git push --force-with-lease -f" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"

# 5c. SECURITY — allowlist present, -f combined into a short-flag cluster with
# another single-letter flag (git's own getopt-style clustering, e.g. -uf ==
# -u -f) still denied. Regression guard for a second bypass found in review:
# the -f\b detector only recognised -f as its OWN complete token, missing it
# when bundled with another short flag on either side of the cluster. This
# mirrors the file's own pre-existing git-clean force detector (line 47),
# which already handles exactly this shape for a different command.
check "allowlist present: -uf cluster (upstream+force) -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git push -uf origin main --force-with-lease" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"
check "allowlist present: -fu cluster (force+upstream) -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git push -fu origin main --force-with-lease" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"
check "allowlist present: -ufd cluster (force in middle) -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git push -ufd origin main --force-with-lease" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"
# Negative control: a cluster with NO f letter (just -u) must still allow
# force-with-lease through when the allowlist permits it.
check "allowlist present: -u only (no f), force-with-lease -> allow" ALLOW \
  "$(run_cwd "$(payload_with_cwd "git push -u origin main --force-with-lease" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"

# 5d. SECURITY — a TAB character (not just a literal space) as the flag
# separator still denies with the allowlist present. Regression guard for a
# bypass found in review: naked_force_re's token boundaries were previously
# literal spaces only ("(^| )" / "( |$)"), but bash's default IFS splits on
# space, tab, AND newline — a tool_input line with a tab between "-f" and
# "--force-with-lease" produces the exact same real argv split as a space
# would, so a space-only boundary let the tab-separated form slip through as
# "no naked force detected" even though it is one. Fixed by using
# [[:space:]] character classes instead of literal spaces throughout the
# block. Each case below is paired with a POSITIVE CONTROL (plain
# force-with-lease, no tab, same allowlist) run in the SAME check group —
# an earlier verification pass on this exact bug wrongly concluded "not
# reproduced" because it only ever asserted DENY with no allowlist present,
# which is uninformatively true (fails closed for the wrong reason) rather
# than proving detection; pairing every tab-form assertion with a same-
# fixture positive control makes that class of false negative structurally
# impossible to repeat here.
TAB=$(printf '\t')
POS_CTRL=$(run_cwd "$(payload_with_cwd "git push --force-with-lease" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")
check "positive control: plain force-with-lease, allowlist live -> allow" ALLOW "$POS_CTRL"
check "allowlist present: -f + TAB + force-with-lease -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git push -f${TAB}--force-with-lease" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"
check "allowlist present: -uf cluster + TAB + force-with-lease -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git push -uf${TAB}--force-with-lease" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"
check "allowlist present: --force + TAB + force-with-lease -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git push --force${TAB}--force-with-lease" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"
# Negative control: a non-force cluster separated by a TAB must still allow.
check "allowlist present: -u + TAB + force-with-lease -> allow" ALLOW \
  "$(run_cwd "$(payload_with_cwd "git push -u${TAB}--force-with-lease" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"

# 5e. SECURITY — a backslash-newline line continuation defeats the naked-force
# check even after the [[:space:]] fix above, because `echo "$cmd" | grep` is
# inherently line-oriented — no character class can match ACROSS a newline.
# Bash treats a trailing backslash at end-of-line as intra-command
# whitespace, so two physical lines run as ONE logical command: a naked
# force push split across a backslash-newline continuation executed for
# real while the detector only ever saw one physical line at a time. This
# is a DIFFERENT root cause than the tab case (architectural: line-oriented
# matching, not a character-class gap) — verified by confirming the real
# case is a genuine single command via bash itself, not just asserting on
# the hook's output. Each DENY case pairs with the same-fixture positive
# control used throughout this section.
# NB: NL must be built with ANSI-C quoting ($'\n'), not $(printf '\n') --
# command substitution strips trailing newlines, silently producing an
# EMPTY string and turning every case below into a no-op false-pass.
#
# NOTE on scope: a backslash-newline continuation placed BETWEEN "git" and
# "push" themselves (rather than between two flag tokens) is NOT tested
# here and is confirmed NOT a real bypass, despite superficially looking
# like one: bash's line-continuation removes the backslash-newline with NO
# space inserted, so `git\`<newline>`push` becomes the single token
# `gitpush` — a nonexistent command, not a real `git push` invocation at
# all (verified: `type gitpush` reports not-found). Flagging this
# distinction explicitly because the FLAG-separator case below behaves
# differently: two flag tokens joined by backslash-newline genuinely do
# remain two separate argv entries after continuation-removal (there's
# still a token boundary between them, unlike git+push which fuses into
# one identifier), so that case is a real, exploitable bypass and this one
# is not.
NL=$'\n'
check "positive control (again, before newline cases): plain fwl -> allow" ALLOW \
  "$(run_cwd "$(payload_with_cwd "git push --force-with-lease" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"
# Naked force via backslash-newline continuation, NO allowlist keyword needed
# at all — this is the more severe shape: a plain force push, no carve-out
# involved, still must always deny.
check "no allowlist: naked force via backslash-newline continuation -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git push \\${NL}-f origin main" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"
# Allowlist-active smuggle: force-with-lease on the first physical line,
# the naked -f on a second physical line joined by backslash-continuation.
check "allowlist present: fwl line1 + backslash-newline + -f line2 -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git push --force-with-lease \\${NL}-f origin" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"

# 5f. SECURITY — a backslash-newline continuation placed INSIDE a flag word
# (not just between two separate flags) defeats a naive tr '\n' ' '
# flattening. Bash's real line-continuation REMOVES both the backslash and
# the newline, fusing the characters on either side into one token: e.g.
# "--for" + backslash-newline + "ce" becomes the single genuine argv token
# "--force". A flatten that only replaces the newline with a space (and
# leaves the backslash) instead produces "--for\ ce" — two tokens with a
# stray backslash — so the regex never sees a contiguous "--force" and the
# split escapes detection entirely, with NO allowlist involved at all. This
# is more severe than the inter-token case above: it's a plain naked-force
# bypass, not something that needs the carve-out active to exploit.
#
# Uses its OWN fresh scratch repo (NO_INTRA_REPO) rather than reusing
# ALLOWLIST_REPO, whose allowlist file state at this point in the suite is
# ambient (last set by an earlier section, not something this group
# controls) — an earlier draft of this test wrongly assumed "no allowlist"
# while actually running against a live one left over from an earlier
# check, producing a self-contradictory pair of assertions for the same
# fixture state. A dedicated fresh repo makes the allowlist state explicit
# and local to this test group instead of inherited.
NO_INTRA_REPO="$TMP/no_intra_repo"
git init "$NO_INTRA_REPO" -q
git -C "$NO_INTRA_REPO" checkout -b feat/no-intra -q 2>/dev/null || true
check "no allowlist: --force split via intra-token backslash-newline -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git push --for\\${NL}ce origin main" "$NO_INTRA_REPO")" "$NO_INTRA_REPO")"
check "no allowlist: --force-with-lease split via intra-token backslash-newline -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git push --force-with-\\${NL}lease" "$NO_INTRA_REPO")" "$NO_INTRA_REPO")"
# Positive control: the SAME intra-token split of force-with-lease, but with
# the allowlist live in this same fresh repo, must allow once correctly
# spliced back together into the real "--force-with-lease" token — proves
# the splice fix doesn't just deny everything with a backslash-newline in
# it.
mkdir -p "$NO_INTRA_REPO/.claude"
printf 'git-push-force-with-lease\n' > "$NO_INTRA_REPO/.claude/destructive_allowlist"
check "allowlist present: --force-with-lease split via intra-token backslash-newline -> allow" ALLOW \
  "$(run_cwd "$(payload_with_cwd "git push --force-with-\\${NL}lease" "$NO_INTRA_REPO")" "$NO_INTRA_REPO")"

# 6. Empty allowlist file -> denied (mirrors test_gate.sh empty-content no-op)
: > "$ALLOWLIST_REPO/.claude/destructive_allowlist"
check "empty allowlist file: force-with-lease -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git push --force-with-lease" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"

# 7. Malformed/garbage allowlist content -> denied, not accidentally permit-all
printf '.*\nallow-everything\n--force\n' > "$ALLOWLIST_REPO/.claude/destructive_allowlist"
check "garbage allowlist content: force-with-lease -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git push --force-with-lease" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"

# 8. Comment and blank lines ignored, keyword still recognized
printf '# comment\n\ngit-push-force-with-lease\n' > "$ALLOWLIST_REPO/.claude/destructive_allowlist"
check "comment/blank lines + keyword: force-with-lease -> allow" ALLOW \
  "$(run_cwd "$(payload_with_cwd "git push --force-with-lease" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"

# 9. Wrong-keyword allowlist does not leak into force-with-lease
printf 'git-commit-no-verify\n' > "$ALLOWLIST_REPO/.claude/destructive_allowlist"
check "wrong keyword only: force-with-lease -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git push --force-with-lease" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"

# 10. Existing full test suite regression guard: the original line-36-style
# check (no allowlist in play) must still deny. Re-run with a scratch repo cwd
# to confirm the harness doesn't accidentally inherit the real coderails
# checkout's own .claude/ directory.
NO_ALLOWLIST_REPO="$TMP/no_allowlist_repo"
git init "$NO_ALLOWLIST_REPO" -q
git -C "$NO_ALLOWLIST_REPO" checkout -b feat/no-allowlist -q 2>/dev/null || true
check "scratch repo, no allowlist: force-with-lease -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git push --force-with-lease" "$NO_ALLOWLIST_REPO")" "$NO_ALLOWLIST_REPO")"

# --- git GLOBAL OPTION between "git" and "push" bypass (option-tolerant trigger) ---
# The original trigger regex required a CONTIGUOUS "git push" (git immediately
# followed by whitespace then push). Any git global option placed between
# them — git -c NAME=VALUE push, git --no-pager push, git -C path push — broke
# that adjacency, so the naked-force detector never even looked at the rest
# of the line: a naked force push with NO allowlist anywhere would sail
# through as ALLOW. Uses its own fresh scratch repo (no allowlist file at
# all) so these assertions prove the trigger fires independent of the
# allowlist carve-out machinery entirely.
OPT_REPO="$TMP/opt_repo"
git init "$OPT_REPO" -q
git -C "$OPT_REPO" checkout -b feat/opt-bypass -q 2>/dev/null || true

# Regression guard for the exact three bypass shapes reported.
check "no allowlist: -c NAME=VALUE before push, naked --force -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git -c push.followTags=true push --force origin main" "$OPT_REPO")" "$OPT_REPO")"
check "no allowlist: --no-pager before push, naked --force -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git --no-pager push --force origin main" "$OPT_REPO")" "$OPT_REPO")"
check "no allowlist: -c NAME=VALUE before push, naked -f -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git -c core.pager=less push -f origin main" "$OPT_REPO")" "$OPT_REPO")"

# Other global-option shapes, same no-allowlist naked-force pattern.
check "no allowlist: -C path before push, naked --force -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git -C /tmp/somerepo push --force origin main" "$OPT_REPO")" "$OPT_REPO")"
check "no allowlist: --git-dir= before push, naked --force -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git --git-dir=/tmp/somerepo/.git push --force origin main" "$OPT_REPO")" "$OPT_REPO")"
check "no allowlist: stacked options before push, naked -f -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git -c a=b -c c=d --no-pager push -f origin main" "$OPT_REPO")" "$OPT_REPO")"

# Repetition-bound regression guard: 7 chained -c options (one more than the
# gate's first-draft {0,6} bound, widened to {0,20} after review) must still
# deny — found during review as a live bypass at the original bound (7
# options pushed the trigger out of range, silently ALLOWing a naked force
# push). git itself has no limit on repeated -c, so this proves the widened
# bound actually covers a realistic chain length rather than just re-testing
# the same single-option shape already covered above.
check "no allowlist: 7 chained -c options before push, naked --force -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git -c a.a=1 -c a.b=2 -c a.c=3 -c a.d=4 -c a.e=5 -c a.f=6 -c a.g=7 push --force origin main" "$OPT_REPO")" "$OPT_REPO")"

# Regression guard: the already-fixed backslash-newline-BETWEEN-git-and-push
# case must stay denied — it's a different mechanism (awk splice collapses it
# to contiguous "git push" upstream of this block) but worth re-confirming
# here alongside the option-tolerance fix so a future change to either
# mechanism can't silently reopen this specific shape.
OPT_NL=$'\n'
check "no allowlist: backslash-newline between git and push, naked --force -> deny (no regression)" DENY \
  "$(run_cwd "$(payload_with_cwd "git \\${OPT_NL}push --force origin main" "$OPT_REPO")" "$OPT_REPO")"

# Symmetric carve-out preservation: the allowlisted force-with-lease path must
# stay reachable WITH a git global option present between git and push —
# option-tolerance has to apply to both the trigger and the fwl-exclusion
# check, not just the naked-force trigger, or this fix would break the
# legitimate opt-in path for anyone who also passes a global option.
mkdir -p "$OPT_REPO/.claude"
printf 'git-push-force-with-lease\n' > "$OPT_REPO/.claude/destructive_allowlist"
check "allowlist present: -c option before push, force-with-lease only -> allow" ALLOW \
  "$(run_cwd "$(payload_with_cwd "git -c push.followTags=true push --force-with-lease origin main" "$OPT_REPO")" "$OPT_REPO")"
check "positive control: plain force-with-lease, allowlist live -> allow" ALLOW \
  "$(run_cwd "$(payload_with_cwd "git push --force-with-lease" "$OPT_REPO")" "$OPT_REPO")"
check "allowlist present: -c option before push, naked --force + fwl -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "git -c push.followTags=true push --force --force-with-lease origin main" "$OPT_REPO")" "$OPT_REPO")"

# Negative control: an unrelated git subcommand with a global option must
# still be allowed through untouched (proves the wider trigger isn't
# over-matching ordinary git invocations).
check "no allowlist: -c option before status (unrelated subcommand) -> allow" ALLOW \
  "$(run_cwd "$(payload_with_cwd "git -c color.ui=always status" "$OPT_REPO")" "$OPT_REPO")"
check "no allowlist: --no-pager before log (unrelated subcommand) -> allow" ALLOW \
  "$(run_cwd "$(payload_with_cwd "git --no-pager log -1" "$OPT_REPO")" "$OPT_REPO")"

# --- SECURITY: TAB-separated forms of every OTHER blocklist detector in this
# file (not just the git-push naked-force one fixed above). Every one of
# these detectors used a literal-space-only "+" (or a literal-space "(^| )"
# boundary, or "[= ]") as its token separator, which never matches a TAB —
# a real, executable argv split bash itself treats identically to a space
# (default IFS = space, tab, newline). A tab between "rm" and "-rf", or
# "git" and "reset", etc. previously evaded every one of these checks
# entirely, denying nothing. TAB is the same $(printf '\t') var defined
# above (5d) — reused here rather than re-declared.
check "rm TAB -rf -> deny" DENY \
  "$(run "$(payload "rm${TAB}-rf /tmp/x")")"
check "git TAB reset TAB --hard -> deny" DENY \
  "$(run "$(payload "git${TAB}reset${TAB}--hard HEAD~1")")"
check "DROP TAB TABLE -> deny" DENY \
  "$(run "$(payload "DROP${TAB}TABLE users;")")"
check "TRUNCATE TAB TABLE -> deny" DENY \
  "$(run "$(payload "TRUNCATE${TAB}TABLE logs;")")"
check "dd TAB if= -> deny" DENY \
  "$(run "$(payload "dd${TAB}if=/dev/zero of=/dev/sda")")"
check "chmod TAB -R TAB 777 -> deny" DENY \
  "$(run "$(payload "chmod${TAB}-R${TAB}777 /var/www")")"
check "git TAB commit TAB --no-verify -> deny" DENY \
  "$(run "$(payload "git${TAB}commit${TAB}-m x${TAB}--no-verify")")"

# git clean force, TAB-separated
check "git TAB clean TAB -f -> deny" DENY \
  "$(run "$(payload "git${TAB}clean${TAB}-f")")"
check "git TAB clean TAB --force -> deny" DENY \
  "$(run "$(payload "git${TAB}clean${TAB}--force")")"
# git clean dry-run, TAB-separated, must still allow
check "git TAB clean TAB --dry-run -> allow" ALLOW \
  "$(run "$(payload "git${TAB}clean${TAB}--dry-run")")"

# find -delete, TAB-separated
check "find ... TAB -delete -> deny" DENY \
  "$(run "$(payload "find .${TAB}-delete")")"

# truncate -s / --size, TAB-separated (shell truncate, distinct from the SQL
# TRUNCATE TABLE detector above)
check "truncate TAB -s0 -> deny" DENY \
  "$(run "$(payload "truncate${TAB}-s0 logfile.txt")")"
check "truncate TAB --size=0 -> deny" DENY \
  "$(run "$(payload "truncate${TAB}--size=0 logfile.txt")")"
check "truncate --sizeTAB0 -> deny" DENY \
  "$(run "$(payload "truncate --size${TAB}0 logfile.txt")")"

# sed -i / perl -i, TAB-separated, branch-aware (must deny on main, allow on
# a feature branch — mirrors the existing sed/perl coverage above).
check "main: sed TAB -i on .py -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "sed${TAB}-i 's/a/b/' foo.py" "$MAIN_REPO")" "$MAIN_REPO")"
check "feat: sed TAB -i on .py -> allow" ALLOW \
  "$(run_cwd "$(payload_with_cwd "sed${TAB}-i 's/a/b/' foo.py" "$FEAT_REPO")" "$FEAT_REPO")"
check "main: perl TAB -i on .go -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "perl${TAB}-i -pe 's/old/new/g' main.go" "$MAIN_REPO")" "$MAIN_REPO")"

# src_ext / plugin_src right-boundary: "([ '\"]|$)" was a literal-space
# bracket expression (space, single-quote, double-quote only, no tab), so a
# source extension followed by a TAB (rather than end-of-string, a space, or
# a quote) fell through the boundary check entirely and was not recognised
# as a source file at all.
check "main: sed -i on .py followed by TAB -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "sed -i 's/a/b/' foo.py${TAB}extra" "$MAIN_REPO")" "$MAIN_REPO")"
check "main: tee SKILL.md followed by TAB -> deny" DENY \
  "$(run_cwd "$(payload_with_cwd "tee skills/mything/SKILL.md${TAB}extra" "$MAIN_REPO")" "$MAIN_REPO")"

# --- Regression: benign commands where a blocked word appears only as a
# substring of an unrelated token must still allow, including with tabs
# nearby, so the widened separator classes don't start over-matching.
check "drops.txt filename -> allow" ALLOW \
  "$(run "$(payload "cat drops.txt")")"
check "firmware/ path -> allow" ALLOW \
  "$(run "$(payload "ls firmware/")")"
check "format word in prose -> allow" ALLOW \
  "$(run "$(payload "echo format the disk nicely")")"
check "find without delete, TAB-separated args -> allow" ALLOW \
  "$(run "$(payload "find${TAB}. -name x.tmp")")"

# --- SECURITY: \$IFS-expansion evasion ------------------------------------
# A destructive command built with an $IFS expansion (${IFS}, bare $IFS,
# ${IFS:offset:length}, or a use-default/assign-default/error-if-unset
# parameter-expansion operator applied to IFS) as its token separator
# contains NO whitespace CHARACTER in the literal tool_input text — every
# detector in this file greps $cmd for a literal whitespace class, so the
# pattern was entirely invisible to all of them before $cmd is normalized.
# Covers rm, git reset --hard, chmod -R 777, and DROP TABLE (representative
# families across the monolithic blocklist), using the clean separator forms
# that reconstruct into the real, intended command in actual bash — verified
# by ground-truth execution (rm removing a real non-empty directory, chmod
# actually setting 777 on a real file), not tokenization alone, since a
# glued/corrupted reconstruction can look destructive in isolated token
# inspection while actually erroring out harmlessly. ${IFS}, ${IFS:0:1}, and
# ${IFS:-y} all act as a full expansion boundary yielding real whitespace
# (IFS is set by default, so use-default/assign-default/error-if-unset
# operators evaluate to IFS's own value, never their fallback word) and are
# safe to replace with a space; bare $IFS is included only where it is not
# immediately followed by an identifier character, since bash itself treats
# $IFSreset as an entirely different (and here irrelevant) variable name,
# not $IFS followed by literal "reset".
check "rm\${IFS}-rf -> deny"           DENY "$(run "$(payload "rm\${IFS}-rf /tmp/x")")"
check "rm bare \$IFS -rf -> deny"      DENY "$(run "$(payload "rm\$IFS-rf /tmp/x")")"
check "rm \${IFS:0:1}-rf -> deny"      DENY "$(run "$(payload "rm\${IFS:0:1}-rf /tmp/x")")"
check "git reset \${IFS}--hard -> deny" DENY \
  "$(run "$(payload "git\${IFS}reset\${IFS}--hard HEAD~1")")"
check "chmod \${IFS}-R\${IFS}777 -> deny" DENY \
  "$(run "$(payload "chmod\${IFS}-R\${IFS}777 /var/www")")"
check "chmod \${IFS:0:1}-R\${IFS:0:1}777 -> deny" DENY \
  "$(run "$(payload "chmod\${IFS:0:1}-R\${IFS:0:1}777 /var/www")")"

# ${IFS:-word} / ${IFS-word} (use-default operator): since IFS is set by
# default, this evaluates to IFS's OWN whitespace value, not the fallback
# word — a real separator, confirmed by ground-truth execution (rm -rf on a
# non-empty dir; chmod -R 777 on a real file) rather than tokenization alone.
check "rm \${IFS:-y}-rf -> deny"       DENY "$(run "$(payload "rm\${IFS:-y}-rf /tmp/x")")"
check "chmod \${IFS:-y}-R\${IFS:-y}777 -> deny" DENY \
  "$(run "$(payload "chmod\${IFS:-y}-R\${IFS:-y}777 /var/www")")"
check "git reset \${IFS:-y}--hard -> deny" DENY \
  "$(run "$(payload "git\${IFS:-y}reset\${IFS:-y}--hard HEAD~1")")"
check "DROP \${IFS:-y}TABLE -> deny"   DENY "$(run "$(payload "DROP\${IFS:-y}TABLE users;")")"

# Negative substring offsets — \${IFS: -1} / \${IFS:(-1)} — bash requires the
# space (or parens) right after the colon to disambiguate a negative offset
# from the :- use-default operator; both still evaluate to trailing IFS
# whitespace and are real separators (an enumerated, non-exclude-only version
# of this fix missed this shape entirely — found by an independent grader).
check "rm \${IFS: -1}-rf -> deny"      DENY "$(run "$(payload "rm\${IFS: -1}-rf /tmp/x")")"
check "rm \${IFS:(-1)}-rf -> deny"     DENY "$(run "$(payload "rm\${IFS:(-1)}-rf /tmp/x")")"

# Benign commands that merely MENTION $IFS (not use it as a separator to
# hide a destructive verb) must stay ALLOWED — the normalization only
# changes whitespace, never introduces or removes a blocklist keyword.
check "echo \${IFS} (benign mention) -> allow" ALLOW \
  "$(run "$(payload 'echo "${IFS}"')")"
check "echo bare \$IFS (benign mention) -> allow" ALLOW \
  "$(run "$(payload 'echo $IFS')")"
check "echo \\\$IFSOMETHING (different var, not \$IFS) -> allow" ALLOW \
  "$(run "$(payload 'echo $IFSOMETHING')")"

# Harmless look-alikes: ${IFS}x and ${IFSx} do NOT act as clean separators
# (confirmed by ground-truth execution against a real non-empty directory —
# rm${IFS}x-rf and rm${IFSx}-rf both leave the directory intact) and must
# stay ALLOWED, proving the normalization doesn't over-match into a false deny.
check "rm \${IFS}x-rf (harmless glue) -> allow" ALLOW \
  "$(run "$(payload "rm\${IFS}x-rf /tmp/x")")"
check "rm \${IFSx}-rf (different var, harmless) -> allow" ALLOW \
  "$(run "$(payload "rm\${IFSx}-rf /tmp/x")")"

# \${IFS:+word} / \${IFS+word} (alternate-value operator): since IFS is set,
# this substitutes the literal WORD, not IFS's whitespace value. A
# NON-whitespace word (e.g. SET) must NOT be collapsed to a space — that
# would erase real text — and stays allowed exactly as written.
check "echo \${IFS:+word} (not a separator) -> allow" ALLOW \
  "$(run "$(payload 'echo "safe${IFS:+word}"')")"
check "echo \${IFS:+SET} (not a separator) -> allow" ALLOW \
  "$(run "$(payload 'echo "${IFS:+SET}"')")"
check "echo \${IFS+SET} (no colon, not a separator) -> allow" ALLOW \
  "$(run "$(payload 'echo "${IFS+SET}"')")"

# SECURITY (whitespace-word carve-out): when the :+/+ word is ATTACKER-
# CONTROLLED and is one or more literal spaces/tabs, the substituted word
# IS whitespace, making the expansion a real separator independent of IFS's
# own value — found by security review, confirmed by ground-truth execution
# (rm removing a real non-empty directory). The blanket "never collapse
# :+/+" reasoning above covers the common case (a non-whitespace word) but
# is incomplete on its own; this carve-out must fire first and re-collapse
# the whitespace-only-word shape specifically.
check "rm \${IFS:+ }-rf (whitespace word) -> deny" DENY \
  "$(run "$(payload "rm\${IFS:+ }-rf /tmp/x")")"
check "rm \${IFS+ }-rf (whitespace word, no colon) -> deny" DENY \
  "$(run "$(payload "rm\${IFS+ }-rf /tmp/x")")"
check "rm \${IFS:+  }-rf (two-space word) -> deny" DENY \
  "$(run "$(payload "rm\${IFS:+  }-rf /tmp/x")")"
check "chmod \${IFS:+ }-R\${IFS:+ }777 (whitespace word) -> deny" DENY \
  "$(run "$(payload "chmod\${IFS:+ }-R\${IFS:+ }777 /var/www")")"

# SECURITY (word-general :+/+ operator rule): the whitespace-word carve-out
# above only re-collapses a word that is ENTIRELY whitespace. A word that
# BEGINS with whitespace and then continues into real flag text (e.g.
# " -r") is NOT all-whitespace, so the carve-out's own [[:space:]]+ anchor
# does not match it, and it falls through to pass 1's blanket ":+/+ never
# collapse" exclusion untouched — no whitespace character reaches any
# detector, but bash still splits on the leading space and reconstructs a
# real armed command (verified: `rm${IFS:+ -r}f /tmp/x` -> bash argv
# [rm][-rf][/tmp/x], a real rm -rf). The fix generalises the operator rule
# instead of adding a fourth one-off literal: emit the :+/+ word VERBATIM
# (not collapsed to a single space) regardless of its first character. This
# also closes a second, adjacent form the same family exposes: a word that
# is flag text with NO leading whitespace at all, separated from the
# preceding token by its OWN separate space or ${IFS} (e.g.
# `rm ${IFS:+-rf} x` / `rm${IFS}${IFS:+-rf} x`) — the old blanket exclusion
# left `${IFS:+-rf}` opaque in both, so the gate saw "rm " followed
# immediately by "$" (not "-"), missing the \brm[[:space:]]+-rf pattern
# entirely, while bash expands it to a real `-rf` token glued onto "rm ".
check "rm \${IFS:+ -r}f (leading-ws-then-flag word) -> deny" DENY \
  "$(run "$(payload "rm\${IFS:+ -r}f /tmp/x")")"
check "git\${IFS:+ }reset\${IFS:+ --hard} (chained leading-ws words) -> deny" DENY \
  "$(run "$(payload "git\${IFS:+ }reset\${IFS:+ --hard} HEAD~1")")"
check "rm \${IFS:+-rf} (flag word, own separate space) -> deny" DENY \
  "$(run "$(payload "rm \${IFS:+-rf} /tmp/x")")"
check "rm\${IFS}\${IFS:+-rf} (flag word, own separate \${IFS}) -> deny" DENY \
  "$(run "$(payload "rm\${IFS}\${IFS:+-rf} /tmp/x")")"

# Controls that MUST stay allowed after the word-general fix — emitting the
# word verbatim must not turn a harmless word into a destructive one.
check "echo \${IFS:+x -r} (word starts non-whitespace, glues harmlessly) -> allow" ALLOW \
  "$(run "$(payload "echo rm\${IFS:+x -r}f /tmp/x")")"

# assign-default / error-if-unset operators on IFS: already collapsed
# correctly by pass 1 (verified), just lacked a behavioural test.
check "rm \${IFS:=y}-rf (assign-default) -> deny" DENY \
  "$(run "$(payload "rm\${IFS:=y}-rf /tmp/x")")"
check "rm \${IFS=y}-rf (assign-default, no colon) -> deny" DENY \
  "$(run "$(payload "rm\${IFS=y}-rf /tmp/x")")"
check "DROP \${IFS:?y}TABLE (error-if-unset) -> deny" DENY \
  "$(run "$(payload "DROP\${IFS:?y}TABLE users;")")"
check "DROP \${IFS?y}TABLE (error-if-unset, no colon) -> deny" DENY \
  "$(run "$(payload "DROP\${IFS?y}TABLE users;")")"

# Literal-TAB whitespace-word in the :+ carve-out — guards the
# [[:space:]]-not-\t footgun the pass-0 comment warns about (BSD sed does
# not treat a literal backslash-t as an escape inside a bracket class, so a
# \t-based class would silently fail to match a real tab byte).
check "rm \${IFS:+<TAB>-r}f (tab-leading word) -> deny" DENY \
  "$(run "$(payload "$(printf 'rm${IFS:+\t-r}f /tmp/x')")")"

# --- Q1: mention-safe hyphenated pattern_id per deny() case arm -----------
# Each deny() call now carries a hyphenated pattern_id in the jq output
# (hookSpecificOutput.patternId) alongside the existing message fields. The
# id is MESSAGE-ONLY output text — it changes nothing about which commands
# reach deny() in the first place (the matcher regexes are untouched).
#
# Per id: (a) MENTION-SAFETY — a command whose text is just the id string
# itself must NOT be denied (the id is hyphenated specifically so it never
# matches the matcher's own whitespace-based regexes, e.g. "chmod-r-777"
# does not match "chmod[[:space:]]+-R[[:space:]]+777"). (b) NEGATIVE
# CONTROL — the real blocked literal must still deny AND must carry that
# same pattern_id in its output.
assert_pattern_id() { # desc real_blocked_cmd mention_safe_cmd expected_id
  local desc="$1" real_cmd="$2" mention_cmd="$3" expected_id="$4"
  check "$desc: mention alone -> allow" ALLOW "$(run "$(payload "$mention_cmd")")"
  check "$desc: real literal -> deny"   DENY  "$(run "$(payload "$real_cmd")")"
  check "$desc: deny carries pattern_id" "$expected_id" "$(run_pattern_id "$(payload "$real_cmd")")"
}

assert_pattern_id "git-reset-hard" \
  "git reset --hard HEAD~1" "echo git-reset-hard" "git-reset-hard"
assert_pattern_id "rm-rf" \
  "rm -rf /tmp/x" "echo rm-rf" "rm-rf"
assert_pattern_id "git-push-force" \
  "git push --force" "echo git-push-force" "git-push-force"
assert_pattern_id "git-clean-force" \
  "git clean -fdx" "echo git-clean-force" "git-clean-force"
assert_pattern_id "find-delete" \
  "find . -name '*.tmp' -delete" "echo find-delete" "find-delete"
assert_pattern_id "truncate-size" \
  "truncate -s0 logfile.txt" "echo truncate-size" "truncate-size"
assert_pattern_id "secure-wipe-delete" \
  "shred secret.key" "echo secure-wipe-delete" "secure-wipe-delete"
assert_pattern_id "drop-table (TABLE)" \
  "DROP TABLE users;" "echo drop-table" "drop-table"
assert_pattern_id "drop-table (DATABASE)" \
  "DROP DATABASE mydb;" "echo drop-table" "drop-table"
assert_pattern_id "drop-table (SCHEMA)" \
  "DROP SCHEMA public CASCADE;" "echo drop-table" "drop-table"
assert_pattern_id "truncate-table" \
  "TRUNCATE TABLE logs;" "echo truncate-table" "truncate-table"
assert_pattern_id "dd-if" \
  "dd if=/dev/zero of=/dev/sda" "echo dd-if" "dd-if"
assert_pattern_id "mkfs-format" \
  "mkfs.ext4 /dev/sdb1" "echo mkfs-format" "mkfs-format"
assert_pattern_id "chmod-r-777" \
  "chmod -R 777 /var/www" "echo chmod-r-777" "chmod-r-777"
assert_pattern_id "git-commit-no-verify" \
  "git commit -m 'wip' --no-verify" "echo git-commit-no-verify" "git-commit-no-verify"
# dotenv-access: the id is hyphenated AND contains no ".env" substring at all
# (it is "dotenv", not ".env"), so echoing the id cannot self-trigger the
# gate's own .env matcher — which is precisely why the id was named that way.
assert_pattern_id "dotenv-access" \
  "cat .env" "echo dotenv-access" "dotenv-access"

# --- Q1: source-drift tripwire extension — every route case arm (except the
# generic "*)" fallback, exempted below) must carry a pattern_id, so a new
# arm added later without one is caught here rather than shipping silently
# routeless AND idless. Extracted the same way as extract_fixed_labels above
# (grep -vE comment lines first) but scoped to "route=" assignment lines and
# their immediately-following "pattern_id=" assignment, keyed on line number
# adjacency within the case block.
assert_every_route_arm_has_pattern_id() {
  local gate_path="$1"
  # route_lines: 1-indexed line numbers of every non-comment "route=" assignment
  # inside the deny() case block (destructive_bash_gate.sh's case "$pat_lc" in
  # ... esac). The generic "*)" fallback's route= line is excluded by name via
  # the preceding case label check below, not by line-number exclusion, so a
  # future reordering of arms doesn't silently break the exemption.
  local awk_prog='
    /^[[:space:]]*case "\$pat_lc" in/ { in_case=1 }
    /^[[:space:]]*esac/ { in_case=0 }
    in_case && /^[[:space:]]*\*\)/ { is_fallback=1; next }
    in_case && /^[[:space:]]*[^[:space:]].*\)$/ { is_fallback=0 }
    in_case && /^[[:space:]]*route=/ && !is_fallback { print NR }
  '
  local route_lines
  route_lines=$(grep -vE '^[[:space:]]*#' "$gate_path" > /dev/null; awk "$awk_prog" "$gate_path")
  local missing=0
  local ln
  for ln in $route_lines; do
    # A pattern_id= assignment must appear within the same case arm — check
    # the next non-blank line after route= (the arms in this file set
    # pattern_id immediately adjacent to route, per the task's pinned shape).
    local next_line
    next_line=$(sed -n "$((ln+1))p" "$gate_path")
    if ! printf '%s' "$next_line" | grep -qE '^[[:space:]]*pattern_id='; then
      missing=1
      printf '     MISSING pattern_id on the arm ending at route= line %s\n' "$ln"
    fi
  done
  [ "$missing" -eq 0 ]
}

if assert_every_route_arm_has_pattern_id "$HOOK"; then
  check "every non-fallback deny() case arm sets a pattern_id" DENY DENY
else
  fails=$((fails+1))
  printf 'FAIL - every non-fallback deny() case arm sets a pattern_id\n'
fi

# --- Deliverable B: source-drift tripwire ---------------------------------
# Extracts the gate's blockable set (the 5 fixed-label `deny "..."` call
# sites, plus the monolithic `pattern=` regex line verbatim) and compares it
# against a committed expected snapshot below. This must FAIL the instant
# someone adds a new blockable pattern to the gate without also updating this
# file's EXPECTED_* snapshot — which is exactly the moment a new pattern
# would otherwise ship with no safe route and no test (the routeless
# pattern-#14 gap this whole task exists to close).
#
# Extraction reads the gate source with grep/awk only — never executes it as
# a command whose *string content* matches the gate's own blocklist (the
# extraction regexes below, e.g. 'deny "[^"$]*"' or '^pattern=', contain no
# blocklisted literal themselves, so this is safe to run directly).
#
# Comment lines are excluded (grep -vE '^[[:space:]]*#') so a *prose mention*
# of `deny "..."` in a comment (e.g. this file's own strategy comment above
# the git-clean block) is not mistaken for a real call site — confirmed this
# matters: the naive extraction (no comment filter) picked up a spurious
# 6th "label" from exactly such a comment during this file's own development.
#
# Scope: sync is enforced for the deny()-routed patterns only (the 5 fixed
# labels + the pattern= alternatives) — NOT the cp/mv/dd, sed/perl/tee, or
# command-substitution blocks further down the gate, which build their own
# jq JSON directly and never call deny(). Those three already carry their
# own specific messages and are outside this tripwire's scope by design.

extract_fixed_labels() { # gate_path -> sorted unique "deny "..."" call sites
  grep -vE '^[[:space:]]*#' "$1" | grep -oE 'deny "[^"$]*"' | sort -u
}

extract_pattern_line() { # gate_path -> the pattern= line verbatim
  grep -E '^pattern=' "$1"
}

# Committed expected snapshot — the blockable set as of this PR. Update BOTH
# this snapshot AND (deny() route arm + a behavioural test case above) in the
# SAME commit whenever a new deny() call site or pattern= alternative is
# added — that is the "one-line update with an obvious diff" the drift check
# exists to force.
EXPECTED_FIXED_LABELS='deny ".env access"
deny "find -delete"
deny "git clean (force)"
deny "git push --force"
deny "shred"
deny "truncate -s/--size"'

EXPECTED_PATTERN_LINE='pattern='"'"'\brm[[:space:]]+(-[rRfF]+|--recursive|--force)|\bgit[[:space:]]+reset[[:space:]]+--hard|\bDROP[[:space:]]+(TABLE|DATABASE|SCHEMA)\b|\bTRUNCATE[[:space:]]+TABLE\b|\bdd[[:space:]]+if=|\bmkfs\.|\bchmod[[:space:]]+-R[[:space:]]+777|\bgit[[:space:]]+commit[[:space:]]+.*--no-verify'"'"

actual_fixed_labels=$(extract_fixed_labels "$HOOK")
actual_pattern_line=$(extract_pattern_line "$HOOK")

if [ "$actual_fixed_labels" = "$EXPECTED_FIXED_LABELS" ]; then
  check "gate's fixed-label deny() call sites match the committed snapshot" DENY DENY
else
  fails=$((fails+1))
  printf 'FAIL - gate'"'"'s fixed-label deny() call sites match the committed snapshot\n'
  printf '     the blockable set changed. Expected:\n%s\n     Actual (live gate):\n%s\n' \
    "$EXPECTED_FIXED_LABELS" "$actual_fixed_labels"
  printf '     ACTION: for each new/removed deny "<label>" call site, add a matching\n'
  printf '     lowercase case arm in deny() (destructive_bash_gate.sh) with a real safe\n'
  printf '     route (or an honest "no safe equivalent" route), add a behavioural test\n'
  printf '     case for it above, THEN update EXPECTED_FIXED_LABELS in this file to match.\n'
fi

if [ "$actual_pattern_line" = "$EXPECTED_PATTERN_LINE" ]; then
  check "gate's monolithic pattern= line matches the committed snapshot" DENY DENY
else
  fails=$((fails+1))
  printf 'FAIL - gate'"'"'s monolithic pattern= line matches the committed snapshot\n'
  printf '     the pattern= regex changed. Expected:\n%s\n     Actual (live gate):\n%s\n' \
    "$EXPECTED_PATTERN_LINE" "$actual_pattern_line"
  printf '     ACTION: for each new alternative added to pattern=, add a matching\n'
  printf '     lowercase case arm in deny() keyed on the MATCHED SUBSTRING (not a\n'
  printf '     friendly label) with a real safe route (or an honest "no safe\n'
  printf '     equivalent" route), add a behavioural test case for it above, THEN\n'
  printf '     update EXPECTED_PATTERN_LINE in this file to match.\n'
fi

[ "$fails" -eq 0 ] && { echo "PASS"; exit 0; } || { echo "FAILED ($fails)"; exit 1; }
