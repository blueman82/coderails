#!/bin/bash
# PreToolUse Bash hook: permanently block destructive commands.
# Detects rm -rf, git push --force, git reset --hard, SQL DROP/TRUNCATE, dd, mkfs, chmod -R 777,
# git clean (force), find -delete/--delete, truncate -s/--size, shred.
# Also blocks in-Bash source-file edits (sed -i, perl -i, redirect >, >>, tee, cp, mv, dd of=)
# on main/master branches — closing the hole that no_edit_on_main (Write/Edit only) misses.
# Returns permissionDecision="deny" — there is no approval path; use a safer alternative or add a settings.json permission rule.

IFS= read -r -d '' -t 5 input || true
cmd=$(echo "$input" | jq -r '.tool_input.command // empty')

# Normalize $IFS expansions to a single space, once, immediately after $cmd is
# assigned. Bash honours $IFS/${IFS}/${IFS:offset:length}/${IFS<op>word} as a
# live expansion that yields whitespace (IFS is set by default in any real
# shell) and is then used by bash itself to split the surrounding text into
# argv tokens — so a command built with `rm${IFS}-rf` instead of `rm -rf`
# contains NO whitespace CHARACTER anywhere in the literal tool_input string.
# Every detector below (the git-clean block, find, truncate, shred, the
# monolithic blocklist, the source-edit blocks, and the derived
# force_cmd_flat/cmd_flat vars) greps `$cmd` (or something derived from it)
# for a literal whitespace class — none of them evaluate the string as bash
# would, so an IFS-expansion form is literally invisible text to every one of
# them and evades the entire file. Doing the substitution once here, before
# any detector runs, fixes all of them in one place.
#
# Two passes, built EXCLUDE-ONLY rather than as an enumeration of offset/
# operator shapes: every ${IFS<body>} expands to IFS's own whitespace value
# EXCEPT the two shapes below, so listing "the whitespace forms" one by one
# is an incomplete, whack-a-mole strategy (numeric substring offsets can be
# negative and spelled `: -N` or `:(-N)` to disambiguate from the :- operator
# — a shape an earlier, enumerated version of this fix missed entirely).
# Instead: collapse ${IFS<body>} to a space UNLESS <body> starts with the
# ONE operator whose branches are inverted.
#   1. Braced forms. After "IFS", the expansion is delimited by "}" or
#      continues with a body whose first character determines the operator.
#      Collapsed to a single space (real whitespace, verified against bash
#      ground truth, not just token inspection):
#        ${IFS}                          bare
#        ${IFS:N} ${IFS:N:M}             substring, N/M signed digits,
#                                         including "space-then-minus" or
#                                         parenthesized negative offsets
#                                         (${IFS: -1}, ${IFS:(-1)}) — bash
#                                         requires that space/paren to tell a
#                                         negative offset apart from the :-
#                                         use-default operator; both forms
#                                         still evaluate to trailing IFS
#                                         whitespace
#        ${IFS:-word} ${IFS-word}        use-default — IFS is set, so this
#                                         evaluates to IFS's OWN value (the
#                                         default word is never used), i.e.
#                                         whitespace, not the word
#        ${IFS:=word} ${IFS=word}        assign-default — same reasoning
#        ${IFS:?word} ${IFS?word}        error-if-unset — same reasoning
#      NOT matched by this pass at all (already fully handled by the
#      WORD-EMITTING RULE below, which runs FIRST and consumes every :+/+
#      shape before this pass ever sees the text):
#        ${IFS:+word} ${IFS+word}        alternate-value — the ONE operator
#                                         whose branches are inverted: since
#                                         IFS is normally set, this
#                                         substitutes the literal WORD, not
#                                         IFS's whitespace value (verified:
#                                         bash expands `${IFS:+word}` to the
#                                         literal text "word" when IFS is
#                                         set). Handled by pass 0's
#                                         word-emitting rule, not this pass.
#        ${IFSx} (any identifier char    a DIFFERENT variable name, not an
#          right after IFS)              operator on IFS at all — the first
#                                         body character must not itself be
#                                         an identifier char ([A-Za-z0-9_]),
#                                         mirroring the bare-$IFS boundary
#                                         check in pass 2 below.
#        ${#IFS}                         yields the length ("3", a digit,
#                                         not whitespace) — moot here since
#                                         this pattern only ever anchors on
#                                         literal "${IFS", never "${#".
#      This exclude-only shape was checked against bash ground truth for the
#      common operators (bare, substring incl. negative offsets, use-default,
#      assign-default, error-if-unset, alternate-value, length). It is
#      BEST-EFFORT, NOT complete — a pre-expansion regex cannot fully match
#      bash tokenization, and review found this the hard way. KNOWN CEILING
#      (deliberate, same class as the quoted-path and chmod-ordering ceilings
#      elsewhere in this file / AGENTS.md — obfuscation no normal workflow
#      emits, and an actor who can craft it already has shell capability):
#        - a WORD containing a nested ${...} / $(...) (e.g. ${IFS:-${OTHER}},
#          ${IFS:+${IFS}}) — the body `[^}]*` stops at the first "}". This
#          applies equally to pass 0's own word capture below: a :+/+ word
#          holding a nested expansion is only emitted up to its first "}",
#          same ceiling, not a separate one.
#        - a substring form that expands to the EMPTY string (${IFS:0:0},
#          ${IFS:3}, offset past IFS's 3 bytes): this pass OVER-collapses it
#          to a space, fabricating a separator bash does not create. This
#          only ever fails OPEN on obfuscated input that base also allowed —
#          it never turns a base-DENIED real command into an allow (verified
#          non-regression), so it is a missed catch, never a lost one.
#        - an arbitrary user variable holding whitespace (X=' '; rm${X}-rf) —
#          unbounded, no regex can enumerate variable names.
#      These are recorded as a future unit (see the residual handoff); closing
#      them needs position-based tokenisation, not more normalization passes.
#   0. WORD-EMITTING RULE FOR :+/+ (runs BEFORE pass 1, on the untouched
#      $cmd): ${IFS:+word} / ${IFS+word} substitute the literal WORD (see
#      above), and the word is attacker-controlled — so this pass emits the
#      captured word VERBATIM in place of the whole expansion, for ANY word,
#      rather than collapsing the expansion to a single space. A blanket
#      collapse-to-space would be WRONG in two directions at once: it erases
#      real non-whitespace text (`${IFS:+SET}` must become the literal "SET",
#      not " "), and — the bug two prior versions of this pass had — it can
#      UNDER-collapse a word that is whitespace-led but not whitespace-only
#      (`${IFS:+ -r}` collapsed to " " gives "rm f", which still ALLOWS at
#      the gate while bash still runs `rm -rf`; found by security review,
#      confirmed by ground truth). Emitting the word verbatim glues correctly
#      either way: a whitespace-only word (`${IFS:+ }`) becomes a real
#      separator; a whitespace-LED word (`${IFS:+ -r}`) becomes the intended
#      flag text with its separator attached (`rm${IFS:+ -r}f` -> `rm -rf`);
#      a non-whitespace word (`${IFS:+SET}`, `${IFS:+x -r}`) is unchanged
#      text, exactly as bash would expand it, so it stays exactly as
#      dangerous or harmless as if it had been typed literally (an EMPTY
#      word, `${IFS:+}`, emits nothing, gluing the surrounding tokens into a
#      single inert token — `rm${IFS:+}-rf` -> `rm-rf` — verified harmless,
#      matching bash's own empty-expansion behaviour of "no token boundary
#      introduced"). This also covers a word that is flag text with NO
#      leading whitespace of its own, separated from the previous token by
#      its own separate space or ${IFS} (`rm ${IFS:+-rf} x`,
#      `rm${IFS}${IFS:+-rf} x`) — under the old blanket exclusion the
#      `${IFS:+-rf}` stayed opaque in both and evaded every detector while
#      bash still expanded it to a real -rf token.
#      [[:space:]] (not \t) is used in every OTHER pass in this file for the
#      same documented reason (POSIX bracket expressions don't treat \t as
#      an escape, so a literal-backslash-t class silently fails to match a
#      real tab byte) — this pass has no [[:space:]] of its own since it
#      captures the word unconditionally rather than testing its class, so
#      that footgun does not apply here, but a tab-led word is still
#      exercised by a dedicated test given the emphasis elsewhere in this
#      file on tab as its own bypass vector. A NEWLINE-led word (e.g.
#      ${IFS:+<NL>-r}) is NOT closed by this pass: sed operates per-line, so
#      a real embedded newline splits the expansion across two lines before
#      this pass's regex ever sees it as one string, and even a hypothetical
#      cross-line match would still only feed the downstream line-oriented
#      detectors (grep/pattern=) a verb and flag on separate lines. This is
#      the SAME pre-existing architectural ceiling as the documented
#      backslash-newline-continuation gap in this file's test suite (a
#      literal `rm`+newline+`-rf`, no $IFS involved at all, already evades
#      detection with no change from this PR — confirmed at both base and
#      head) — not a gap this :+/+ fix introduces or leaves open within its
#      own family, and not closable by another normalization pass.
#      CEILING (unchanged by this pass, documented below with the other
#      pass-1 ceilings): a word containing a NESTED ${...}/$(...) is not
#      resolved by this pass either — `[^}]*` still stops at the first "}",
#      so `${IFS:+${OTHER}}` is captured only up to that inner "}" and the
#      remainder is left as stray text. That needs recursive/position-based
#      parsing, not another sed pass; same ceiling as documented for pass 1.
#   2. Bare $IFS: only when NOT followed by an identifier character
#      ([A-Za-z0-9_]) or followed by end-of-string. Bash variable names
#      extend as far as identifier characters continue, so `$IFSOMETHING` is
#      a wholly different (and irrelevant) variable, not $IFS at all — the
#      lookahead-substitute (capture the boundary char, splice it back in
#      unconsumed) is required so `$IFS-rf` collapses to ` -rf` but
#      `$IFSOMETHING` is left completely alone.
# A benign command that only MENTIONS IFS in an unrelated way (e.g.
# echo "${IFS}") still normalizes to a literal space in that position, same
# as before — it does not gain or lose any blocklist keyword by doing so, so
# it stays ALLOWED; the substitution changes whitespace, never introduces or
# removes a destructive verb/flag token.
cmd=$(printf '%s' "$cmd" | sed -E 's/\$\{IFS:?\+([^}]*)\}/\1/g' | sed -E 's/\$\{IFS(\}|[^A-Za-z0-9_:+}][^}]*\}|:[^+}][^}]*\})/ /g' | sed -E 's/\$IFS([^A-Za-z0-9_]|$)/ \1/g')

