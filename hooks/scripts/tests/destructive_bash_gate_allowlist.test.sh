#!/usr/bin/env bash
# shellcheck disable=SC1091
source "$(dirname "$0")/destructive_bash_gate_common.sh"

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
printf 'git-push-force-with-lease\n' >"$ALLOWLIST_REPO/.claude/destructive_allowlist"
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
printf 'git-push-force-with-lease\n' >"$NO_INTRA_REPO/.claude/destructive_allowlist"
check "allowlist present: --force-with-lease split via intra-token backslash-newline -> allow" ALLOW \
    "$(run_cwd "$(payload_with_cwd "git push --force-with-\\${NL}lease" "$NO_INTRA_REPO")" "$NO_INTRA_REPO")"

# 6. Empty allowlist file -> denied (mirrors test_gate.py empty-content no-op)
: >"$ALLOWLIST_REPO/.claude/destructive_allowlist"
check "empty allowlist file: force-with-lease -> deny" DENY \
    "$(run_cwd "$(payload_with_cwd "git push --force-with-lease" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"

# 7. Malformed/garbage allowlist content -> denied, not accidentally permit-all
printf '.*\nallow-everything\n--force\n' >"$ALLOWLIST_REPO/.claude/destructive_allowlist"
check "garbage allowlist content: force-with-lease -> deny" DENY \
    "$(run_cwd "$(payload_with_cwd "git push --force-with-lease" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"

# 8. Comment and blank lines ignored, keyword still recognized
printf '# comment\n\ngit-push-force-with-lease\n' >"$ALLOWLIST_REPO/.claude/destructive_allowlist"
check "comment/blank lines + keyword: force-with-lease -> allow" ALLOW \
    "$(run_cwd "$(payload_with_cwd "git push --force-with-lease" "$ALLOWLIST_REPO")" "$ALLOWLIST_REPO")"

# 9. Wrong-keyword allowlist does not leak into force-with-lease
printf 'git-commit-no-verify\n' >"$ALLOWLIST_REPO/.claude/destructive_allowlist"
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
printf 'git-push-force-with-lease\n' >"$OPT_REPO/.claude/destructive_allowlist"
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

finish
