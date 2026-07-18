---
allowed-tools: ["Bash", "Read", "Skill"]
argument-hint: [commit message] [--quick]
description: Add, commit, push changes and create PR
---

## Project config

Config: !`source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/config.sh" && coderails::resolve_config`

## Pre-flight: engineering-principles check

**Skip condition**: If `$ARGUMENTS` contains `--quick`, skip this section entirely and go straight to push. Strip `--quick` from the arguments before passing to push.sh.

**Skip condition**: If `config.engineering_principles_paths` is null or empty (or config is `NO_CONFIG`), skip this section entirely and go straight to push.

**Non-interactive context**: If you are running as a sub-task (conductor, background agent) with no interactive user turn available, log any findings but proceed to push — do not block.

**Trigger**: Determine the base branch first: `git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@.*/@@'` (falls back to `main` if unset). Then run `git diff --name-only $(git merge-base HEAD <base>)..HEAD` and check if ANY changed files match the patterns listed in `config.engineering_principles_paths`.

If **no files match**, skip to push.

If **files match**, run `config.engineering_principles_skill` (default: `/engineering-principles-python`) on the changed files matching those patterns.

### Interpreting findings

Apply this decision rule to engineering-principles output:

- **Blocking**: Any deviation from the project's documented architectural conventions (e.g. DI protocol patterns, module registration rules, required test updates per public contract changes). Block and prompt.
- **Non-blocking**: Style preferences, readability suggestions, naming opinions. Log the note and proceed.

If blocking findings exist, present them as a numbered list and ask: **"Fix these before pushing, or push as-is?"** Then follow the user's answer.

If no blocking findings, proceed silently.

---

## Push

Execute the push workflow script. Remove `--quick` from arguments if present.

`push.sh` stages tracked-modified files automatically (`git add -u`) but never sweeps up new, untracked files — that's deliberate, to avoid dragging unrelated working-tree files into the PR. If you (the actor running this command) created NEW files that belong in this PR, list them explicitly and pass each one via a repeatable `--add <path>` flag. You know what you created; don't stage new files with a separate `git add` sweep — name them to push.sh instead.

Use a separate `--add` flag per file, one path per occurrence — never a space-separated variable like `--add $FILES`. `--add` consumes exactly one token, so `--add $FILES` would stage only the first file and the rest would be silently misparsed as extra arguments (the next token becomes part of the commit message). Name individual files, not directories or globs — a directory would stage everything under it, including files that aren't yours. Example shape:

```bash
bash "${CLAUDE_PLUGIN_ROOT}/scripts/push.sh" "$ARGUMENTS" --add path/to/newfile --add path/to/another
```

The script handles:
1. Staging tracked-modified files, plus any `--add <path>` files named explicitly
2. Creating commit (with provided message or auto-generated)
3. Pushing branch to origin
4. Creating or updating Pull Request

## JIRA Auto-Resolve

After the PR is created, check for a linked JIRA ticket and resolve it:

```bash
BRANCH=$(git branch --show-current)
JIRA_KEY=$(git config branch.$BRANCH.jira-ticket 2>/dev/null)
```

If `JIRA_KEY` is set, transition the ticket to **Resolved** via whichever Jira route you have:
Read `config.jira.mcp_namespace` from the project config (default: `jira` if unset or config is `NO_CONFIG`). Call `mcp__<mcp_namespace>__transition_jira_status_by_name` with `{issueIdOrKey: JIRA_KEY, statusName: "<config.jira.transitions.resolve>", comment: "..."}`. For non-default namespaces, calls fall through to the normal permission system (one-time prompt or a `mcp__<mcp_namespace>__*` rule in `settings.json` `permissions.allow` — see INSTALLATION.md).

Then:
1. Use comment text: `"Resolved via PR merge. Work implemented via AI-assisted development (Claude Code). Branch: $BRANCH."`
2. Report the resolved ticket key alongside the PR URL

If `JIRA_KEY` is empty, skip silently — not all branches have tickets.

Report the PR URL (and resolved JIRA key if applicable) when complete.