if [ -z "$cmd" ]; then
  exit 0
fi

deny() {
  local pat="$1"
  # route: the concrete safe alternative for this specific pattern, so the
  # message doesn't just state a prohibition and withhold the way around it.
  # Keyed on $pat's own text (set by each call site below via grep -oiE or a
  # literal string) — this only changes what the DENY message SAYS, never
  # which commands reach deny() in the first place.
  # Matched against a normalised copy: the call sites feed $pat from a
  # case-insensitive grep whose blocklist regexes allow runs of whitespace
  # (`git +reset +--hard`), so a command reaches here with its own casing and
  # internal spacing preserved and would otherwise miss every specific branch
  # and take the generic route. Lowercase and collapse whitespace runs to a
  # single space for the lookup only — the message still reports $pat as it
  # was actually matched. tr rather than a bash 4 parameter expansion:
  # this machine's bash is 3.2, where `${pat,,}` aborts the hook and it
  # denies nothing.
  local route
  local pat_lc
  pat_lc=$(printf '%s' "$pat" | tr '[:upper:]' '[:lower:]' | tr -s '[:space:]' ' ')
  case "$pat_lc" in
    *"git reset --hard"*)
      route="Safe route: park the commits first with 'git branch backup/<desc> <ref>', then use 'git reset --keep <ref>' instead of --hard — --keep applies the same move but REFUSES (errors out) rather than clobbering when it would discard uncommitted working-tree changes, and the backup branch keeps the moved-past commits recoverable either way."
      ;;
    "rm "*)
      route="Safe route: for a single file, use 'unlink <file>' instead of rm -rf. For a directory or multiple files, move the target into a temp dir (e.g. 'mkdir -p /tmp/trash && mv <target> /tmp/trash/') instead of deleting it outright."
      ;;
    *"git push --force"*)
      route="Safe route: use 'git push --force-with-lease' instead of a naked --force — it refuses to overwrite a remote ref that has moved since your last fetch. Note --force-with-lease is ALSO blocked by this hook by default; add the exact line 'git-push-force-with-lease' to .claude/destructive_allowlist in the target repo to opt in before using it."
      ;;
    "git clean"*)
      route="Safe route: preview what would be removed first with 'git clean -n' (dry-run — lists targets, deletes nothing), or use 'git clean -i' for an interactive prompt per file/directory. Both are already permitted by this hook; only the force forms (-f/--force) are blocked."
      ;;
    *"find"*"-delete"*|*"find"*"--delete"*)
      route="Safe route: there is no safe equivalent for the deletion itself. Preview the exact match set first by replacing -delete with -print (or -print0 piped to xargs -0 ls) and reviewing the list before deleting any other way. To allow this pattern, add a Bash permission rule to settings.json."
      ;;
    *"truncate -s"*|*"truncate --size"*)
      route="Safe route: there is no safe equivalent — truncate destroys file content in place. Back up the file first ('cp <file> <file>.bak') if you need to recover it, or find a non-destructive way to achieve the goal (e.g. rotate the log instead of truncating it). To allow this pattern, add a Bash permission rule to settings.json."
      ;;
    *"shred"*)
      route="Safe route: there is no safe equivalent — shred exists specifically to make content unrecoverable. If you only meant to delete the file (not securely wipe it), move it to a temp dir instead ('mkdir -p /tmp/trash && mv <file> /tmp/trash/'). To allow shred itself, add a Bash permission rule to settings.json."
      ;;
    *"drop table"*|*"drop database"*|*"drop schema"*)
      route="Safe route: there is no safe equivalent — DROP permanently destroys the object and its data. Take a backup/dump first if the data must be recoverable, and confirm you're pointed at the intended database before running any destructive DDL directly. To allow this pattern, add a Bash permission rule to settings.json."
      ;;
    *"truncate table"*)
      route="Safe route: there is no safe equivalent — TRUNCATE TABLE removes all rows and is not equivalent in safety to a scoped DELETE. Take a backup/dump first if the data must be recoverable. To allow this pattern, add a Bash permission rule to settings.json."
      ;;
    *"dd if="*)
      route="Safe route: there is no safe equivalent — dd writes raw bytes to its target with no confirmation. Double-check the of= target device/file before running it directly, and confirm it isn't a mounted disk. To allow this pattern, add a Bash permission rule to settings.json."
      ;;
    *"mkfs."*)
      route="Safe route: there is no safe equivalent — mkfs reformats a filesystem and destroys existing data on it. Confirm the target device is correct (not a mounted or in-use disk) before running it directly. To allow this pattern, add a Bash permission rule to settings.json."
      ;;
    *"chmod -r 777"*)
      route="Safe route: use narrower recursive bits instead of a blanket 777 — 'chmod -R u+rwX,go+rX <path>' grants the owner read/write (and execute only on directories/already-executable files) while giving group/other read access, without making everything world-writable and world-executable."
      ;;
    *"git commit"*"--no-verify"*)
      route="Safe route: fix the failing pre-commit hook and re-run 'git commit' without --no-verify, rather than bypassing it — the hook exists to catch something before commit. If the hook itself is broken (not the change), fix the hook, don't skip it."
      ;;
    *)
      route="No specific safe route is recorded for this pattern. To allow it, add a Bash permission rule to settings.json, or find a non-destructive equivalent for what you're trying to do."
      ;;
  esac
  jq -n --arg pat "$pat" --arg cmd "$cmd" --arg route "$route" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: ("Destructive pattern detected: " + $pat + "\nFull command: " + $cmd + "\nThis command is permanently blocked. " + $route)
    }
  }'
  exit 0
}

