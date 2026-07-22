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

# git-common.sh (BASH_SOURCE-relatively sources eval-artifact.sh +
# review-artifact.sh) — needed for gate_eval_artifact_for_merge's use of
# pr::head_sha / pr::has_coderails_eval_for_head. Its colour vars are guarded
# by _GIT_COMMON_COLORS_LOADED, so re-sourcing here is safe even though
# scripts/merge.sh also sources it in-process elsewhere.
. "$(dirname "$0")/../../scripts/lib/git-common.sh"

# tier-floor.sh — the diff-derived tier floor. Needed here, not only in
# scripts/merge.sh: a raw `gh pr merge <N>` never runs merge.sh, so a floor
# that lived only there would be bypassed by the very command this hook
# exists to gate.
. "$(dirname "$0")/../../scripts/lib/tier-floor.sh"

IFS= read -r -d '' -t 5 input || true
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')

gate_has_command() {
  [ -z "$cmd" ] && exit 0
}

gate_safe_passthrough() {
  # --dry-run and --help are matched in one alternation with word-boundary checks
  # so --dry-run-data or --helpfulness don't accidentally pass through. The pattern
  # requires the flag to be preceded by a non-word char (or start of string) and
  # followed by a non-word char or end.
  # EXCLUDED from this passthrough: merge.sh invocations (tested with the same
  # anchor gate_in_scope uses below, so this isn't a second regex dialect).
  # The exemption exists because `gh pr merge --dry-run`/`--help` are genuinely
  # inert for gh (gh rejects the unknown --dry-run flag outright with exit 1,
  # and --help just prints usage — neither ever merges). scripts/merge.sh has
  # no such flags: its arg parser (merge::main) reads only $1 as the PR
  # number/branch and silently ignores any trailing token, including
  # --dry-run — so `scripts/merge.sh 140 --dry-run` would otherwise pass
  # through this gate and then perform a REAL merge of PR 140.
  if printf '%s' "$cmd" | grep -qE '(^|[^-[:alnum:]])(--dry-run|--help)([^-[:alnum:]]|$)' && \
     ! printf '%s' "$cmd" | grep -qE "(^|[;&|[:space:]])((bash|sh)[[:space:]]+)?[\"']?([^[:space:]\"']*/)?merge\\.sh[\"']?([[:space:]]|\$)"; then
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
  # `git -C <dir> merge`/`git -C <dir> push` are also recognized as gated forms
  # (same tail requirement) — previously a segment starting with `git -C` never
  # matched "begins with git merge/push" at all, so the whole hook stood aside
  # and e.g. `git -C /path/to/main-checkout push origin main` bypassed the gate
  # unconditionally. push_target_dir carries the `-C` directory (if any) so
  # gate_targets_main can resolve the branch from the actual target, not $cwd.
  # Known limit: a gated command wrapped in a subshell `(gh pr create)` or behind
  # an env/command prefix (`VAR=x gh ...`) is not parsed — the same "we don't
  # parse every shell form" stance as the refspec note in gate_targets_main.
  subcommand=""
  push_target_dir=""
  matched_seg=""
  local seg
  while IFS= read -r seg; do
    seg="${seg#"${seg%%[![:space:]]*}"}"   # strip leading whitespace
    if   [[ "$seg" =~ ^gh[[:space:]]+pr[[:space:]]+create([[:space:]]|$) ]]; then subcommand="create";    matched_seg="$seg"; break
    elif [[ "$seg" =~ ^gh[[:space:]]+pr[[:space:]]+merge([[:space:]]|$)  ]]; then subcommand="merge";     matched_seg="$seg"; break
    elif [[ "$seg" =~ ^git[[:space:]]+merge([[:space:]]|$) ]];             then subcommand="git_merge"; break
    elif [[ "$seg" =~ ^git[[:space:]]+push([[:space:]]|$) ]];              then subcommand="git_push";  break
    elif [[ "$seg" =~ ^((bash|sh)[[:space:]]+)?[\"\']?([^[:space:]\"\']*/)?merge\.sh[\"\']?([[:space:]]|$) ]]; then
      # scripts/merge.sh is the repo's sanctioned merge wrapper (calls `gh pr
      # merge` internally). Recognizing its invocation here closes the gap
      # where `scripts/merge.sh <N>` / `./scripts/merge.sh <N>` / `bash
      # <path>/merge.sh <N>` sailed past this gate entirely — only literal
      # `gh pr merge` was matched. subcommand="merge" reuses the exact same
      # review-pr + eval-artifact gating as raw `gh pr merge` below.
      # pr_num is NOT set here (no arm sets it) — enforce_required_step
      # extracts it from this form the same way it does for `gh pr merge`.
      # Word-boundary: the executed word must be exactly `merge.sh` (optionally
      # path-prefixed and/or quoted) — a name merely containing "merge.sh"
      # (auto_merge.sh, some-merge.shim) must not match, same precedent as the
      # git-merge-base word-boundary fix (PR #42).
      subcommand="merge"; matched_seg="$seg"; break
    elif [[ "$seg" =~ ^git[[:space:]]+-C[[:space:]]+([^[:space:]]+)[[:space:]]+merge([[:space:]]|$) ]]; then
      subcommand="git_merge"; push_target_dir="${BASH_REMATCH[1]}"; break
    elif [[ "$seg" =~ ^git[[:space:]]+-C[[:space:]]+([^[:space:]]+)[[:space:]]+push([[:space:]]|$) ]]; then
      subcommand="git_push"; push_target_dir="${BASH_REMATCH[1]}"; break
    fi
  done <<EOF
$(printf '%s' "$cmd" | awk '{gsub(/&&|\|\||[;|&]/, "\n"); print}')
EOF
  # No gated command was actually invoked → stand aside.
  [ -z "$subcommand" ] && exit 0
  # $subcommand is also read by gate_targets_main and enforce_required_step.
  # $push_target_dir (may be empty) is read by gate_targets_main.
  # $matched_seg (create/merge only) is the SEGMENT that actually matched, not
  # the raw $cmd — enforce_required_step's pr_num extraction scans this rather
  # than $cmd so an earlier segment that only MENTIONS a PR number (e.g.
  # `echo "run merge.sh 999 first" && scripts/merge.sh 140`) can't donate a
  # decoy PR number to the real, later-executed merge invocation.
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
  #    bare-branch targets from any branch — a refspec is not the only way to name main.
  if [ "$subcommand" = "git_merge" ] || [ "$subcommand" = "git_push" ]; then
    # Resolve the directory the git command actually runs in — a leading
    # `cd <dir> &&` prefix or a `git -C <dir>` flag (parsed into push_target_dir
    # by gate_in_scope) both take the command out of $cwd (the payload's
    # session-level cwd). Relative dirs join to $cwd, same idiom as
    # destructive_bash_gate.sh's branch_for_path. Falls back to $cwd verbatim
    # when neither form is present — byte-identical to prior behaviour.
    target_dir="$push_target_dir"
    if [ -z "$target_dir" ] && [[ "$cmd" =~ ^[[:space:]]*cd[[:space:]]+([^[:space:]]+)[[:space:]]*(\&\&|\;) ]]; then
      target_dir="${BASH_REMATCH[1]}"
    fi
    if [ -n "$target_dir" ]; then
      case "$target_dir" in
        /*) ;;
        *) target_dir="$cwd/$target_dir" ;;
      esac
    else
      target_dir="$cwd"
    fi
    current_branch=$(git -C "$target_dir" branch --show-current 2>/dev/null)
    # If the resolved target isn't a usable git repo (e.g. a relative `cd sub`
    # that doesn't exist, or isn't a checkout at all), fall back to $cwd's
    # branch rather than treating an empty/unresolvable branch as "not main" —
    # that would silently widen the gate's blind spot instead of narrowing it.
    if [ -z "$current_branch" ] && [ "$target_dir" != "$cwd" ]; then
      current_branch=$(git -C "$cwd" branch --show-current 2>/dev/null)
    fi
    gate_it=0
    case "$current_branch" in main|master) gate_it=1 ;; esac
    # The destination ref may be terminated by whitespace, EOL, or a shell separator
    # (`git push origin HEAD:main;echo`), so the anchor accepts `;& |)` too — otherwise
    # a metachar abutting the ref trivially evades the gate.
    if [ "$subcommand" = "git_push" ] && \
       printf '%s' "$cmd" | grep -qE ':(refs/heads/)?(main|master)([[:space:];&|)]|$)'; then
      gate_it=1
    fi
    # Also gate `git push` when main/master appears as a standalone
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
      # Matches both plain `git push ...` and `git -C <dir> push ...` (the anchor
      # tolerates an optional `-C <dir>` between `git` and `push` so the -C form's
      # destination args aren't silently skipped).
      push_args=$(printf '%s' "$cmd" | grep -oE '\bgit([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+push[[:space:]](.*)' | sed -E 's/^git([[:space:]]+-C[[:space:]]+[^[:space:]]+)?[[:space:]]+push[[:space:]]*//')
      # Match +main, refs/heads/main, or bare main/master as a standalone token.
      if printf '%s' "$push_args" | grep -qE '(^|[[:space:]])(\+)?(refs/heads/)?(main|master)([[:space:];&|)]|$)'; then
        gate_it=1
      fi
    fi
    [ "$gate_it" -eq 0 ] && exit 0   # neither on, nor targeting, main/master — safe
  fi
}

gate_have_transcript() {
  # In a subagent, .transcript_path is the PARENT session transcript and
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
    # If a PR number is given in the command, require review-pr to have
    # been invoked with that same number in its args. If no PR number is given
    # (bare `gh pr merge`), any review-pr invocation suffices (legacy behaviour).
    required_step="/pr-review-toolkit:review-pr"
    gate_hint="Run /pr-review-toolkit:review-pr first (or add a 'gh pr merge' Bash permission to settings.json to bypass)."

    # Extract the first bare integer argument after "gh pr merge", skipping
    # any leading --flag or --flag=val tokens. This handles forms like:
    #   gh pr merge --squash 42     (flag before number)
    #   gh pr merge --auto 42
    #   gh pr merge 42 --squash     (number first — also handled by stripping flags)
    # Strip the "gh pr merge" prefix, then scan tokens left-to-right for a bare integer.
    # Scoped to $matched_seg (the segment gate_in_scope actually classified as
    # the merge), NOT the raw $cmd — otherwise a PR number mentioned in an
    # earlier, non-executed segment (e.g. `echo "gh pr merge 999" && gh pr
    # merge 140`) would be extracted instead of the real target, since grep
    # over the whole $cmd finds the FIRST occurrence anywhere in the string.
    merge_suffix=$(printf '%s' "$matched_seg" | grep -oE 'gh[[:space:]]+pr[[:space:]]+merge(.*)')
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

    # Parallel extraction for the merge.sh invocation form (mirrors the gh pr
    # merge extraction above rather than inventing a second parser style):
    # find the merge.sh token, then scan remaining tokens left-to-right for
    # the first bare integer, stripping surrounding quotes from each token
    # first (merge.sh args are commonly quoted: `merge.sh "140"`). Also scoped
    # to $matched_seg for the same decoy-number reason as above.
    if [ -z "$pr_num" ]; then
      merge_sh_suffix=$(printf '%s' "$matched_seg" | grep -oE '[^[:space:]]*merge\.sh.*')
      if [ -n "$merge_sh_suffix" ]; then
        merge_sh_args=$(printf '%s' "$merge_sh_suffix" | sed -E 's/^[^[:space:]]*merge\.sh[[:space:]]*//')
        for token in $merge_sh_args; do
          token="${token%\"}"; token="${token#\"}"
          token="${token%\'}"; token="${token#\'}"
          case "$token" in
            --*=*) ;;           # --flag=val: skip
            --*|-*) ;;          # --flag or -f: skip
            [0-9]*) pr_num="$token"; break ;;   # bare integer: this is the PR number
          esac
        done
      fi
    fi

    if [ -n "$pr_num" ]; then
      # Per-PR check — review-pr args must START WITH (or be exactly) the
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
    # Consume-on-use: review-pr must have run SINCE the last git merge.
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

gate_eval_artifact_for_merge() {
  # Closes the gap PR #95 shipped through: scripts/merge.sh already gates `gh
  # pr merge` on a coderails eval artifact (pr::has_coderails_eval_for_head),
  # but a raw `gh pr merge` run outside merge.sh bypassed it entirely. Only
  # acts on the `merge` subcommand — git_merge/git_push have no PR number and
  # stay review-gated only (documented residual gap). Runs AFTER
  # enforce_required_step so the cheap, transcript-only review-pr gate fires
  # and denies first; this function only runs its (network) check once that
  # gate has already passed for this invocation.
  [ "$subcommand" = "merge" ] || return 0
  # If the review-pr gate above already denied, don't also run (and
  # potentially deny again for) the eval gate — one deny per invocation.
  [ "$step_found" -eq 0 ] 2>/dev/null && return 0

  local num="$pr_num"
  # repo()/pr::* are CWD-dependent (e.g. `git remote get-url origin` takes no
  # arg) — cd into the payload's cwd before calling any of them. This is the
  # hook's own process and it exits right after, so a plain `cd` (not a
  # subshell) is safe and is required: a subshell would swallow the
  # PR_EVAL_TIER / PR_TRUST_FETCH_FAIL_REASON globals the deny messages below
  # need from pr::has_coderails_eval_for_head.
  cd "$cwd" 2>/dev/null || {
    jq -n '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: "Blocked: could not resolve working directory to verify the eval artifact for gh pr merge. Retry from a valid repo directory."
      }
    }'
    return 0
  }

  [ -z "$num" ] && num=$(pr::num "$(branch)")
  if [ -z "$num" ]; then
    jq -n '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: "Blocked: gh pr merge — could not resolve a PR number to verify the eval artifact. Retry, or check gh auth/network."
      }
    }'
    return 0
  fi

  local sha; sha=$(pr::head_sha "$num")
  if [ -z "$sha" ]; then
    jq -n --arg n "$num" '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: ("Blocked: gh pr merge " + $n + " — GitHub fetch failed, could not resolve PR head SHA. Retry, or check gh auth/network.")
      }
    }'
    return 0
  fi

  local eval_rc=0
  pr::has_coderails_eval_for_head "$num" "$sha" || eval_rc=$?

  if [ "$eval_rc" -eq 2 ]; then
    local reason
    case "${PR_TRUST_FETCH_FAIL_REASON:-}" in
      identity)   reason="Blocked: gh pr merge $num — GitHub fetch failed, could not resolve the authenticated identity (gh api user) for the eval artifact gate. Retry, or check gh auth/network." ;;
      permission) reason="Blocked: gh pr merge $num — GitHub fetch failed, could not resolve repo permission for the eval artifact gate. Retry, or check gh auth/network." ;;
      tempfile)   reason="Blocked: gh pr merge $num — local temporary file allocation failed (mktemp) before any GitHub fetch was attempted for the eval artifact gate. Check /tmp disk space or permissions, then retry." ;;
      *)          reason="Blocked: gh pr merge $num — GitHub fetch failed, could not fetch PR comments for the eval artifact. Retry, or check gh auth/network." ;;
    esac
    jq -n --arg r "$reason" '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: $r
      }
    }'
  elif [ "$eval_rc" -ne 0 ]; then
    local reason
    if [ -n "${PR_EVAL_TIER:-}" ]; then
      reason="Blocked: gh pr merge $num — eval artifact for current head $sha is NO-GO (tier $PR_EVAL_TIER). Resolve failing P0 evals and re-run /coderails:post-evals."
    else
      reason="Blocked: gh pr merge $num — no coderails eval artifact for current head $sha. Run /coderails:task-evals then /coderails:post-evals after /pr-review-toolkit:review-pr."
    fi
    jq -n --arg r "$reason" '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: $r
      }
    }'
  else
    gate_tier_floor "$num" || return 0
    gate_tier_review_status "$num" "$sha"
  fi
  return 0
}

