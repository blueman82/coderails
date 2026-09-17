#!/usr/bin/env bash
# shellcheck disable=SC1091
source "$(dirname "$0")/destructive_bash_gate_common.sh"

# --- Blocked commands ---
check "rm -rf x -> deny" DENY "$(run "$(payload "rm -rf /tmp/x")")"
check "rm -rf . -> deny" DENY "$(run "$(payload "rm -rf .")")"
check "rm -r somedir -> deny" DENY "$(run "$(payload "rm -r somedir")")"
check "git push --force -> deny" DENY "$(run "$(payload "git push --force")")"
check "git push -f -> deny" DENY "$(run "$(payload "git push origin main -f")")"
# Combined short-flag cluster (git's own getopt-style clustering, e.g. -uf ==
# -u -f), no --force-with-lease in play at all — mirrors the file's existing
# git-clean force detector's own combined-flag handling (line 47) rather than
# only recognising -f as a standalone complete token.
check "git push -uf cluster (no fwl) -> deny" DENY "$(run "$(payload "git push -uf origin main")")"
check "git push --force-with-lease -> deny" DENY "$(run "$(payload "git push --force-with-lease")")"
check "git reset --hard -> deny" DENY "$(run "$(payload "git reset --hard HEAD~1")")"
check "DROP TABLE -> deny" DENY "$(run "$(payload "DROP TABLE users;")")"
check "DROP DATABASE -> deny" DENY "$(run "$(payload "DROP DATABASE mydb;")")"
check "TRUNCATE TABLE -> deny" DENY "$(run "$(payload "TRUNCATE TABLE logs;")")"
check "dd if= -> deny" DENY "$(run "$(payload "dd if=/dev/zero of=/dev/sda")")"
check "mkfs. -> deny" DENY "$(run "$(payload "mkfs.ext4 /dev/sdb1")")"
check "chmod -R 777 -> deny" DENY "$(run "$(payload "chmod -R 777 /var/www")")"
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
    check "$desc" DENY "$([ "$ok" -eq 1 ] && echo DENY || echo MISSING)"
}

# Forced cleanup has a genuine safe route: the gate already permits
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

# Commit-hook bypass has a genuine safe alternative — fix the failing hook.
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
check ".env: cat -> deny" DENY "$(run "$(payload "cat .env")")"
check ".env: less -> deny" DENY "$(run "$(payload "less .env")")"
check ".env: head -> deny" DENY "$(run "$(payload "head -5 .env")")"
check ".env: tail -> deny" DENY "$(run "$(payload "tail .env")")"
check ".env: grep -> deny" DENY "$(run "$(payload "grep API_KEY .env")")"
check ".env: source -> deny" DENY "$(run "$(payload "source .env")")"
check ".env: awk -> deny" DENY "$(run "$(payload "awk '{print}' .env")")"
check ".env: editor -> deny" DENY "$(run "$(payload "nano .env")")"

# WRITES — the destroy/replace direction.
check ".env: redirect > -> deny" DENY "$(run "$(payload "echo 'X=1' > .env")")"
check ".env: append >> -> deny" DENY "$(run "$(payload "echo 'X=1' >> .env")")"
check ".env: no-space redirect -> deny" DENY "$(run "$(payload "echo 'X=1' >.env")")"
check ".env: cp onto it -> deny" DENY "$(run "$(payload "cp secrets .env")")"
check ".env: mv it -> deny" DENY "$(run "$(payload "mv .env /tmp/x")")"
check ".env: rm it -> deny" DENY "$(run "$(payload "rm .env")")"

# LEFT-BOUNDARY path variants — each is a different left-boundary character
# class in the regex ("/" for the path forms, quote chars, "=").
check ".env: ./ relative -> deny" DENY "$(run "$(payload "cat ./.env")")"
check ".env: ../ parent -> deny" DENY "$(run "$(payload "cat ../.env")")"
check ".env: absolute path -> deny" DENY "$(run "$(payload "cat /Users/x/proj/.env")")"
check ".env: single-quoted -> deny" DENY "$(run "$(payload "cat '.env'")")"
check ".env: double-quoted -> deny" DENY "$(run "$(payload "cat \".env\"")")"
check ".env: VAR= assignment -> deny" DENY "$(run "$(payload "VAR=.env cat \$VAR")")"