# ── Permanent blocklist ────────────────────────────────────────────────────

# git clean with any force flag — matches combined short flags (-f, -fd, -fdx, -xf)
# OR long flag --force OR separated flag like "-d -f".
# Also matches --force and multi-token "-d -f" patterns.
# Strategy: deny "git clean" when the arg string contains -f (combined short flag)
# or --force (anywhere). Excludes: bare "git clean", dry-run, interactive.
if echo "$cmd" | grep -qiE '\bgit[[:space:]]+clean\b'; then
  # Extract everything after "git clean" as the args portion
  args=$(echo "$cmd" | sed -E 's/.*\bgit[[:space:]]+clean\b//')
  # Allow bare "git clean" (no args)
  if [ -n "$(echo "$args" | tr -d ' \t')" ]; then
    # Allow dry-run forms: -n / --dry-run
    if echo "$args" | grep -qE '(^|[[:space:]])--dry-run([[:space:]]|$)|(^|[[:space:]])-[a-zA-Z]*n[a-zA-Z]*([[:space:]]|$)'; then
      : # dry-run — allow
    # Allow interactive: -i / --interactive
    elif echo "$args" | grep -qE '(^|[[:space:]])-[a-zA-Z]*i[a-zA-Z]*([[:space:]]|$)|(^|[[:space:]])--interactive([[:space:]]|$)'; then
      : # interactive — allow
    # Deny force: --force or -f in any combined/separated form
    elif echo "$args" | grep -qE '(^|[[:space:]])--force([[:space:]]|$)|(^|[[:space:]])-[a-zA-Z]*f[a-zA-Z]*([[:space:]]|$)'; then
      deny "git clean (force)"
    fi
  fi
