---
name: prep
description: Create an isolated feature or bug worktree and optionally create and link a Jira ticket. Use when starting repository work that needs a new feature, bug, or bugfix branch.
---

# Prepare isolated work

Create the Git worktree first. Jira setup is optional and must never undo or invalidate a successfully created worktree.

## Gather the request

Identify:

- A required branch named `feature/...`, `bug/...`, or `bugfix/...`.
- An optional issue type, summary, and description.

If the branch is missing or ambiguous, use `request_user_input` to ask only for the branch name. Infer `Task` for feature branches and `Bug` for bug branches. When absent, generate a plain summary from the branch suffix and a short description that includes `Branch: <branch>`.

## Read project configuration

Resolve the nearest `.coderails/workflow.config.yaml` by walking from the current directory upward to the Git root. The first file found wins. Otherwise use:

- `worktree_base`: the Git root.
- `worktree_script`: unset.
- `jira`: unset.

Do not change configuration. Ignore Claude-specific configuration.

## Create the worktree

1. Run read-only Git checks to find the repository root, current branch, existing worktrees, and status.
2. Remove the `feature/`, `bug/`, or `bugfix/` prefix from the branch to form the worktree suffix.
3. Set the worktree path to `<worktree_base>-<suffix>`.
4. Fail before writing if the branch or worktree path already exists, or if either target is ambiguous.
5. From the Git root, run the configured worktree script with `<path> <branch>` when one is set. Otherwise run:

   ```bash
   git worktree add <path> -b <branch>
   ```

Report the created branch and absolute worktree path.

## Create a Jira ticket when configured

Skip Jira when `jira` is unset. If Jira is configured but no matching Jira tool is available, keep the worktree and report that only Jira setup was skipped.

Use the configured Jira project and available Jira tools to:

1. Create the issue with the inferred or supplied type, summary, description, and the currently authenticated user as assignee.
2. Add the configured epic and component only when both the relevant field and value are present.
3. Set a configured fix version and story-points field through Jira's update operation.
4. Apply the configured start transition. Attempt the configured resolve transition afterward, but treat its absence or rejection as non-fatal.
5. After creation succeeds, store the issue key in the new worktree:

   ```bash
   git config branch.<branch>.jira-ticket <issue-key>
   ```

Do not hardcode Jira users, fields, transitions, namespaces, or project values. Jira failure is non-fatal after the worktree exists.

## Finish

Summarize the branch, worktree path, and Jira key when one was created. State any skipped or failed optional Jira step plainly.
