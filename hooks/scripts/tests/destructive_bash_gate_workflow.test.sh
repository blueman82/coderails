#!/usr/bin/env bash
# shellcheck disable=SC2016
# shellcheck disable=SC1091
source "$(dirname "$0")/destructive_bash_gate_common.sh"

# --- Branch-aware in-Bash source edits on main ---
# on main — sed -i on a source file -> DENY
check "main: sed -i on .py -> deny" DENY "$(run_cwd "$(payload_with_cwd "sed -i 's/a/b/' foo.py" "$MAIN_REPO")" "$MAIN_REPO")"
# on main — redirect > into a .ts file -> DENY
check "main: redirect > .ts -> deny" DENY "$(run_cwd "$(payload_with_cwd "echo x > bar.ts" "$MAIN_REPO")" "$MAIN_REPO")"
# on main — tee into a SKILL.md -> DENY
check "main: tee SKILL.md -> deny" DENY "$(run_cwd "$(payload_with_cwd "tee skills/mything/SKILL.md" "$MAIN_REPO")" "$MAIN_REPO")"
# on main — tee into a command -> DENY
check "main: tee commands/x.md -> deny" DENY "$(run_cwd "$(payload_with_cwd "tee commands/prep.md" "$MAIN_REPO")" "$MAIN_REPO")"
# lookalike plugin-path filenames that merely CONTAIN "skills/"/"commands/" as a
# substring, not the actual plugin directory at a token boundary -> ALLOW
check "main: tee xcommands/prep.md -> allow" ALLOW "$(run_cwd "$(payload_with_cwd "tee xcommands/prep.md" "$MAIN_REPO")" "$MAIN_REPO")"
check "main: tee not-skills/x/SKILL.md -> allow" ALLOW "$(run_cwd "$(payload_with_cwd "tee not-skills/x/SKILL.md" "$MAIN_REPO")" "$MAIN_REPO")"
check "main: tee docs/notcommands/x.md -> allow" ALLOW "$(run_cwd "$(payload_with_cwd "tee docs/notcommands/x.md" "$MAIN_REPO")" "$MAIN_REPO")"
# genuine nested plugin path (real skills/ dir under an unrelated parent) -> DENY
check "main: tee vendor/skills/x/SKILL.md -> deny" DENY "$(run_cwd "$(payload_with_cwd "tee vendor/skills/x/SKILL.md" "$MAIN_REPO")" "$MAIN_REPO")"
# on main — sed -i on README.md (non-source) -> ALLOW
check "main: sed -i README.md -> allow" ALLOW "$(run_cwd "$(payload_with_cwd "sed -i 's/a/b/' README.md" "$MAIN_REPO")" "$MAIN_REPO")"
# on feature branch — same commands -> ALLOW
check "feat: sed -i on .py -> allow" ALLOW "$(run_cwd "$(payload_with_cwd "sed -i 's/a/b/' foo.py" "$FEAT_REPO")" "$FEAT_REPO")"
check "feat: redirect > .ts -> allow" ALLOW "$(run_cwd "$(payload_with_cwd "echo x > bar.ts" "$FEAT_REPO")" "$FEAT_REPO")"
check "feat: tee SKILL.md -> allow" ALLOW "$(run_cwd "$(payload_with_cwd "tee skills/mything/SKILL.md" "$FEAT_REPO")" "$FEAT_REPO")"
# perl -i on main -> DENY
check "main: perl -i on .go -> deny" DENY "$(run_cwd "$(payload_with_cwd "perl -i -pe 's/old/new/g' main.go" "$MAIN_REPO")" "$MAIN_REPO")"
# >> append into source on main -> DENY
check "main: >> into .js -> deny" DENY "$(run_cwd "$(payload_with_cwd "echo 'foo' >> app.js" "$MAIN_REPO")" "$MAIN_REPO")"

# --- git clean long/separated force flags ---
check "git clean --force -> deny" DENY "$(run "$(payload "git clean --force")")"
check "git clean -d -f -> deny" DENY "$(run "$(payload "git clean -d -f")")"
check "git clean -d --force -> deny" DENY "$(run "$(payload "git clean -d --force")")"
check "git clean bare -> allow" ALLOW "$(run "$(payload "git clean")")"
check "git clean --dry-run -> allow" ALLOW "$(run "$(payload "git clean --dry-run")")"
check "git clean -i -> allow" ALLOW "$(run "$(payload "git clean -i")")"