fi

# find ... -delete or find ... --delete
# The .* must not cross a shell separator (;, &&, ||, |).
# Only match -delete/--delete in the same shell token group as "find".
if echo "$cmd" | grep -qiE '\bfind\b[^;|&]*([[:space:]]-delete|[[:space:]]--delete)'; then
  deny "find -delete"
fi

# truncate with size flag — truncates file content
# Also catches --size / --size=N long forms.
if echo "$cmd" | grep -qiE '\btruncate[[:space:]]+(-s|--size[=[:space:]])'; then
  deny "truncate -s/--size"
fi

# shred (secure file deletion / overwrite)
if echo "$cmd" | grep -qiE '\bshred\b'; then
  deny "shred"
fi

# Session cwd, read from the hook payload (.cwd), falling back to $PWD.
# Resolved here (rather than only at its later use below) because the
# force-with-lease allowlist check below also needs it.
cwd=$(echo "$input" | jq -r '.cwd // empty')
[ -z "$cwd" ] && cwd="$PWD"  # Falls back to $PWD when .cwd is absent.

# allowlist_permits: checks whether .claude/destructive_allowlist (resolved
# against the payload cwd's repo root) contains an exact-match, whole-line
# keyword. Closed keyword vocabulary only — the file is never eval'd or
# spliced into a regex, so malformed/garbage content can only fail to match,
# never widen what's permitted. Missing/empty/garbage file -> permits nothing
# (fail CLOSED).
allowlist_permits() {
  local keyword="$1"
  local root
  root=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null)
  local path
  if [ -n "$root" ]; then
    path="$root/.claude/destructive_allowlist"
  else
    path="$cwd/.claude/destructive_allowlist"
  fi
  [ -f "$path" ] || return 1
  grep -qxF "$keyword" "$path" 2>/dev/null
}

