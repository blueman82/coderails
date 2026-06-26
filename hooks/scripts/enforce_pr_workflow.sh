#!/bin/bash
# PreToolUse Bash hook: enforce the coderails workflow chain for gh pr operations.
# Blocks `gh pr create` unless /coderails:push ran this session.
# Blocks `gh pr merge`  unless /pr-review-toolkit:review-pr ran this session.
# Blocks `git merge` on main/master unless /pr-review-toolkit:review-pr ran this session.
# Blocks `git push` to main/master unless /pr-review-toolkit:review-pr ran this session —
#   fires when on main/master OR when the command targets main/master via an explicit
#   destination refspec (HEAD:main, feature:master, :refs/heads/main) from any branch.
#   Closes the common direct-push-to-main bypass. Feature-branch pushes are never gated;
#   bare positional targets (`git push origin main` from off-main) are not parsed.
# Opt-in: if no workflow.config.yaml exists (NO_CONFIG), the hook is a no-op.
# Escape: add a `gh pr create`, `gh pr merge`, `git merge`, or `git push` Bash permission to settings.json.

input=$(cat)
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')

gate_has_command() {
  [ -z "$cmd" ] && exit 0
}

gate_safe_passthrough() {
  case "$cmd" in
    *--help*|*--dry-run*) exit 0 ;;
  esac
  # git merge conflict-resolution ops are never a "bring in changes" merge — always pass.
  if printf '%s' "$cmd" | grep -qE '\bgit +merge +(--abort|--continue|--quit|--skip)\b'; then
    exit 0
  fi
}

gate_in_scope() {
  # Only act on `gh pr create`, `gh pr merge`, `git merge`, or `git push` — and
  # only when one is the command actually being RUN, not a substring mentioned
  # inside an argument. Split the command on shell separators (; | & && ||) and
  # test whether any segment, after leading whitespace, BEGINS with a gated
  # command. This fixes the false-positive where e.g. `printf 'gh pr create' > f`
  # (writing text) was blocked, while still catching chained forms like
  # `cd x && gh pr create`. The `([[:space:]]|$)` tail on `git merge`/`git push`
  # excludes read-only plumbing (`git merge-base`/`-file`/`-tree`).
  # Known limit: a gated command wrapped in a subshell `(gh pr create)` or behind
  # an env/command prefix (`VAR=x gh ...`) is not parsed — the same "we don't
  # parse every shell form" stance as the refspec note in gate_targets_main.
  subcommand=""
  local seg
  while IFS= read -r seg; do
    seg="${seg#"${seg%%[![:space:]]*}"}"   # strip leading whitespace
    if   [[ "$seg" =~ ^gh[[:space:]]+pr[[:space:]]+create([[:space:]]|$) ]]; then subcommand="create";    break
    elif [[ "$seg" =~ ^gh[[:space:]]+pr[[:space:]]+merge([[:space:]]|$)  ]]; then subcommand="merge";     break
    elif [[ "$seg" =~ ^git[[:space:]]+merge([[:space:]]|$) ]];             then subcommand="git_merge"; break
    elif [[ "$seg" =~ ^git[[:space:]]+push([[:space:]]|$) ]];              then subcommand="git_push";  break
    fi
  done <<EOF
$(printf '%s' "$cmd" | awk '{gsub(/&&|\|\||[;|&]/, "\n"); print}')
EOF
  # No gated command was actually invoked → stand aside.
  [ -z "$subcommand" ] && exit 0
  # $subcommand is also read by gate_targets_main and enforce_required_step.
}

gate_config_present() {
  # Opt-in — if no workflow.config.yaml exists, stand aside.
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
}

gate_targets_main() {
  # git_merge / git_push only gate when they actually touch main/master.
  #  - git_merge integrates into the CHECKED-OUT branch → the current branch decides.
  #  - git_push is decided by its DESTINATION → gate when on main/master, OR when the
  #    command names an explicit main/master destination refspec (e.g. `HEAD:main`,
  #    `feature:master`, `:refs/heads/main`) from any branch. Bare positional targets
  #    (`git push origin main` from off-main) are NOT parsed — a documented limitation;
  #    the colon-refspec form is the realistic direct-to-main bypass, and that is closed.
  if [ "$subcommand" = "git_merge" ] || [ "$subcommand" = "git_push" ]; then
    current_branch=$(git -C "$cwd" branch --show-current 2>/dev/null)
    gate_it=0
    case "$current_branch" in main|master) gate_it=1 ;; esac
    # The destination ref may be terminated by whitespace, EOL, or a shell separator
    # (`git push origin HEAD:main;echo`), so the anchor accepts `;& |)` too — otherwise
    # a metachar abutting the ref trivially evades the gate.
    if [ "$subcommand" = "git_push" ] && \
       printf '%s' "$cmd" | grep -qE ':(refs/heads/)?(main|master)([[:space:];&|)]|$)'; then
      gate_it=1
    fi
    [ "$gate_it" -eq 0 ] && exit 0   # neither on, nor targeting, main/master — safe
  fi
}

gate_have_transcript() {
  # No transcript → can't enforce, stand aside.
  transcript=$(printf '%s' "$input" | jq -r '.transcript_path // empty')
  if [ -z "$transcript" ] || [ ! -f "$transcript" ]; then
    exit 0
  fi
}

enforce_required_step() {
  # Scan transcript for the required preceding step.
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
      gate_hint="Run /pr-review-toolkit:review-pr first. Or use /coderails:merge for the full PR workflow. Or add a 'git merge' Bash permission to settings.json to bypass."
    elif [ "$subcommand" = "git_push" ]; then
      gate_hint="Don't push directly to main/master — push a feature branch and open a PR (/coderails:push). Or run /pr-review-toolkit:review-pr first. Or add a 'git push' Bash permission to settings.json to bypass."
    else
      gate_hint="Run /pr-review-toolkit:review-pr first (or add a 'gh pr merge' Bash permission to settings.json to bypass)."
    fi
  fi

  [ -z "$step_found" ] && step_found=0

  if [ "$step_found" -eq 0 ]; then
    if [ "$subcommand" = "git_merge" ]; then
      reason="Blocked: \`git merge\` on main requires $required_step to have run this session. $gate_hint"
    elif [ "$subcommand" = "git_push" ]; then
      reason="Blocked: \`git push\` on main/master requires $required_step to have run this session. $gate_hint"
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
}

gate_has_command
gate_safe_passthrough
gate_in_scope
gate_config_present
gate_targets_main
gate_have_transcript
enforce_required_step

exit 0
