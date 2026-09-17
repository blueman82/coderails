#!/usr/bin/env bash
# shellcheck disable=SC2016
# shellcheck disable=SC1091
source "$(dirname "$0")/destructive_bash_gate_common.sh"

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

# Forced cleanup, TAB-separated
check "git TAB clean TAB -f -> deny" DENY \
    "$(run "$(payload "git${TAB}clean${TAB}-f")")"
check "git TAB clean TAB --force -> deny" DENY \
    "$(run "$(payload "git${TAB}clean${TAB}--force")")"
# Dry-run cleanup, TAB-separated, must still allow
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
check "rm\${IFS}-rf -> deny" DENY "$(run "$(payload "rm\${IFS}-rf /tmp/x")")"
check "rm bare \$IFS -rf -> deny" DENY "$(run "$(payload "rm\$IFS-rf /tmp/x")")"
check "rm \${IFS:0:1}-rf -> deny" DENY "$(run "$(payload "rm\${IFS:0:1}-rf /tmp/x")")"
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
check "rm \${IFS:-y}-rf -> deny" DENY "$(run "$(payload "rm\${IFS:-y}-rf /tmp/x")")"
check "chmod \${IFS:-y}-R\${IFS:-y}777 -> deny" DENY \
    "$(run "$(payload "chmod\${IFS:-y}-R\${IFS:-y}777 /var/www")")"
check "git reset \${IFS:-y}--hard -> deny" DENY \
    "$(run "$(payload "git\${IFS:-y}reset\${IFS:-y}--hard HEAD~1")")"
check "DROP \${IFS:-y}TABLE -> deny" DENY "$(run "$(payload "DROP\${IFS:-y}TABLE users;")")"

# Negative substring offsets — \${IFS: -1} / \${IFS:(-1)} — bash requires the
# space (or parens) right after the colon to disambiguate a negative offset
# from the :- use-default operator; both still evaluate to trailing IFS
# whitespace and are real separators (an enumerated, non-exclude-only version
# of this fix missed this shape entirely — found by an independent grader).
check "rm \${IFS: -1}-rf -> deny" DENY "$(run "$(payload "rm\${IFS: -1}-rf /tmp/x")")"
check "rm \${IFS:(-1)}-rf -> deny" DENY "$(run "$(payload "rm\${IFS:(-1)}-rf /tmp/x")")"

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

finish