# git push --force / -f / --force-with-lease
# Carved out of the monolithic blocklist below because POSIX ERE alternation
# (via grep -E, no BASH_REMATCH here) can't report WHICH alternative matched —
# needed to allow the narrower --force-with-lease shape while still denying
# naked --force/-f unconditionally, even when both appear on the same line.
# The naked-force sub-pattern also matches short-flag CLUSTERS (e.g. -uf,
# -fu, -ufd — git's own getopt-style combined short-flag behaviour), mirroring
# this file's existing git-clean force detector above (line 47) rather than
# only a standalone -f token, which a combined cluster would otherwise evade.
# All token boundaries use [[:space:]] (not a literal space) — bash's default
# IFS splits on space, tab, AND newline, so a tab between flags on one
# tool_input line produces the same real argv split as a space would; a
# literal-space-only boundary here previously let a tab-separated naked
# force slip past undetected while a space-separated one correctly denied.
#
# force_cmd_flat: $cmd normalised for matching below. Two passes, in order:
#   1. Splice backslash-newline PAIRS out entirely (awk, RS set to the
#      literal pair). Bash's own line-continuation removes both the
#      backslash and the newline with NOTHING inserted in their place,
#      fusing the characters on either
#      side into one token — e.g. `--for` + backslash-newline + `ce`
#      becomes the single real argv token `--force`. A naive `tr '\n' ' '`
#      instead REPLACES the newline with a space and leaves the backslash
#      behind, producing `--for\ ce` (two tokens, stray backslash) — the
#      regex never sees a contiguous "--force" and a continuation split
#      INSIDE a flag word (not just between two separate flag tokens)
#      bypassed detection entirely, with no allowlist needed at all.
#   2. THEN flatten any remaining bare (non-backslash-preceded) newlines to
#      spaces, for the inter-token case: `echo "$cmd" | grep` is inherently
#      line-oriented — grep's `.` and `[[:space:]]` can never match ACROSS
#      a newline no matter how the character class is written, so two
#      flags on separate physical lines (joined into one logical command
#      by a continuation) still need normalising to be visible to a
#      single-line regex.
# Scoped locally (not reusing the file's later cmd_flat, defined further
# down for the substitution-check block and not in scope yet here — and
# that later cmd_flat has the SAME splice gap this fixes, since it also
# only does a plain tr; out of scope to change here, flagged separately).
force_cmd_flat=$(printf '%s' "$cmd" | awk 'BEGIN{RS="\\\\\n"} {printf "%s", $0}' | tr '\n' ' ')
naked_force_re='(--force([^-]|$)|(^|[[:space:]])-[a-zA-Z]*f[a-zA-Z]*([[:space:]]|$))'
# git_push_re: "git" followed by zero or more git GLOBAL options, then "push".
# A bare `git[[:space:]]+push` trigger is defeated by any global option placed
# between the two (git -c NAME=VALUE push, git --no-pager push, git -C path
# push, ...) — the option makes "git" and "push" no longer adjacent, so the
# naked-force detector below never even looks at the rest of the line. git_opt_tok
# covers the three shapes global options take: -c/-C with a separate-token
# argument, a long option with an optional attached =value, and any other
# short flag. Bounded to 20 repetitions — git itself has no limit on
# repeated -c, so any fixed bound is a residual gap in principle, but 20
# chained global options is far beyond any real invocation and this keeps
# the match from running unbounded across an unrelated line. A -c/-C value
# containing a quoted space (e.g. -c "user.name=John Doe") also isn't
# matched by the single-token value arm below — same class as this file's
# documented "quoted paths with spaces... remain uncaught" ceiling elsewhere
# (AGENTS.md), not something a line-oriented ERE can fix without quote-aware
# tokenising; both gaps pre-date this fix (confirmed identical on
# pre-fix main) and are narrowed, not introduced, by it.
git_opt_tok='(-[cC][[:space:]]+[^[:space:]]+|--[a-zA-Z][a-zA-Z-]*(=[^[:space:]]*)?|-[a-zA-Z]+)'
git_push_re="\\bgit\\b([[:space:]]+${git_opt_tok}){0,20}[[:space:]]+push\\b"
if echo "$force_cmd_flat" | grep -qiE "${git_push_re}.*(${naked_force_re}|--force-with-lease\\b)"; then
  if echo "$force_cmd_flat" | grep -qiE "${git_push_re}[[:space:]]+.*--force-with-lease\\b" \
     && ! echo "$force_cmd_flat" | grep -qiE "${git_push_re}.*${naked_force_re}" \
     && allowlist_permits "git-push-force-with-lease"; then
    : # allowlisted force-with-lease, no naked --force present — allow
  else
    deny "git push --force"
  fi
fi

# ── Original permanent blocklist ─────────────────────────────────────────────
# All token separators below use [[:space:]] (POSIX class: space, tab,
# newline, etc.), never a literal space. A literal-space-only "+" only
# matches commands whose flags are separated by an actual space character —
# a tab (or other whitespace) between tokens is still a real argv split once
# bash parses the line (IFS defaults to space+tab+newline), but a
# literal-space regex never sees it as a separator, so a tab-separated form
# of every pattern here (rm, git reset --hard, DROP/TRUNCATE, chmod -R 777,
# git commit --no-verify) previously matched nothing and evaded the entire
# blocklist. [[:space:]] is POSIX ERE and confirmed working under this
# machine's bash 3.2.57 grep -E — unlike a bash 4-only construct
# (${var,,}, declare -A, mapfile), it carries no version risk.
pattern='\brm[[:space:]]+(-[rRfF]+|--recursive|--force)|\bgit[[:space:]]+reset[[:space:]]+--hard|\bDROP[[:space:]]+(TABLE|DATABASE|SCHEMA)\b|\bTRUNCATE[[:space:]]+TABLE\b|\bdd[[:space:]]+if=|\bmkfs\.|\bchmod[[:space:]]+-R[[:space:]]+777|\bgit[[:space:]]+commit[[:space:]]+.*--no-verify'

