#!/bin/bash
# PreToolUse Bash hook: permanently block destructive commands.
# Detects rm -rf, git push --force, git reset --hard, SQL DROP/TRUNCATE, dd, mkfs, chmod -R 777,
# git clean (force), find -delete/--delete, truncate -s/--size, shred.
# Also blocks in-Bash source-file edits (sed -i, perl -i, redirect >, >>, tee, cp, mv, dd of=)
# on main/master branches — closing the hole that no_edit_on_main (Write/Edit only) misses.
# Returns permissionDecision="deny" — there is no approval path; use a safer alternative or add a settings.json permission rule.

IFS= read -r -d '' -t 5 input || true
cmd=$(echo "$input" | jq -r '.tool_input.command // empty')

if [ -z "$cmd" ]; then
  exit 0
fi

deny() {
  local pat="$1"
  jq -n --arg pat "$pat" --arg cmd "$cmd" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: ("Destructive pattern detected: " + $pat + "\nFull command: " + $cmd + "\nThis command is permanently blocked. To allow it, add a Bash permission rule to settings.json or use a non-destructive alternative.")
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
if echo "$cmd" | grep -qiE '\bgit +clean\b'; then
  # Extract everything after "git clean" as the args portion
  args=$(echo "$cmd" | sed -E 's/.*\bgit +clean\b//')
  # Allow bare "git clean" (no args)
  if [ -n "$(echo "$args" | tr -d ' \t')" ]; then
    # Allow dry-run forms: -n / --dry-run
    if echo "$args" | grep -qE '(^| )--dry-run( |$)|(^| )-[a-zA-Z]*n[a-zA-Z]*( |$)'; then
      : # dry-run — allow
    # Allow interactive: -i / --interactive
    elif echo "$args" | grep -qE '(^| )-[a-zA-Z]*i[a-zA-Z]*( |$)|(^| )--interactive( |$)'; then
      : # interactive — allow
    # Deny force: --force or -f in any combined/separated form
    elif echo "$args" | grep -qE '(^| )--force( |$)|(^| )-[a-zA-Z]*f[a-zA-Z]*( |$)'; then
      deny "git clean (force)"
    fi
  fi
fi

# find ... -delete or find ... --delete
# The .* must not cross a shell separator (;, &&, ||, |).
# Only match -delete/--delete in the same shell token group as "find".
if echo "$cmd" | grep -qiE '\bfind\b[^;|&]*( -delete| --delete)'; then
  deny "find -delete"
fi

# truncate with size flag — truncates file content
# Also catches --size / --size=N long forms.
if echo "$cmd" | grep -qiE '\btruncate +(-s|--size[= ])'; then
  deny "truncate -s/--size"
fi

# shred (secure file deletion / overwrite)
if echo "$cmd" | grep -qiE '\bshred\b'; then
  deny "shred"
fi

# ── Original permanent blocklist ─────────────────────────────────────────────
pattern='\brm +(-[rRfF]+|--recursive|--force)|\bgit +push +.*(--force|-f\b|--force-with-lease)|\bgit +reset +--hard|\bDROP +(TABLE|DATABASE|SCHEMA)\b|\bTRUNCATE +TABLE\b|\bdd +if=|\bmkfs\.|\bchmod +-R +777|\bgit +commit +.*--no-verify'

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
# - Session cwd is read from the hook payload (.cwd), falling back to $PWD.
cwd=$(echo "$input" | jq -r '.cwd // empty')
[ -z "$cwd" ] && cwd="$PWD"  # Falls back to $PWD when .cwd is absent.

# Source-file extensions pattern (anchored to end-of-token to avoid false matches
# like foo.py.bak or output.go.log). Matches only tokens ENDING in a source ext.
src_ext='\.(py|ts|tsx|js|jsx|go)([ '"'"'"]|$)'
# Plugin source pattern (skills/*/SKILL.md or commands/*.md)
plugin_src='(skills/[^/]+/SKILL\.md|commands/[^/]+\.md)([ '"'"'"]|$)'

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
if echo "$cmd" | grep -qiE "\\bsed +-[^'\"]*i[^'\"]*.*($src_ext|$plugin_src)"; then
  source_edit_blocked=1
  source_edit_target=$(echo "$cmd" | awk '{print $NF}')
fi

# perl -i ... <sourcefile>: extract last token as the target approximation
if [ "$source_edit_blocked" -eq 0 ]; then
  if echo "$cmd" | grep -qiE "\\bperl +-[^'\"]*i[^'\"]*.*($src_ext|$plugin_src)"; then
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
          permissionDecisionReason: ("Command-substitution character (backtick or $(...)) detected inside a push.sh/merge.sh/post_review.sh/post_evals.sh argument.\nFull command: " + $cmd + "\nThese scripts take a free-text message that becomes a commit/PR title or comment body — a backtick or $(...) in it executes as live shell substitution when this line runs, not literal text. None of these scripts read a body from a file, so there is no -F body=@file escape hatch here — rewrite the argument in plain prose with no backticks or $() (e.g. \"git rev-parse show-toplevel\" instead of wrapping it in backticks).")
        }
      }'
      exit 0
    fi
  fi
fi

exit 0
