---
allowed-tools: ["Bash", "Read"]
argument-hint: [pr-number | branch-name | auto]
description: Merge approved PR, switch to main, and pull latest changes
---

## Current state

- Current branch: !`git branch --show-current`
- Open PRs: !`gh pr list --state open --limit 10`

Execute the merge workflow script:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/merge.sh" "$ARGUMENTS"
```

The script handles:
1. Detecting PR from argument (number, branch name, or current branch)
2. Checking if repository requires PR approval
3. Verifying approval if required
4. Merging PR with branch deletion
5. Switching to main branch
6. Pulling latest changes
7. Showing recent commit history

Report success and final state when complete.