if echo "$cmd" | grep -qiE "$pattern"; then
  matched=$(echo "$cmd" | grep -oiE "$pattern" | head -1)
  deny "$matched"
fi

# ── Branch-aware in-Bash source edits on main/master ──────────────────────
# Blocks: sed -i, perl -i, redirect (>/>>), tee, cp <src> FILE, mv <src> FILE, dd of=FILE
# targeting source files (.py .ts .tsx .js .jsx .go) or plugin source
# (skills/*/SKILL.md, commands/*.md).
# Best-effort: shell redirect parsing is imperfect; this catches the common forms
# but cannot catch all shell constructs (e.g. here-docs, process substitution,
# variable filenames, quoted paths with spaces, python -c open(...)).
# On feature branches these patterns are allowed.
#
# Branch resolution strategy:
# - For cp/mv/dd: parse the target file path from the command and resolve its
#   repo branch directly (target-repo resolution), mirroring no_edit_on_main.sh.
#   Falls back to cwd-branch if the target path can't be resolved as a git repo.
# - For sed/perl/redirect/tee: parse the target file path and prefer target-repo
#   resolution; fall back to cwd-branch if the path is not resolvable.
# - Session cwd is resolved earlier above (needed by the force-with-lease
#   allowlist check too).

# Source-file extensions pattern (anchored to end-of-token to avoid false matches
# like foo.py.bak or output.go.log). Matches only tokens ENDING in a source ext.
# Right boundary uses [[:space:]] (not a literal space) alongside the quote
# chars, for the same reason as every other separator in this file: a tab
# after the extension is a real token break bash itself recognises, and a
# literal-space-only bracket let a source path followed by a TAB (rather
# than end-of-string, a space, or a quote) evade detection entirely.
src_ext='\.(py|ts|tsx|js|jsx|go)([[:space:]'"'"'"]|$)'
# Plugin source pattern (skills/*/SKILL.md or commands/*.md).
# Left-anchored to a path/token boundary (start-of-string, whitespace,
# quote, or a preceding "/") so a GLUED lookalike word like
# "xcommands/prep.md" or "not-skills/x/SKILL.md" — which merely CONTAINS
# the substring, not an actual skills/ or commands/ path segment — doesn't
# false-positive, while a genuinely nested real path like
# "vendor/skills/x/SKILL.md" still matches (the "/" before "skills/" is a
# real path separator, not part of the directory name). Mirrors src_ext's
# existing right-anchor above.
plugin_src='(^|[[:space:]/'"'"'"])(skills/[^/]+/SKILL\.md|commands/[^/]+\.md)([[:space:]'"'"'"]|$)'