# gate_tier_floor <num>
# Blocks the merge when the PR's SELF-DECLARED tier (PR_EVAL_TIER, set by the
# eval-artifact gate that ran immediately above) is below the floor derived
# from the diff itself. Emits a deny decision and returns 1 when it blocks,
# so the caller stops and does not also emit a second decision; returns 0
# (silently) when the claim clears the floor or when the diff could not be
# fetched at all.
#
# Always on — no config key, no override, unlike gate_tier_review_status.
# The tier this consumes is the same trusted-but-self-declared value every
# other gate here reads; this is the only check that tests it against the
# change under review.
gate_tier_floor() {
  local num="$1"
  local out rc=0
  out=$(tier_floor::gate_pr "${PR_EVAL_TIER:-}" "$num") || rc=$?

  # rc 3 is an infrastructure failure (the diff fetch itself errored) — the
  # floor could not be evaluated, so it does not block; the eval, review and
  # tier-review gates still apply. rc 1 (claim below the derived floor) and
  # rc 2 (fetch succeeded but the evidence is unusable) BOTH block: an empty
  # file list zeroes every count and would pass every size cap vacuously, so
  # it must never be read as a pass.
  case $rc in
    0|3) return 0 ;;
  esac

  jq -n --arg r "Blocked: gh pr merge $num — $out" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $r
    }
  }'
  return 1
}

