#!/bin/bash
# PreToolUse Bash hook: enforce the coderails workflow chain for gh pr operations.
# Blocks `gh pr create` unless /coderails:push ran this session.
# Blocks `gh pr merge`  unless /pr-review-toolkit:review-pr ran this session
#   referencing the same PR number (when a number is given).
# Blocks `git merge` on main/master unless /pr-review-toolkit:review-pr ran since
#   the last git merge (consume-on-use).
# Blocks `git push` to main/master unless /pr-review-toolkit:review-pr ran this
#   session — fires when on main/master OR when the command targets main/master
#   via a destination refspec (HEAD:main, feature:master, :refs/heads/main) OR
#   via a bare positional target (git push origin main) from any branch.
# Subagent support: when .agent_transcript_path is present and readable, it is
#   scanned in addition to .transcript_path for required evidence.
# Opt-in: if no workflow.config.yaml exists (NO_CONFIG), the hook is a no-op.
# Escape: add a `gh pr create`, `gh pr merge`, `git merge`, or `git push` Bash
#   permission to settings.json.

# Shared workflow.config.yaml resolver (walk-up from cwd to git root). Sourced
# relative to this script: hooks/scripts/ -> ../../scripts/lib/config.sh.
. "$(dirname "$0")/../../scripts/lib/config.sh"

IFS= read -r -d '' -t 5 input || true
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')

gate_has_command() {
  [ -z "$cmd" ] && exit 0
}

gate_safe_passthrough() {
  # CHANGE D: merge --dry-run / --help into one alternation with word-boundary match
  # so --dry-run-data or --helpfulness don't accidentally pass through. The pattern
  # requires the flag to be preceded by a non-word char (or start of string) and
  # followed by a non-word char or end.
  if printf '%s' "$cmd" | grep -qE '(^|[^-[:alnum:]])(--dry-run|--help)([^-[:alnum:]]|$)'; then
    exit 0
  fi
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
  # Uses the shared resolver (scripts/lib/config.sh) so the hook's opt-in
  # detection agrees with the commands' resolution — otherwise the merge gate
  # would silently go inactive in a non-projects/ layout.
  cwd=$(printf '%s' "$input" | jq -r '.cwd // empty')
  [ -z "$cwd" ] && cwd="$PWD"
  config_file=$(coderails::config_path "$cwd")
  if [ -z "$config_file" ]; then
    exit 0
  fi
}

gate_targets_main() {
  # git_merge / git_push only gate when they actually touch main/master.
  #  - git_merge integrates into the CHECKED-OUT branch → the current branch decides.
  #  - git_push is decided by its DESTINATION → gate when on main/master, OR when the
  #    command names an explicit main/master destination refspec (e.g. `HEAD:main`,
  #    `feature:master`, `:refs/heads/main`) from any branch. Also gate positional
  #    bare-branch targets from any branch — CHANGE C1 closes this gap.
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
    # CHANGE C1 (expanded): gate `git push` when main/master appears as a standalone
    # whitespace-delimited token ANYWHERE after the `push` keyword. This catches all of:
    #   git push -u origin main         (upstream flag before remote)
    #   git push --set-upstream origin main
    #   git push -f origin main         (force flag)
    #   git push --force origin main
    #   git push origin +main           (force-refspec, no colon)
    #   git push origin refs/heads/main (bare ref)
    #   git push origin tag v1 main     (extra positionals)
    # The pattern `(^|[[:space:]])(main|master)([[:space:];&|)]|$)` matches the branch
    # name only as a complete token: preceded by start or whitespace, followed by end
    # or a shell separator. This prevents over-match on `main-fix`, `maintenance`, etc.
    # Trade-off: a remote *named* `main` (e.g. `git push main feature`) will also be
    # gated. That is fail-safe (over-block, not bypass); the settings.json Bash
    # permission escape covers any legitimate use of such a remote name.
    if [ "$subcommand" = "git_push" ] && [ "$gate_it" -eq 0 ]; then
      # Extract the portion of the command after the `push` keyword for token scan.
      push_args=$(printf '%s' "$cmd" | grep -oE '\bgit[[:space:]]+push[[:space:]](.*)' | sed 's/^git[[:space:]]*push[[:space:]]*//')
      # Match +main, refs/heads/main, or bare main/master as a standalone token.
      if printf '%s' "$push_args" | grep -qE '(^|[[:space:]])(\+)?(refs/heads/)?(main|master)([[:space:];&|)]|$)'; then
        gate_it=1
      fi
    fi
    [ "$gate_it" -eq 0 ] && exit 0   # neither on, nor targeting, main/master — safe
  fi
}