# branch_for_path: resolve git branch for a given file path.
# Accepts an absolute path or a path relative to $cwd.
# Returns the branch string (empty if not in a git repo).
branch_for_path() {
  local path="$1"
  # Resolve relative paths against the session cwd
  case "$path" in
    /*) : ;;             # already absolute
    *)  path="$cwd/$path" ;;
  esac
  local dir
  dir=$(dirname "$path")
  git -C "$dir" branch --show-current 2>/dev/null || true
}

is_main_branch() {
  local b="$1"
  [ "$b" = "main" ] || [ "$b" = "master" ]
}

# target_is_on_main: given a target file token (possibly absolute or relative),
# returns 0 (true) if the file's repo is on main/master, 1 otherwise.
# Falls back to cwd-branch if the path is not in any git repo.
target_is_on_main() {
  local target="$1"
  local branch
  branch=$(branch_for_path "$target")
  if [ -z "$branch" ]; then
    branch=$(git -C "$cwd" branch --show-current 2>/dev/null || true)
  fi
  is_main_branch "$branch"
}

# ── cp/mv/dd write-to-source-file detection ───────────────────────────────────
# Uses target-repo resolution: resolves the target file's own git repo branch.
# Best-effort: variable filenames, quoted paths with spaces remain uncaught.
write_cmd_target=""
if echo "$cmd" | grep -qiE '^\s*cp\b'; then
  write_cmd_target=$(echo "$cmd" | awk '{print $NF}')
elif echo "$cmd" | grep -qiE '^\s*mv\b'; then
  write_cmd_target=$(echo "$cmd" | awk '{print $NF}')
elif echo "$cmd" | grep -qiE '\bdd\b.*\bof='; then
  write_cmd_target=$(echo "$cmd" | grep -oE 'of=[^ ]+' | head -1 | sed 's/of=//')
fi

if [ -n "$write_cmd_target" ]; then
  # Check if target is a source file or plugin source
  if echo "$write_cmd_target" | grep -qiE "$src_ext|$plugin_src"; then
    if target_is_on_main "$write_cmd_target"; then
      jq -n --arg cmd "$cmd" '{
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          permissionDecision: "deny",
          permissionDecisionReason: ("In-Bash source write (cp/mv/dd) on main branch blocked.\nFull command: " + $cmd + "\nWriting source files via cp/mv/dd on main is blocked. Switch to a feature branch.")
        }
      }'
      exit 0
    fi
  fi
fi

# ── sed/perl/redirect/tee source-edit detection ───────────────────────────────
# For each form, attempt to extract the target file and use target-repo resolution.
# When target file cannot be cleanly extracted, falls back to cwd-branch.
# (sed/perl/tee target parsing is best-effort; variable filenames remain uncaught.)

source_edit_blocked=0
source_edit_target=""

# sed -i ... <sourcefile>: extract last token as the target approximation
if echo "$cmd" | grep -qiE "\\bsed[[:space:]]+-[^'\"]*i[^'\"]*.*($src_ext|$plugin_src)"; then
  source_edit_blocked=1
  source_edit_target=$(echo "$cmd" | awk '{print $NF}')
fi

# perl -i ... <sourcefile>: extract last token as the target approximation
if [ "$source_edit_blocked" -eq 0 ]; then
  if echo "$cmd" | grep -qiE "\\bperl[[:space:]]+-[^'\"]*i[^'\"]*.*($src_ext|$plugin_src)"; then
    source_edit_blocked=1
    source_edit_target=$(echo "$cmd" | awk '{print $NF}')
  fi
fi

# redirect > or >> into a source file
# Ext is anchored to end-of-token so foo.py.bak / output.go.log are not blocked.
if [ "$source_edit_blocked" -eq 0 ]; then
  if echo "$cmd" | grep -qiE ">+\s*['\"]?[^ '\"]*($src_ext|$plugin_src)"; then
    source_edit_blocked=1
    # Extract the redirect target token (the token after > or >>)
    source_edit_target=$(echo "$cmd" | grep -oE '>+[[:space:]]*[^ ]+' | head -1 | sed "s/>*[[:space:]]*//;s/['\"]//g")
  fi
fi

# tee into a source file
if [ "$source_edit_blocked" -eq 0 ]; then
  if echo "$cmd" | grep -qiE "\\btee\b.*($src_ext|$plugin_src)"; then
    source_edit_blocked=1
    source_edit_target=$(echo "$cmd" | awk '{print $NF}')
  fi
fi

if [ "$source_edit_blocked" -eq 1 ]; then
  # Target-repo resolution: check the branch of the target file's own repo.
  # If the target is in a feature-branch repo, allow even if cwd is on main.
  # Falls back to cwd-branch when target path is not resolvable.
  branch_to_check=""
  if [ -n "$source_edit_target" ]; then
    branch_to_check=$(branch_for_path "$source_edit_target")
  fi
  if [ -z "$branch_to_check" ]; then
    branch_to_check=$(git -C "$cwd" branch --show-current 2>/dev/null || true)
  fi

  if is_main_branch "$branch_to_check"; then
    jq -n --arg cmd "$cmd" --arg branch "$branch_to_check" '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: ("In-Bash source edit on " + $branch + " branch blocked.\nFull command: " + $cmd + "\nEditing source files via sed/perl/redirect/tee on main is blocked. Switch to a feature branch or use the Edit tool.")
      }
    }'
    exit 0
  fi
fi

