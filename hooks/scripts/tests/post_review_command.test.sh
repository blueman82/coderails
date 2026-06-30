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

[[ $fails -eq 0 ]] && { echo PASS; exit 0; } || { echo "FAIL ($fails)"; exit 1; }