# coderails::_tier_review_machine_user <config_file>
# Echoes the value of the nested key tier_review.machine_user from a
# workflow.config.yaml, or nothing if the key/block is absent. Mirrors
# scripts/merge.sh's identically-named function (no shared lib file is in
# this task's manifest, so both gates carry their own copy) — no generic
# nested-key YAML reader exists in this repo (scripts/lib/config.sh only
# locates the file); this is a minimal, single-purpose extractor for this
# one key, not a new config system.
coderails::_tier_review_machine_user() {
  local config_file="$1"
  [ -f "$config_file" ] || return 0
  awk '
    /^tier_review:[[:space:]]*$/ { in_block=1; next }
    in_block && /^[^[:space:]]/ { in_block=0 }
    in_block && /^[[:space:]]+machine_user:/ {
      sub(/^[[:space:]]+machine_user:[[:space:]]*/, "")
      gsub(/^["'"'"']|["'"'"']$/, "")
      gsub(/[[:space:]]*#.*$/, "")
      gsub(/[[:space:]]+$/, "")
      print
      exit
    }
  ' "$config_file" 2>/dev/null
}

# gate_tier_review_status <num> <sha>
# Redundant defence-in-depth layer (fail-closed): once the eval-artifact gate
# above has ALREADY passed, this additionally requires a `tier-review` commit
# status of state=success, posted by the configured machine user, whose
# description carries verdict=legitimate AND a tier=N token matching this
# artifact's own claimed tier (PR_EVAL_TIER, set by pr::has_coderails_eval_for_head
# in the caller). This layer is REDUNDANT BY DESIGN once the server-side
# ruleset is live (belt-and-braces) — it exists to fail loudly on
# misconfiguration and to hold the line during the pre-ruleset interim. It is
# NOT the primary control — do not delete it as dead code once the ruleset is
# active; it is the only local check that catches a machine-user
# misconfiguration before GitHub itself would. Config-keyed and inactive by
# default: only runs when config key tier_review.machine_user is set (config
# absent -> other installs unaffected). Runs at EVERY tier — the daemon
# (tier-gate-runner) now judges every tier, not just tier 0, so this gate is
# no longer restricted to PR_EVAL_TIER=0. Emits a deny JSON on any failure;
# emits nothing (stands aside) when inactive or when the check passes — same
# "one deny per invocation" contract as gate_eval_artifact_for_merge's caller.
gate_tier_review_status() {
  local num="$1" sha="$2"
  local config_file; config_file=$(coderails::config_path "$cwd")
  [ -z "$config_file" ] && return 0
  local machine_user; machine_user=$(coderails::_tier_review_machine_user "$config_file")
  [ -z "$machine_user" ] && return 0

  local statuses tr_rc=0
  statuses=$(gh api "repos/$(repo)/commits/${sha}/statuses" --paginate \
    --jq '[.[] | select(.context == "tier-review")]' 2>/dev/null) || tr_rc=$?
  if [ "$tr_rc" -ne 0 ]; then
    jq -n --arg r "Blocked: gh pr merge $num — GitHub fetch failed, could not fetch tier-review status for $sha. Retry, or check gh auth/network." '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: $r
      }
    }'
    return 0
  fi

  local state creator description
  state=$(printf '%s' "$statuses" | jq -r '.[0].state // empty' 2>/dev/null)
  creator=$(printf '%s' "$statuses" | jq -r '.[0].creator.login // empty' 2>/dev/null)
  description=$(printf '%s' "$statuses" | jq -r '.[0].description // empty' 2>/dev/null)

  local reason=""
  if [ -z "$state" ]; then
    reason="Blocked: gh pr merge $num — no tier-review status found for $sha. The tier-gate daemon has not judged this SHA yet. Wait for it, or kickstart it, then retry."
  elif [ "$state" != "success" ]; then
    reason="Blocked: gh pr merge $num — tier-review status for $sha is '$state' (not success). The tier-gate daemon has not approved this SHA. Resolve and retry."
  elif [ "$creator" != "$machine_user" ]; then
    reason="Blocked: gh pr merge $num — tier-review status for $sha was posted by '$creator', not the configured machine user '$machine_user'. This is a misconfiguration-or-forgery signal, not a valid verdict. Do not bypass; investigate the creator mismatch."
  else
    case "$description" in
      *"verdict=legitimate"*) : ;;
      *)
        # state=success is necessary but NOT sufficient: only a genuine
        # `legitimate` judgment carries verdict=legitimate in its description
        # (tier-gate-runner tg_gate_pr). Mirrors scripts/merge.sh's identical
        # check — closes the verdict-laundering path where an otherwise-
        # minted success is reused as a pass.
        reason="Blocked: gh pr merge $num — tier-review status for $sha is success but its description ('$description') does not carry verdict=legitimate. This is not a genuine approval (e.g. a laundered or non-judged status). Do not bypass; investigate."
        ;;
    esac
    if [ -z "$reason" ]; then
      case "$description" in
        *[[:space:]]tier=${PR_EVAL_TIER}[[:space:]]*|*[[:space:]]tier=${PR_EVAL_TIER}) : ;;
        tier=${PR_EVAL_TIER}[[:space:]]*|tier=${PR_EVAL_TIER}) : ;;
        *)
          # Tier-binding (anti-laundering): the status description must carry
          # a tier=N token matching THIS artifact's own claimed tier.
          # Space/end-of-string delimited so tier=1 can never satisfy tier=12
          # (or vice versa) via a bare substring match. Mirrors
          # scripts/merge.sh's identical check.
          reason="Blocked: gh pr merge $num — tier-review status for $sha carries description ('$description') that does not match this artifact's claimed tier ${PR_EVAL_TIER}. A status minted for a different tier cannot satisfy this claim. Do not bypass; investigate."
          ;;
      esac
    fi
  fi

  if [ -n "$reason" ]; then
    jq -n --arg r "$reason" '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: $r
      }
    }'
  fi
  return 0
}

gate_has_command
gate_safe_passthrough
gate_in_scope
gate_config_present
gate_targets_main
gate_have_transcript
enforce_required_step
gate_eval_artifact_for_merge

exit 0
