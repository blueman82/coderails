#!/bin/bash
# PreToolUse Bash hook: enforce the coderails workflow chain for gh pr operations.
# Blocks `gh pr create` unless /coderails:push ran this session.
# Blocks `gh pr merge`  unless /pr-review-toolkit:review-pr ran this session.
# Blocks `git merge` on main/master unless /pr-review-toolkit:review-pr ran this session.
# Opt-in: if no workflow.config.yaml exists (NO_CONFIG), the hook is a no-op.
# Escape: add a `gh pr create`, `gh pr merge`, or `git merge` Bash permission to settings.json.

input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')

# Gate 1: nothing to inspect.
[ -z "$cmd" ] && exit 0

# Gate 2: --help / --dry-run / conflict-resolution flags are always safe passthroughs.
case "$cmd" in
  *--help*|*--dry-run*) exit 0 ;;
esac
# git merge conflict-resolution ops are never a "bring in changes" merge — always pass.
if printf '%s' "$cmd" | grep -qE '\bgit +merge +(--abort|--continue|--quit|--skip)\b'; then
  exit 0
fi

# Gate 3: only act on `gh pr create`, `gh pr merge`, or `git merge`.
if ! printf '%s' "$cmd" | grep -qE '\bgh +pr +(create|merge)\b|\bgit +merge\b'; then
  exit 0
fi

# Determine which subcommand we are guarding.
if printf '%s' "$cmd" | grep -qE '\bgh +pr +create\b'; then
  subcommand="create"
elif printf '%s' "$cmd" | grep -qE '\bgh +pr +merge\b'; then
  subcommand="merge"
else
  subcommand="git_merge"
fi

# Gate 4: opt-in — if no workflow.config.yaml exists, stand aside.
cwd=$(printf '%s' "$input" | jq -r '.cwd // empty')
[ -z "$cwd" ] && cwd="$PWD"
git_root=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null)
if [ -z "$git_root" ]; then
  exit 0
fi
config_file=""
candidate1="$git_root/projects/$(basename "$cwd")/.claude/workflow.config.yaml"
candidate2="$git_root/.claude/workflow.config.yaml"
[ -f "$candidate1" ] && config_file="$candidate1"
[ -z "$config_file" ] && [ -f "$candidate2" ] && config_file="$candidate2"
if [ -z "$config_file" ]; then
  exit 0
fi

# Gate 4b: for `git merge`, only gate when on main or master; feature branches are safe.
if [ "$subcommand" = "git_merge" ]; then
  current_branch=$(git -C "$cwd" branch --show-current 2>/dev/null)
  case "$current_branch" in
    main|master) ;;  # proceed to evidence check
    *) exit 0 ;;    # not on main/master — local merges are safe
  esac
fi

# Gate 5: no transcript → can't enforce, stand aside.
transcript=$(printf '%s' "$input" | jq -r '.transcript_path // empty')
if [ -z "$transcript" ] || [ ! -f "$transcript" ]; then
  exit 0
fi

# Gate 6: scan transcript for the required preceding step.
# Match on: Skill tool_use whose skill contains the target name, OR (for push)
# a Bash tool_use whose command contains push.sh. Uses structured jq — never text-grep.
step_found=0

if [ "$subcommand" = "create" ]; then
  # Required step: /coderails:push — matches Skill name "(coderails:)?push" or push.sh Bash
  step_found=$(jq -s -r '
    [ .[]?
      | select(.type == "assistant")
      | .message.content[]?
      | select(.type == "tool_use")
      | select(
          (.name == "Skill" and ((.input.skill // "") | test("(^|:)push$")))
          or
          (.name == "Bash" and ((.input.command // "") | test("push\\.sh")))
        )
    ] | length
  ' "$transcript" 2>/dev/null)
  required_step="/coderails:push"
  gate_hint="Run /coderails:push first (or add a 'gh pr create' Bash permission to settings.json to bypass)."
else
  # Required step: /pr-review-toolkit:review-pr (covers both `gh pr merge` and `git merge` on main)
  step_found=$(jq -s -r '
    [ .[]?
      | select(.type == "assistant")
      | .message.content[]?
      | select(.type == "tool_use" and .name == "Skill")
      | select((.input.skill // "") | test("review-pr$"))
    ] | length
  ' "$transcript" 2>/dev/null)
  required_step="/pr-review-toolkit:review-pr"
  if [ "$subcommand" = "git_merge" ]; then
    gate_hint="Use /coderails:merge for the full PR merge workflow, or add a 'git merge' Bash permission to settings.json to bypass."
  else
    gate_hint="Run /pr-review-toolkit:review-pr first (or add a 'gh pr merge' Bash permission to settings.json to bypass)."
  fi
fi

[ -z "$step_found" ] && step_found=0

if [ "$step_found" -eq 0 ]; then
  if [ "$subcommand" = "git_merge" ]; then
    reason="Blocked: \`git merge\` on main requires $required_step to have run this session. $gate_hint"
  else
    reason="Blocked: gh pr $subcommand requires $required_step to have run this session. $gate_hint"
  fi
  jq -n --arg r "$reason" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $r
    }
  }'
  log="${CLAUDE_DISCIPLINE_LOG:-$HOME/.claude/discipline.log}"
  log_cmd="${subcommand//_/-}"
  printf 'hook=enforce_pr_workflow decision=deny subcommand=%s required=%s\n' \
    "$log_cmd" "$required_step" >> "$log" 2>/dev/null
fi

exit 0
