#!/bin/bash
# PreToolUse Bash hook: hard-block the 3rd+ invocation, per work-unit, of
# either hooks/scripts/tests/run_all.sh (the full suite runner) or a
# post_evals.sh validate-structure ceremony (the per-ceremony anchor
# subcommand -- see below). 1st and 2nd invocation of each target are
# allowed, matched independently (2 run_all.sh + 2 post_evals.sh is fine).
# Returns permissionDecision="deny" on the 3rd+ call — hard block, no
# env-var escape valve.
#
# Work-unit key: the current git branch of the command's cwd (one branch =
# one work-unit, this repo's convention). Detached HEAD / non-repo cwd falls
# back to a fixed shared bucket "(no-branch)" rather than silently no-opping.
#
# post_evals.sh predicate: only the "validate-structure" subcommand counts.
# That subcommand is step 1 of every /coderails:post-evals ceremony
# (commands/post-evals.md) and fires exactly once per ceremony, so counting
# it is equivalent to counting ceremonies. compute-result,
# validate-discriminating, and validate-embed are invoked multiple times per
# ceremony by design (confirmed by reading commands/post-evals.md) and are
# NEVER counted or blocked here — counting every invocation of the script
# path would deny the very first legitimate ceremony's own validate-embed
# call.

IFS= read -r -d '' -t 5 input || true
cmd=$(printf '%s' "$input" | jq -r '.tool_input.command // empty')
[ -z "$cmd" ] && exit 0

cwd=$(printf '%s' "$input" | jq -r '.cwd // empty')
[ -z "$cwd" ] && cwd="$PWD"

# Invocation-shape matcher for run_all.sh: the command must actually RUN the
# script, not merely mention its path (a grep/cat/echo referencing the path
# must not match). Matched at the start of the command, or after a shell
# separator (&&, ;, |, newline), optionally preceded by an interpreter
# prefix (bash/sh/./) and any leading path segments.
run_all_re='(^|[&;|]|&&|\|\|)[[:space:]]*(bash[[:space:]]+|sh[[:space:]]+|\./)?([^[:space:]]*/)?hooks/scripts/tests/run_all\.sh([[:space:]]|$)'
cmd_flat=$(printf '%s' "$cmd" | tr '\n' ' ')

# Invocation-shape matcher for post_evals.sh, capturing the subcommand token
# immediately following the script path. Only a "validate-structure"
# subcommand counts (see header comment above).
post_evals_re='(^|[&;|]|&&|\|\|)[[:space:]]*(bash[[:space:]]+|sh[[:space:]]+|\./)?([^[:space:]]*/)?scripts/post_evals\.sh[[:space:]]+validate-structure([[:space:]]|$)'

target=""
if printf '%s' "$cmd_flat" | grep -qE "$run_all_re"; then
  target="run_all"
elif printf '%s' "$cmd_flat" | grep -qE "$post_evals_re"; then
  target="post_evals"
else
  exit 0
fi

branch=$(git -C "$cwd" branch --show-current 2>/dev/null)
[ -z "$branch" ] && branch="(no-branch)"
branch_slug=$(printf '%s' "$branch" | tr '/' '-')

base="${CLAUDE_AGENTIC_LOOP_DIR:-$HOME/.coderails/agentic-loop}"
state_dir="$base/verification-ceiling"

deny_state_failure() {
  # Fail closed: this is a hard-block hook, so if the count can't be reliably
  # read/written/locked, the safe default is to deny rather than silently let
  # the cap disappear (matches crack_on_gate.sh's write-check convention).
  jq -n --arg r "$1" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $r
    }
  }'
  exit 0
}

if ! mkdir -p "$state_dir" 2>/dev/null; then
  deny_state_failure "Verification-volume ceiling: could not create its state directory ($state_dir) to track invocation counts, so the count for this work-unit branch cannot be reliably tracked. Failing closed (deny) rather than silently letting the ceiling disappear."
fi

count_file="$state_dir/${branch_slug}__${target}.count"
lock_dir="${count_file}.lock"

# mkdir-based lock around the count-file read-modify-write critical section:
# atomic mkdir succeeds/fails uniquely with no external dependency. Retry for
# up to ~1.5s (well inside this hook's 5s hooks.json timeout budget, which
# also covers the earlier `read -t 5` and jq calls) before failing closed.
lock_acquired=0
attempt=0
while [ "$attempt" -lt 15 ]; do
  if mkdir "$lock_dir" 2>/dev/null; then
    lock_acquired=1
    break
  fi
  attempt=$((attempt + 1))
  sleep 0.1
done

if [ "$lock_acquired" -ne 1 ]; then
  script_name="hooks/scripts/tests/run_all.sh"
  [ "$target" = "post_evals" ] && script_name="scripts/post_evals.sh validate-structure"
  deny_state_failure "Verification-volume ceiling: could not acquire the per-target lock for $script_name on work-unit branch '$branch' within the timeout — a concurrent invocation is holding it. Failing closed (deny) rather than risk an undercounted read-modify-write."
fi
trap 'rmdir "$lock_dir" 2>/dev/null' EXIT

count=0
[ -f "$count_file" ] && count=$(cat "$count_file" 2>/dev/null)
case "$count" in
  ''|*[!0-9]*) count=0 ;;
esac

# Single write of count+1, done up front so it covers both the allow and the
# deny path (the deny path also increments, so a retried 3rd+ call doesn't
# reset the count) — matches the previous behaviour with one write instead of
# two, since emitting deny JSON and THEN writing would put two JSON values on
# stdout if the second write also needed to emit on failure.
if ! printf '%s' "$((count + 1))" > "$count_file" 2>/dev/null; then
  deny_state_failure "Verification-volume ceiling: could not write its invocation-count file ($count_file) for work-unit branch '$branch'. Failing closed (deny) rather than silently letting the ceiling reset to 0 on every call."
fi

if [ "$count" -ge 2 ]; then
  script_name="hooks/scripts/tests/run_all.sh"
  [ "$target" = "post_evals" ] && script_name="scripts/post_evals.sh validate-structure"
  reason="Verification-volume ceiling: this is the $((count + 1))th invocation of $script_name on work-unit branch '$branch' — the 3rd+ re-run of the same suite/ceremony per work-unit is hard-blocked (no override). Delegate further re-verification to a verifier agent that returns a one-line verdict instead of re-running the full suite/ceremony in-context; re-reading the same output repeatedly at growing context is the exact cost pattern this cap exists to stop."
  jq -n --arg r "$reason" '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $r
    }
  }'
  exit 0
fi

exit 0