# --- truncate --size long flag ---
check "truncate --size=0 x -> deny" DENY "$(run "$(payload "truncate --size=0 file.txt")")"
check "truncate --size 0 x -> deny" DENY "$(run "$(payload "truncate --size 0 file.txt")")"

# --- cwd fallback (cwd absent → hook resolves branch from $PWD) ---
# When .cwd is absent, the hook falls back to $PWD (destructive_bash_gate.sh:96).
# The branch outcome therefore depends on $PWD, so we pin $PWD to a known repo via
# a subshell `cd` rather than relying on the ambient branch of the coderails
# checkout — which previously made this test flip ALLOW/DENY depending on whether
# coderails itself was on main.
check "no-cwd payload, PWD on feat -> allow" ALLOW "$(cd "$FEAT_REPO" && run "$(payload "sed -i 's/a/b/' foo.py")")"
check "no-cwd payload, PWD on main -> deny" DENY "$(cd "$MAIN_REPO" && run "$(payload "sed -i 's/a/b/' foo.py")")"

# --- target-repo resolution (file in feature-branch repo, session cwd on main) ---
# Target file is in FEAT_REPO (on a feature branch). The hook must not over-block.
check "feature-repo target, main cwd -> allow" ALLOW "$(run_cwd "$(payload_with_cwd "sed -i 's/a/b/' $FEAT_REPO/foo.py" "$MAIN_REPO")" "$MAIN_REPO")"

# --- redirect extension anchored to end-of-token ---
check "echo > output.go.log -> allow" ALLOW "$(run_cwd "$(payload_with_cwd "echo x > output.go.log" "$MAIN_REPO")" "$MAIN_REPO")"
check "echo > foo.py.bak -> allow" ALLOW "$(run_cwd "$(payload_with_cwd "echo x > foo.py.bak" "$MAIN_REPO")" "$MAIN_REPO")"
check "echo > changes.py.txt -> allow" ALLOW "$(run_cwd "$(payload_with_cwd "echo x > changes.py.txt" "$MAIN_REPO")" "$MAIN_REPO")"
check "echo > real.py -> deny" DENY "$(run_cwd "$(payload_with_cwd "echo x > real.py" "$MAIN_REPO")" "$MAIN_REPO")"
check "find && echo --delete -> allow" ALLOW "$(run "$(payload "find . -name x && echo --delete")")"
check "find; rm --delete-like -> allow" ALLOW "$(run "$(payload "find . -name tmp; echo done --delete-style")")"

# --- cp/mv/dd write-to-source on main vs feature branch ---
check "main: cp to foo.py -> deny" DENY "$(run_cwd "$(payload_with_cwd "cp /tmp/x foo.py" "$MAIN_REPO")" "$MAIN_REPO")"
check "main: mv to foo.go -> deny" DENY "$(run_cwd "$(payload_with_cwd "mv /tmp/x foo.go" "$MAIN_REPO")" "$MAIN_REPO")"
check "main: dd of=foo.py -> deny" DENY "$(run_cwd "$(payload_with_cwd "dd of=foo.py if=/tmp/x" "$MAIN_REPO")" "$MAIN_REPO")"
check "feat: cp to foo.py -> allow" ALLOW "$(run_cwd "$(payload_with_cwd "cp /tmp/x foo.py" "$FEAT_REPO")" "$FEAT_REPO")"
check "feat: mv to foo.go -> allow" ALLOW "$(run_cwd "$(payload_with_cwd "mv /tmp/x foo.go" "$FEAT_REPO")" "$FEAT_REPO")"
check "feat: dd of=foo.py -> allow" ALLOW "$(run_cwd "$(payload_with_cwd "dd of=foo.py if=/tmp/x" "$FEAT_REPO")" "$FEAT_REPO")"
check "main: cp to SKILL.md -> deny" DENY "$(run_cwd "$(payload_with_cwd "cp /tmp/x skills/mything/SKILL.md" "$MAIN_REPO")" "$MAIN_REPO")"
check "main: mv to commands/x.md -> deny" DENY "$(run_cwd "$(payload_with_cwd "mv /tmp/x commands/prep.md" "$MAIN_REPO")" "$MAIN_REPO")"
# cp/mv to a non-source file on main -> allow
check "main: cp to README.md -> allow" ALLOW "$(run_cwd "$(payload_with_cwd "cp /tmp/x README.md" "$MAIN_REPO")" "$MAIN_REPO")"

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
    "$(run "$(payload 'VERIFICATION_LEVEL=$(jq -r .verification_level /tmp/e.json) && bash scripts/post_evals.sh post 19 "verification_level zero clean note"')")"
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

finish
