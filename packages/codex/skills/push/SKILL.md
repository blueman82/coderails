---
name: push
description: Commit intended changes, push the current feature branch, and create or update its pull request. Use when work is ready to publish for review.
---

# Push a feature branch

Use the package-local [push helper](../../scripts/push.py) to add changes to the Git index, commit, push, and open or update the PR.

## Before pushing

1. Check that the current directory is a Git repository. Stop if it is not.
   Stop if the current branch is `main` or `master`.

2. Find the nearest `.coderails/workflow.config.yaml` between the current directory and the repository root.
   If there is no file, use no project config.

3. Compare changed files against the remote default branch unless the user selects `quick mode`.
   If paths in `engineering_principles_paths` apply, invoke `$coderails-codex:engineering-principles` on those files.

4. Block the push if changes violate documented architecture, registration rules, or mandatory contract tests.
   Show the violations.
   Use `request_user_input` to let the user select a correction or a push without changes.
   If user input is unavailable, stop before pushing.
   Style and naming suggestions do not block the push.

## Run the helper

Resolve the linked helper relative to this `SKILL.md`, then run it from the user's repository.

- If the user supplies a commit message, give it to the helper as one argument.
- Remove wording about `quick mode` before you invoke the helper.
- The helper uses `git add -u` for tracked modifications. Do not also use a broad `git add`.
- For each new file for this work, give one explicit `--add path/to/file` argument.
- Do not give directories, globs, unrelated files, or multiple paths through one `--add`.
- Give `--force-with-lease` only if the user explicitly tells you to use it. Do not use an unconditional force push.
- If this session owns a graph unit in this worktree, give its `--unit <id> --progress <absolute state path>`.
  Read the two values from the active graph. Do not guess them.

The `pr_publication_gate` hook checks the trusted push helper before `action_authority_gate`.
For a graph unit, run in its assigned canonical worktree. Give the unit ID and absolute path of the graph file this session owns.
If the hook refuses the binding, read the active graph. Correct the directory or arguments before you try again.

If there is no active graph unit, omit the two flags.
This read-only check does not consume a receipt. The existing authority and receipt checks apply.

The hook recognizes the documented `${PLUGIN_ROOT}` syntax and direct Python script options.
The check does not include Python `-c`/`-m`, arbitrary shell expansions, or custom script wrappers.
Invoke the helper directly for graph publication.

The helper must stop with an error if the branch has protection or if the commit, push, or PR operation does not succeed.
It must also stop with an error if the remote branch head differs from local `HEAD`.
Report success only if the helper gives a PR URL.

## Linked Jira ticket

After the PR exists, read `branch.<current-branch>.jira-ticket` from Git config. If there is no ticket, skip this step.

Use the Jira connector that `jira.mcp_namespace` names in the project config. The default is `jira`.
Move the ticket to the configured resolve status. Add this comment:

`Resolved via PR merge. Work implemented via AI-assisted development (Codex). Branch: <branch>.`

If the configured Jira connector or status change is unavailable, report that the ticket is not resolved. Do not invent success.

Report the PR URL. If Jira applies, also give the ticket key and the result of the status change.
