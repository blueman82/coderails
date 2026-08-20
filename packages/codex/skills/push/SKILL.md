---
name: push
description: Commit intended changes, push the current feature branch, and create or update its pull request. Use when work is ready to publish for review.
---

# Push a feature branch

Use the package-local [push helper](../../scripts/push.sh) for the final stage, commit, push, and pull-request operation.

## Before pushing

1. Confirm the current directory is a Git repository and the current branch is neither `main` nor `master`. Stop on either failure.
2. Resolve the nearest `.codex/workflow.config.yaml` between the current directory and the repository root. Treat an absent file as no project config.
3. Unless the user requested quick mode, inspect changed files against the remote default branch. If configured `engineering_principles_paths` match, invoke `$coderails-codex:engineering-principles` on those files.
4. Treat violations of documented architecture, registration rules, or required contract tests as blocking. Present them and use `request_user_input` to ask whether to fix them or push as-is. If user input is unavailable, stop before pushing. Style and naming suggestions are non-blocking.

## Run the helper

Resolve the linked helper relative to this `SKILL.md`, then run it from the user's repository.

- Pass the requested commit message as one argument, if provided.
- Remove any quick-mode wording before invoking the helper.
- The helper stages tracked modifications with `git add -u`; do not run a separate broad `git add`.
- For each new file created for this work, pass one explicit `--add path/to/file` argument. Never pass directories, globs, unrelated files, or multiple paths through one `--add`.
- Pass `--force-with-lease` only when the user explicitly requested it. Never use an unconditional force push.

The helper must fail if the branch is protected, the commit or push fails, the remote branch does not match local `HEAD`, or pull-request creation fails. Do not report success without its resulting pull-request URL.

## Linked Jira ticket

After the pull request exists, read `branch.<current-branch>.jira-ticket` from Git config. If it is absent, skip this step.

If present, use the Jira connector named by `jira.mcp_namespace` in the project config, defaulting to `jira`, to move the ticket to the configured resolve status. Add this comment:

`Resolved via PR merge. Work implemented via AI-assisted development (Codex). Branch: <branch>.`

If the configured Jira connector or transition is unavailable, report that the ticket was not resolved; do not invent success.

Finish by reporting the pull-request URL and, when applicable, the Jira ticket key and actual transition result.