# RIGHT-BOUNDARY: a shell separator immediately after the token (no space)
# must still terminate it — these confirm the right-boundary class, not the
# verb.
check ".env: semicolon after -> deny" DENY "$(run "$(payload "cat .env;echo done")")"
check ".env: pipe after -> deny" DENY "$(run "$(payload "cat .env|grep KEY")")"
check ".env: && after -> deny" DENY "$(run "$(payload "cat .env && echo ok")")"

# SUFFIXED forms — the separate bash-side suffix branch (POSIX ERE has no
# negative lookahead, so these cannot be caught by the bare-token regex).
check ".env.local -> deny" DENY "$(run "$(payload "cat .env.local")")"
check ".env.production -> deny" DENY "$(run "$(payload "cat .env.production")")"
# .env.local.bak: a BACKUP of a real secret file. Its first suffix segment is
# "local", so the ${suffix%%.*} first-segment comparison must still deny it —
# this is the case that a naive "allow anything with a dotted suffix" or a
# whole-suffix comparison against the template list would get wrong.
check ".env.local.bak -> deny" DENY "$(run "$(payload "cat .env.local.bak")")"

# --- Near-miss ALLOW controls (over-blocking is the worse failure here) ----
# .envrc is direnv's file — a DIFFERENT file that shares the ".env" prefix.
# This is the single most important control in this block: it is what forces
# the right boundary to exclude word characters.
check ".envrc -> allow" ALLOW "$(run "$(payload "cat .envrc")")"
check ".envrc via direnv -> allow" ALLOW "$(run "$(payload "direnv allow .envrc")")"
# Committed templates — no real secrets, must stay readable.
check ".env.example -> allow" ALLOW "$(run "$(payload "cat .env.example")")"
check ".env.sample -> allow" ALLOW "$(run "$(payload "cat .env.sample")")"
check ".env.template -> allow" ALLOW "$(run "$(payload "cat .env.template")")"
check ".env.dist -> allow" ALLOW "$(run "$(payload "cat .env.dist")")"
# A docs file ABOUT the template: first suffix segment is "example", so the
# first-segment comparison allows it. A whole-suffix comparison would deny.
check ".env.example.md -> allow" ALLOW "$(run "$(payload "cat .env.example.md")")"
# No leading dot at all — these never contain the literal ".env" as a
# dotfile token.
check "environment.yml -> allow" ALLOW "$(run "$(payload "cat environment.yml")")"
check "env.example -> allow" ALLOW "$(run "$(payload "cat env.example")")"
check "docs/environment.md -> allow" ALLOW "$(run "$(payload "cat docs/environment.md")")"
# Bare env / printenv — unrelated commands that print the environment.
check "bare env -> allow" ALLOW "$(run "$(payload "env")")"
check "env piped -> allow" ALLOW "$(run "$(payload "env | sort")")"
check "printenv -> allow" ALLOW "$(run "$(payload "printenv")")"
check "npm run env -> allow" ALLOW "$(run "$(payload "npm run env")")"
# A non-dotfile *.env: left boundary requires a non-word char before the dot,
# so "myapp.env.example" is not treated as a .env dotfile at all.
check "myapp.env.example -> allow" ALLOW "$(run "$(payload "cat myapp.env.example")")"
# .venv (python virtualenv dir) merely starts with ".ven".
check ".venv -> allow" ALLOW "$(run "$(payload "python -m venv .venv")")"

