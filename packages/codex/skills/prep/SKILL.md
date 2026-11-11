---
name: prep
description: Create an isolated feature or bug worktree and optionally create and link a Jira ticket. Use when starting repository work that needs a new feature, bug, or bugfix branch.
---

# Prepare isolated work

Make the Git worktree first. Jira setup is optional. The worktree must stay usable if Jira setup does not complete.

## Gather the request

Identify:

- A required branch named `feature/...`, `bug/...`, or `bugfix/...`.
- An optional issue type, summary, and description.

If you have no branch name or it is ambiguous, use `request_user_input` to get only that name.
Infer `Task` for feature branches and `Bug` for bug branches.
When missing, generate a plain summary from the branch suffix and a short description that includes `Branch: <branch>`.

## Read project configuration

Before resolving the Git root or configuration, run `git rev-parse --show-toplevel`. If the current folder is not in a Git repository, create the local-only base required for the worktree:

```bash
git init -b main
git add -A
git commit --allow-empty -m "Initial project"
```

If a command exits with an error, stop and report that command. Tell the user if Git has no author identity.
Do not add a remote, make a hosted repository, push, or open a PR.

Look for `.coderails/workflow.config.yaml` from the current directory up to the Git root. Use the first file you find.
If there is no file, use these values:

- `worktree_base`: the Git root.
- `worktree_script`: unset.
- `jira`: unset.

Do not change configuration. Ignore Claude-specific configuration.

## Create the worktree

1. Run read-only Git checks to find the repository root, current branch, existing worktrees, and status.
2. Remove the `feature/`, `bug/`, or `bugfix/` prefix from the branch name to get the worktree suffix.
3. Set the worktree path to `<worktree_base>-<suffix>`.
4. Stop before writing if the branch or worktree path exists, or if one of the two targets is ambiguous.
5. From the Git root, run the configured worktree script with `<path> <branch>` if the config gives one.
   If the config does not give one, run:

   ```bash
   git worktree add <path> -b <branch>
   ```

Report the created branch and absolute worktree path. In a local-only repository, `main` is the base. Do not make or require `origin`.

## Create a Jira ticket when configured

Skip Jira when `jira` is unset. If Jira is configured but no matching Jira tool is available, keep the worktree and report that only Jira setup was skipped.

Use the configured Jira project and available Jira tools to:

1. Make the issue with the inferred or supplied type, summary, description, and the currently authenticated user as assignee.
2. Add the configured epic and component only if the config gives the related field and value for each.
3. Set a configured fix version and story-points field through Jira's update operation.
4. Apply the configured start status change. Then try the configured resolve status change.
   Continue if that change is unavailable or Jira rejects it.
5. After creation succeeds, store the issue key in the new worktree:

   ```bash
   git config branch.<branch>.jira-ticket <issue-key>
   ```

Do not hardcode Jira users, fields, status changes, namespaces, or project values.
If a Jira step does not complete after Git makes the worktree, keep the worktree and continue.

## Finish

Summarize the branch, worktree path, and Jira key if available.
Report which optional Jira steps you skipped or could not complete.