gate_have_transcript() {
  # CHANGE A: in a subagent, .transcript_path is the PARENT session transcript and
  # .agent_transcript_path is the subagent's own. Scan whichever transcripts are
  # present and readable — at least one must exist, or we can't enforce.
  transcript=$(printf '%s' "$input" | jq -r '.transcript_path // empty')
  agent_transcript=$(printf '%s' "$input" | jq -r '.agent_transcript_path // empty')

  # Normalise: treat missing-or-unreadable paths as empty.
  [ -n "$transcript" ] && [ ! -f "$transcript" ] && transcript=""
  [ -n "$agent_transcript" ] && [ ! -f "$agent_transcript" ] && agent_transcript=""

  if [ -z "$transcript" ] && [ -z "$agent_transcript" ]; then
    exit 0   # no transcript available — can't enforce, stand aside
  fi
  # transcript / agent_transcript are now read by enforce_required_step.
}

# scan_for_step runs a jq expression against all available transcript files and
# returns the total count of matching entries across them.
scan_for_step() {  # jq_filter -> count written to stdout
  local jq_filter="$1"
  local count=0 n
  for tpath in "$transcript" "$agent_transcript"; do
    [ -z "$tpath" ] && continue
    n=$(jq -s -r "$jq_filter" "$tpath" 2>/dev/null)
    [ -z "$n" ] && n=0
    count=$((count + n))
  done
  printf '%d' "$count"
}