# CASE VARIANCE. macOS (APFS) and Windows are case-INSENSITIVE by default, so
# ".ENV" opens the very same inode as ".env" — a case-sensitive matcher is
# defeated by pressing shift. The rest of this file's detectors already use
# grep -i, so matching case-insensitively here is the house convention.
# --- Boundary inversion + glob-expansion detection -------------------------
# The boundary rule is INVERTED (any non-filename character is a boundary),
# not an enumeration of permitted separators. Before that, 18 of 19 tested
# left-boundary characters let a command through. These cases pin the two
# behaviours the inversion and the glob predicate are FOR; they fail if
# either is weakened back toward an enumerated class.
#
# Family A — the literal token is present with a glob metacharacter after it.
check "glob suffix -> deny" DENY "$(run "$(payload "cat .env*")")"
# The leading-dot editor-swap name. '.' counts as a LEFT boundary, and the
# suffix loop's sed must strip one leading non-filename char (not "up to the
# first dot") or the suffix reads as the whole token and the file is allowed.
check "leading-dot swap -> deny" DENY "$(run "$(payload "cat ..env.swp")")"
check "leading-dot swo -> deny" DENY "$(run "$(payload "cat ..env.swo")")"
#
# Family B — NO literal token on the line at all. Each of these expands to
# exactly the real secret file, so no widening of a literal matcher reaches
# them; they are caught by matching the glob PATTERN's committing prefix.
check "single-char wildcard -> deny" DENY "$(run "$(payload "cat .en?")")"
check "mid-star -> deny" DENY "$(run "$(payload "cat .e*v")")"
check "bracket class -> deny" DENY "$(run "$(payload "cat .en[v]")")"
check "bracket range -> deny" DENY "$(run "$(payload "cat .en[a-z]")")"
# A bracket group wrapping ONE literal char is that char plus a metacharacter,
# so it commits to the name while carrying no literal token. Collapsed before
# matching rather than enumerating where a bracket may sit.
check "bracket on e -> deny" DENY "$(run "$(payload "cat .[e]nv")")"
check "bracket on n -> deny" DENY "$(run "$(payload "cat .e[n]v")")"
check "all three bracketed -> deny" DENY "$(run "$(payload "cat .[e][n][v]")")"
# Ranges and negated classes are NOT collapsed — they commit to no specific
# character, so collapsing them would manufacture a commitment and over-block.
check "range glob -> allow" ALLOW "$(run "$(payload "ls .[a-z]*")")"
check "prefix star -> deny" DENY "$(run "$(payload "cat .en*")")"
#
# Over-block guard. A naive "could this glob expand onto the secret file"
# predicate was measured to deny 3 of 15 ordinary commands. These pin the
# rule that a token's LITERAL characters must COMMIT to the name: a bare or
# unanchored glob has no committing prefix and must stay allowed.
check "bare dot-glob -> allow" ALLOW "$(run "$(payload "ls .*")")"
check "bare star -> allow" ALLOW "$(run "$(payload "cat *")")"
check "bare star echo -> allow" ALLOW "$(run "$(payload "echo *")")"
check "extension glob -> allow" ALLOW "$(run "$(payload "cat *.md")")"
check "dir glob -> allow" ALLOW "$(run "$(payload "rm build/*")")"
# "envrc" is not a prefix of "env", so direnv's file is not a committing
# prefix even when globbed.
check "direnv glob -> allow" ALLOW "$(run "$(payload "ls .envrc*")")"
# A filename character precedes the dot, so this is not at a boundary.
check "prefixed glob -> allow" ALLOW "$(run "$(payload "cat myapp.env*")")"

check ".ENV upper -> deny" DENY "$(run "$(payload "cat .ENV")")"
check ".Env mixed -> deny" DENY "$(run "$(payload "cat .Env")")"
check ".ENV.LOCAL suffixed -> deny" DENY "$(run "$(payload "cat .ENV.LOCAL")")"
# The template allow-list must be case-insensitive TOO, or making the matcher
# case-blind converts these benign files from allowed into over-blocked.
check ".ENV.EXAMPLE -> allow" ALLOW "$(run "$(payload "cat .ENV.EXAMPLE")")"
check ".Env.Sample -> allow" ALLOW "$(run "$(payload "cat .Env.Sample")")"
# .ENVRC is direnv's file in caps — the right boundary (a word char follows)
# must keep excluding it regardless of case.
check ".ENVRC -> allow" ALLOW "$(run "$(payload "cat .ENVRC")")"
check ".VENV -> allow" ALLOW "$(run "$(payload "python -m venv .VENV")")"

