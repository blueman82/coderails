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
# Scoped (not whole-line): a substitution character anywhere on the line used
# to deny even when it wasn't part of an argument passed to the script. Two
# checks narrow this to genuine in-argument substitution:
#   1. an UNCLOSED substitution reaching the first script-name mention means
#      the whole invocation is being captured (e.g. out=$(bash scripts/push.sh
#      "clean msg")) — the script's own stdout is substituted, not its argument.
#      "Unclosed" is measured by parenthesis-depth for $( (more opens than
#      closes before the script name) and by parity for backticks (an odd
#      count means the mention falls inside an open backtick pair). A
#      substitution that is already CLOSED before the script name (e.g. an
#      unrelated `echo $(pwd); bash scripts/push.sh "msg with $(whoami)"`) does
#      not count — that line's real argument substitution must still be caught
#      by check 2, not suppressed here.
#   2. the quoted segment that contains the script-name mention, when that
#      segment is not the bare "scripts/X.sh" token, is prose that happens to
#      mention the script name and a substitution char together (e.g. a note
#      documenting the script) — not an actual invocation of it. Otherwise a
#      substitution char anywhere on the line (having passed check 1) is a
#      genuine argument to the script and still denies.
script_re='scripts/(push|merge|post_review|post_evals)\.sh'
if echo "$cmd" | grep -qE "$script_re"; then
  if echo "$cmd" | grep -qE '`|\$\('; then
    substitution_scoped=1
    before_script=$(echo "$cmd" | sed -E "s#${script_re}.*##")
    dollar_opens=$(echo "$before_script" | grep -oE '\$\(' | wc -l | tr -d ' ')
    close_parens=$(echo "$before_script" | grep -oE '\)' | wc -l | tr -d ' ')
    backtick_count=$(echo "$before_script" | grep -oE '`' | wc -l | tr -d ' ')
    backtick_open=$(( backtick_count % 2 ))
    if [ "$dollar_opens" -gt "$close_parens" ] || [ "$backtick_open" -eq 1 ]; then
      substitution_scoped=0
    fi
    if [ "$substitution_scoped" -eq 1 ]; then
      script_segment=$(echo "$cmd" | grep -oE '"[^"]*"' | grep -E "$script_re" | head -1)
      if [ -n "$script_segment" ]; then
        bare_segment=$(echo "$script_segment" | grep -oE "^\"${script_re}\"\$")
        if [ -z "$bare_segment" ] && echo "$script_segment" | grep -qE '`|\$\('; then
          substitution_scoped=0
        fi
      fi
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
