#!/bin/bash
# Regression guards for commands/post-review.md and commands/workflow.md.
# These grep-based assertions catch the specific bug class: using -f (static string)
# instead of -F (file-read) in the gh api call, and documenting a bare "review-pr all"
# invocation that fails the enforce_pr_workflow.sh per-PR gate.
set -u
REPO_ROOT="$(cd "$(dirname "$0")/../../.." && pwd)"
POST_REVIEW_CMD="$REPO_ROOT/commands/post-review.md"
WORKFLOW_CMD="$REPO_ROOT/commands/workflow.md"

fails=0

check() { # desc expected_exit actual_exit
  if [[ "$2" == "$3" ]]; then printf 'ok   - %s\n' "$1"
  else printf 'FAIL - %s\n  expected exit: %s\n  actual exit:   %s\n' "$1" "$2" "$3"; fails=$((fails+1)); fi
}

# ─── Fix 1: gh api must use -F (file-read), not -f (literal string) ──────────

# -F body=@ must be present in the gh api call
grep -qF -- '-F body=@' "$POST_REVIEW_CMD"
check "post-review.md: gh api uses -F body=@ (file-read form)" 0 $?

# -f body=@ must NOT be present (the literal-string bug form)
grep -qF -- '-f body=@' "$POST_REVIEW_CMD"
check "post-review.md: gh api does NOT use -f body=@ (literal-string form is absent)" 1 $?

# ─── Fix 2: workflow.md must not instruct bare 'review-pr all' ───────────────

# The Phase 3 review-pr invocation must include the PR# placeholder, not bare 'all'.
# A bare "review-pr all" as the sole argument fails the per-PR hook gate because
# the args don't start with the PR number.
grep -qF '`/pr-review-toolkit:review-pr all`' "$WORKFLOW_CMD"
check "workflow.md: bare '/pr-review-toolkit:review-pr all' invocation is absent" 1 $?

# The Phase 3 step must reference the PR# placeholder so the hook gate is satisfied.
grep -qF '/pr-review-toolkit:review-pr <PR#>' "$WORKFLOW_CMD"
check "workflow.md: review-pr invocation includes <PR#> placeholder" 0 $?

# ─── Fix 3: dedup --jq filter must guard no-match with select(. != null) ─────

# Without this guard, `[] | first` yields null, and `null | {url:.html_url,...}`
# produces a non-empty JSON object with null fields — causing the bash dedup check
# to falsely conclude an artifact already exists and skip posting.
grep -qF 'select(. != null)' "$POST_REVIEW_CMD"
check "post-review.md: dedup --jq filter contains select(. != null) no-match guard" 0 $?

# ─── Fix 4: numeric-only guard on the $ARGUMENTS PR-number argument ──────────
# rev97-security EXPERIMENTALLY confirmed that $(...) command-substitution
# payloads in $ARGUMENTS execute at render time inside ANY render-time
# `!`cmd`` line — no quoting scheme survives this, because the substitution
# is a textual splice performed before the shell parses quotes. The only
# sound fix is removing $ARGUMENTS from render-time lines entirely, and
# moving the numeric check to a model-level inspection gate (Step 0) that
# never pastes the argument into a shell command ahead of validation.

# A "Step 0" gate must appear before "Step 1", instructing the model to
# validate the argument by inspection before running any step.
grep -qF '## Step 0' "$POST_REVIEW_CMD"
check "post-review.md: a Step 0 argument gate section exists" 0 $?

step0_line=$(grep -n '## Step 0' "$POST_REVIEW_CMD" | head -1 | cut -d: -f1)
step1_line=$(grep -n '## Step 1' "$POST_REVIEW_CMD" | head -1 | cut -d: -f1)
if [[ -n "$step0_line" && -n "$step1_line" && "$step0_line" -lt "$step1_line" ]]; then
  ordering_ok=0
else
  ordering_ok=1
fi
check "post-review.md: Step 0 gate appears before Step 1" 0 "$ordering_ok"

# The render-time PR-state line must be argument-free (merge.md's convention).
grep -qF -- '- Open PRs: !`gh pr list --state open --limit 10`' "$POST_REVIEW_CMD"
check "post-review.md: render-time line is the argument-free 'Open PRs' form" 0 $?

# No render-time `!`cmd`` line anywhere in post-review.md may contain $ARGUMENTS —
# this is the specific bug class (render-time textual substitution defeats all quoting).
grep -qE '!`[^`]*\$ARGUMENTS[^`]*`' "$POST_REVIEW_CMD"
check "post-review.md: no render-time !\`cmd\` line contains \$ARGUMENTS" 1 $?

# ─── Class-wide: no commands/*.md may put $ARGUMENTS in a render-time line ───
# Proves the fix is a repo-wide invariant, not a one-off patch on this file.
class_violation=0
for f in "$REPO_ROOT"/commands/*.md; do
  if grep -qE '!`[^`]*\$ARGUMENTS[^`]*`' "$f"; then
    printf '  violation: %s\n' "$f"
    class_violation=1
  fi
done
check "commands/*.md: no file has a render-time !\`cmd\` line containing \$ARGUMENTS" 0 "$class_violation"

[[ $fails -eq 0 ]] && { echo PASS; exit 0; } || { echo "FAIL ($fails)"; exit 1; }