# EDITOR BACKUPS / AUTOSAVES. These hold a byte-identical copy of the secret
# and appear in a repo without anyone choosing to create them. "~" (vim) and
# "#" (emacs autosave, which brackets the name on BOTH sides) were absent
# from the boundary classes, so the copies were reachable while the original
# was denied.
check ".env~ vim backup -> deny" DENY "$(run "$(payload "cat .env~")")"
check "#.env# emacs autosave -> deny" DENY "$(run "$(payload "cat '#.env#'")")"
# An emacs autosave of a SUFFIXED secret. This travels the suffix branch, not
# the bare-token branch above, so widening only the bare-token boundaries
# leaves it reachable while the whole suite still reads green — which is
# exactly the partial implementation this case exists to catch.
check "#.env.local# autosave of suffixed -> deny" DENY "$(run "$(payload "cat '#.env.local#'")")"
# The inverse, pinning that the widened boundaries did NOT swallow the
# template allow-list: a backup of a TEMPLATE holds no secret, so it stays
# allowed. Without this, denying every "~"-suffixed token would look correct.
check ".env.example~ backup of template -> allow" ALLOW "$(run "$(payload "cat .env.example~")")"
# The dotted backup forms already deny via the suffix branch (their first
# suffix segment is not on the template allow-list). Locked here as
# regressions, not as new coverage.
check ".env.swp -> deny" DENY "$(run "$(payload "cat .env.swp")")"
check ".env.bak -> deny" DENY "$(run "$(payload "cat .env.bak")")"
check ".env.save -> deny" DENY "$(run "$(payload "cat .env.save")")"

# NOT-OVER-BLOCKED. Case-insensitivity plus wider boundaries must not turn
# the gate into a blunt instrument on ordinary paths that merely contain
# "env" or a "~"/"#" character.
check "README.md -> allow" ALLOW "$(run "$(payload "cat README.md")")"
check ".environment -> allow" ALLOW "$(run "$(payload "cat .environment")")"
check "envsubst -> allow" ALLOW "$(run "$(payload "envsubst < config.tmpl")")"
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
check "ls -> allow" ALLOW "$(run "$(payload "ls -la")")"
check "git status -> allow" ALLOW "$(run "$(payload "git status")")"
check "git push (no force) -> allow" ALLOW "$(run "$(payload "git push origin main")")"
check "git reset --soft -> allow" ALLOW "$(run "$(payload "git reset --soft HEAD~1")")"
check "git commit (no --no-verify) -> allow" ALLOW "$(run "$(payload "git commit -m 'fix'")")"
check "echo hello -> allow" ALLOW "$(run "$(payload "echo hello")")"
check "cat file.txt -> allow" ALLOW "$(run "$(payload "cat file.txt")")"

# --- Edge cases ---
check "empty command -> allow" ALLOW "$(run '{"tool_input":{"command":""}}')"
check "no command field -> allow" ALLOW "$(run '{"tool_input":{}}')"

# --- Extended destructive blocklist ---
# Forced cleanup flags
check "git clean -fdx -> deny" DENY "$(run "$(payload "git clean -fdx")")"
check "git clean -f -> deny" DENY "$(run "$(payload "git clean -f .")")"
check "git clean -fd -> deny" DENY "$(run "$(payload "git clean -fd src/")")"
check "git clean -xf -> deny" DENY "$(run "$(payload "git clean -xf")")"
# benign git clean lookalikes
check "git cleanup script -> allow" ALLOW "$(run "$(payload "bash git-cleanup.sh")")"
check "git clean (no force) -> allow" ALLOW "$(run "$(payload "git clean -n")")"
check "git clean -n -> allow" ALLOW "$(run "$(payload "git clean -n -d")")"
# find --delete / -delete
check "find -delete -> deny" DENY "$(run "$(payload "find . -name '*.tmp' -delete")")"
check "find --delete -> deny" DENY "$(run "$(payload "find /tmp --delete")")"
# benign find
check "findings -> allow" ALLOW "$(run "$(payload "cat findings.txt")")"
check "find without delete -> allow" ALLOW "$(run "$(payload "find . -name '*.sh'")")"
# truncate -s
check "truncate -s0 -> deny" DENY "$(run "$(payload "truncate -s0 logfile.txt")")"
check "truncate -s 0 -> deny" DENY "$(run "$(payload "truncate -s 0 logfile.txt")")"
# shred
check "shred file -> deny" DENY "$(run "$(payload "shred secret.key")")"
check "shred -u -> deny" DENY "$(run "$(payload "shred -u credentials.txt")")"

finish