# scan_review_pr_since_last_git_merge counts review-pr Skill invocations that appear
# AFTER the last `git merge` Bash tool_use in all available transcripts. Entries are
# ordered by their `.timestamp` field (ISO-8601) so that cross-transcript comparisons
# are chronological, not dependent on parent-then-agent concatenation order. Entries
# with no `.timestamp` are treated as earlier than all timestamped entries (sorted to
# front), which is fail-safe: a timestamp-less review-pr cannot be falsely counted as
# post-merge.
scan_review_pr_since_last_git_merge() {
  # Build combined JSONL from all transcripts, then query in jq.
  local all_lines=""
  for tpath in "$transcript" "$agent_transcript"; do
    [ -z "$tpath" ] && continue
    all_lines="${all_lines}$(cat "$tpath" 2>/dev/null)"$'\n'
  done
  printf '%s' "$all_lines" | jq -s -r '
    # Sort all entries by .timestamp ascending. Entries without a .timestamp
    # sort to the front (treated as earliest) — fail-safe: stale untimed reviews
    # cannot be miscounted as post-merge.
    sort_by(.timestamp // "") as $sorted
    # Find the INDEX of the last git-merge Bash tool_use in the sorted array.
    | ([ $sorted | to_entries[]
         | select(.value.type == "assistant")
         | .key as $i
         | .value.message.content[]?
         | select(.type == "tool_use" and .name == "Bash")
         | select((.input.command // "") | test("\\bgit\\s+merge\\b"))
         | $i
       ] | max // -1) as $last_merge_idx
    # Count review-pr Skill tool_uses that appear AFTER that index in sorted order.
    | [ $sorted | to_entries[]
        | select(.key > $last_merge_idx)
        | select(.value.type == "assistant")
        | .value.message.content[]?
        | select(.type == "tool_use" and .name == "Skill")
        | select((.input.skill // "") | test("review-pr$"))
      ] | length
  ' 2>/dev/null || printf '0'
}

enforce_required_step() {
  # Scan transcripts for the required preceding step.
  # Match on: Skill tool_use whose skill contains the target name, OR (for push)
  # a Bash tool_use whose command contains push.sh. Uses structured jq — never text-grep.
  step_found=0

  # Hoisted: jq filter for "any review-pr Skill in transcript" — reused in merge (bare)
  # and git_push branches to avoid duplication.
  readonly ANY_REVIEW_PR_FILTER='
    [ .[]?
      | select(.type == "assistant")
      | .message.content[]?
      | select(.type == "tool_use" and .name == "Skill")
      | select((.input.skill // "") | test("review-pr$"))
    ] | length
  '

  if [ "$subcommand" = "create" ]; then
    # Required step: /coderails:push — matches Skill name "(coderails:)?push" or push.sh Bash
    step_found=$(scan_for_step '
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
    ')
    required_step="/coderails:push"
    gate_hint="Run /coderails:push first (or add a 'gh pr create' Bash permission to settings.json to bypass)."

  elif [ "$subcommand" = "merge" ]; then
    # Required step: /pr-review-toolkit:review-pr
    # CHANGE B: if a PR number is given in the command, require review-pr to have
    # been invoked with that same number in its args. If no PR number is given
    # (bare `gh pr merge`), any review-pr invocation suffices (legacy behaviour).
    required_step="/pr-review-toolkit:review-pr"
    gate_hint="Run /pr-review-toolkit:review-pr first (or add a 'gh pr merge' Bash permission to settings.json to bypass)."

    # CHANGE B1: extract the first bare integer argument after "gh pr merge", skipping
    # any leading --flag or --flag=val tokens. This handles forms like:
    #   gh pr merge --squash 42     (flag before number)
    #   gh pr merge --auto 42
    #   gh pr merge 42 --squash     (number first — also handled by stripping flags)
    # Strip the "gh pr merge" prefix, then scan tokens left-to-right for a bare integer.
    merge_suffix=$(printf '%s' "$cmd" | grep -oE 'gh[[:space:]]+pr[[:space:]]+merge(.*)')
    pr_num=""
    if [ -n "$merge_suffix" ]; then
      # Remove the "gh pr merge" prefix; iterate remaining tokens to find first integer.
      merge_args=$(printf '%s' "$merge_suffix" | sed 's/gh[[:space:]]*pr[[:space:]]*merge[[:space:]]*//')
      for token in $merge_args; do
        case "$token" in
          --*=*) ;;           # --flag=val: skip
          --*|-*) ;;          # --flag or -f: skip
          [0-9]*) pr_num="$token"; break ;;   # bare integer: this is the PR number
        esac
      done
    fi

    if [ -n "$pr_num" ]; then
      # CHANGE B2: per-PR check — review-pr args must START WITH (or be exactly) the
      # PR number as a leading token. Incidental occurrences of the number embedded in
      # prose (e.g. args "fixed 12 bugs") must NOT satisfy the gate.
      # Pattern: args begins with the PR number optionally followed by non-digit or end.
      step_found=$(scan_for_step "
        [ .[]?
          | select(.type == \"assistant\")
          | .message.content[]?
          | select(.type == \"tool_use\" and .name == \"Skill\")
          | select((.input.skill // \"\") | test(\"review-pr\$\"))
          | select((.input.args // \"\") | tostring | test(\"^${pr_num}([^0-9]|\$)\"))
        ] | length
      ")
      gate_hint="Run /pr-review-toolkit:review-pr ${pr_num} first (or add a 'gh pr merge' Bash permission to settings.json to bypass)."
    else
      # No PR number — any review-pr suffices.
      step_found=$(scan_for_step "$ANY_REVIEW_PR_FILTER")
    fi

  elif [ "$subcommand" = "git_merge" ]; then
    # CHANGE B consume-on-use: review-pr must have run SINCE the last git merge.
    required_step="/pr-review-toolkit:review-pr"
    gate_hint="Run /pr-review-toolkit:review-pr first. Or use /coderails:merge for the full PR workflow. Or add a 'git merge' Bash permission to settings.json to bypass."
    step_found=$(scan_review_pr_since_last_git_merge)

  else
    # git_push — any review-pr this session suffices.
    required_step="/pr-review-toolkit:review-pr"
    gate_hint="Don't push directly to main/master — push a feature branch and open a PR (/coderails:push). Or run /pr-review-toolkit:review-pr first. Or add a 'git push' Bash permission to settings.json to bypass."
    step_found=$(scan_for_step "$ANY_REVIEW_PR_FILTER")
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