# ── backtick/$() command-substitution inside workflow-script free-text args ──
# push.sh/merge.sh/post_review.sh/post_evals.sh all take a free-text message/path
# argument that becomes part of a commit message, PR title, or file body. A bare
# backtick or $(...) inside that argument executes as live command substitution
# the moment this command line is interpolated into bash — same injection class
# as the $ARGUMENTS render-time bug (PR #97), triggered here via the model's own
# Bash tool_input rather than a command-file render-time !`cmd` line.
#
# Scoped conservatively: the prose exemption (a note that merely mentions
# a script name, not an invocation of it) is deliberately narrow, because
# three prior narrower attempts at this exemption each turned out to admit
# a real bypass under adversarial review (an outer-capture wrapper hiding a
# dirty invocation; quote-blind segment splitting on ; && ||; an
# interpreter-prefix check evaded by direct/./ invocation without bash/sh;
# a first-mention-only scan that let a second, separate genuine invocation
# hide behind an earlier prose statement's exemption). Rather than continue
# refining a clever per-mention heuristic, the exemption now only fires for
# the single narrowest shape it was ever meant to cover:
#
#   the script pattern occurs EXACTLY ONCE on the whole line, that one
#   occurrence is inside a quoted string (not a bare token — a bare,
#   unquoted mention is always treated as a genuine invocation, whether
#   written as `bash scripts/push.sh ...`, `sh scripts/push.sh ...`, or a
#   direct `scripts/push.sh ...` / `./scripts/push.sh ...` call with no
#   interpreter prefix at all), that quoted segment is not the bare
#   "scripts/X.sh" token alone, AND every substitution character on the
#   ENTIRE line is confined to that one quoted segment — if any substitution
#   exists anywhere else on the line, the exemption does not apply.
#
# If the script pattern occurs MORE THAN ONCE on the line, the exemption
# never applies at all — multiple mentions are treated as invocation-
# bearing and denied if a substitution exists anywhere from the first
# mention onward. This collapses several of the previously-fragile shapes
# (a real invocation whose own argument separately mentions a script name;
# a prose statement followed by a separate genuine invocation) into a
# single, simple, conservative rule: more than one mention is never prose.
# subst_re: every character/token sequence that triggers live shell
# expansion the instant this line is interpreted — backtick and $(...)
# command substitution, PLUS <(...) / >(...) process substitution, which
# executes its body eagerly exactly like $(...) but contains neither a
# backtick nor a literal "$(" and was therefore invisible to a detector
# that only checked for those two (confirmed bypass: `bash scripts/push.sh
# "note" <(touch pwned)` ran the touch with zero backticks or $( anywhere
# on the line).
subst_re='`|\$\(|<\(|>\('
# cmd_flat: $cmd with embedded newlines joined into spaces before any
# sed/grep scoping logic runs. Without this, sed's and grep's `.` never
# cross a newline, so a script mention on one physical line and its own
# live substitution on a DIFFERENT physical line (a heredoc body with an
# unquoted delimiter, which still expands $(...) inside it; or ordinary
# backslash line-continuation, which bash joins into one logical command
# before executing it) let "before_script"/"from_script" silently miss the
# substitution — confirmed bypass on both shapes. Flattening first makes
# every check below see the whole logical command as bash will.
cmd_flat=$(echo "$cmd" | tr '\n' ' ')
script_re='scripts/(push|merge|post_review|post_evals)\.sh'
if echo "$cmd_flat" | grep -qE "$script_re"; then
  if echo "$cmd_flat" | grep -qE "$subst_re"; then
    substitution_scoped=0
    total_mentions=$(echo "$cmd_flat" | grep -oE "$script_re" | wc -l | tr -d ' ')
    if [ "$total_mentions" -eq 1 ]; then
      before_script=$(echo "$cmd_flat" | sed -E "s#${script_re}.*##")
      quote_count=$(echo "$before_script" | grep -oE '"' | wc -l | tr -d ' ')
      quote_parity=$(( quote_count % 2 ))
      if [ "$quote_parity" -eq 0 ]; then
        from_script=$(echo "$cmd_flat" | grep -oE "${script_re}.*")
        echo "$from_script" | grep -qE "$subst_re" && substitution_scoped=1
      else
        script_segment=$(echo "$cmd_flat" | grep -oE '"[^"]*"' | grep -E "$script_re" | head -1)
        bare_segment=$(echo "$script_segment" | grep -oE "^\"${script_re}\"\$")
        if [ -n "$bare_segment" ]; then
          from_script=$(echo "$cmd_flat" | grep -oE "${script_re}.*")
          echo "$from_script" | grep -qE "$subst_re" && substitution_scoped=1
        elif echo "$script_segment" | grep -qE "$subst_re"; then
          # substitution is inside the prose segment — allow ONLY if no
          # OTHER substitution exists elsewhere on the line. Compared by
          # COUNTING substitution characters in the whole command vs. in
          # the one segment, rather than removing the segment via sed text
          # substitution — a sed pattern needs a delimiter guaranteed
          # absent from the segment's own (user-controlled) text, which
          # cannot be guaranteed for any fixed delimiter (e.g. a literal #
          # in the segment broke a `#`-delimited sed command, causing a
          # silent parse error whose stderr text was captured as "rest" and
          # read as substitution-free, granting an undeserved exemption
          # even though a separate substitution existed elsewhere on the
          # line). Counting has no delimiter to collide with.
          whole_subst=$(( $(echo "$cmd_flat" | grep -oE '\$\(|<\(|>\(' | wc -l | tr -d ' ') + $(echo "$cmd_flat" | grep -oE '`' | wc -l | tr -d ' ') ))
          segment_subst=$(( $(echo "$script_segment" | grep -oE '\$\(|<\(|>\(' | wc -l | tr -d ' ') + $(echo "$script_segment" | grep -oE '`' | wc -l | tr -d ' ') ))
          [ "$whole_subst" -ne "$segment_subst" ] && substitution_scoped=1
        else
          substitution_scoped=1
        fi
      fi
    else
      from_script=$(echo "$cmd_flat" | grep -oE "${script_re}.*")
      echo "$from_script" | grep -qE "$subst_re" && substitution_scoped=1
    fi
    if [ "$substitution_scoped" -eq 1 ]; then
      jq -n --arg cmd "$cmd" '{
        hookSpecificOutput: {
          hookEventName: "PreToolUse",
          permissionDecision: "deny",
          permissionDecisionReason: ("Command-substitution character (backtick, $(...), or process substitution <(...)/>(...)) detected inside a push.sh/merge.sh/post_review.sh/post_evals.sh argument.\nFull command: " + $cmd + "\nThese scripts take a free-text message that becomes a commit/PR title or comment body — a backtick, $(...), or <(...)/>(...) in it executes as live shell substitution when this line runs, not literal text. None of these scripts read a body from a file, so there is no -F body=@file escape hatch here — rewrite the argument in plain prose with no backticks, $(), or <()/>() (e.g. \"git rev-parse show-toplevel\" instead of wrapping it in backticks).")
        }
      }'
      exit 0
    fi
  fi
fi

exit 0
