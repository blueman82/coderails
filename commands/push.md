---
allowed-tools: ["Bash", "Read", "Skill"]
argument-hint: [commit message] [--quick]
description: Add, commit, push changes and create PR
---

## Project config

Config: !`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lib/config.py" resolve-config`

## Pre-flight: engineering-principles check

**Skip condition**: If `$ARGUMENTS` contains `--quick`, go directly to push. Remove `--quick` from the arguments to push.py.

**Skip condition**: Go directly to push if `config.engineering_principles_paths` is null or empty, or if config is `NO_CONFIG`.

**Non-interactive context**: A sub-task can have no interactive user turn. If so, log the results and continue to push.

Get the base branch first with `git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@.*/@@'`. Use `main` if the result is unset. Then run `git diff --name-only $(git merge-base HEAD <base>)..HEAD`. Check changed files against the patterns in `config.engineering_principles_paths`.

If **no files match**, skip to push.

If **files match**, run `config.engineering_principles_skill` (default: `/engineering-principles-python`) on the changed files matching those patterns.

### Interpreting findings

Apply this decision rule to engineering-principles output:

- **Blocking**: A deviation from a documented architectural convention. Examples include DI protocol patterns, module registration rules, and required tests for public contract changes. Block and prompt.
- **Non-blocking**: Style preferences, readability suggestions, naming opinions. Log the note and proceed.

If results block the push, give the user a numbered list and prompt: **"Fix these before pushing, or push as-is?"** Follow the user's answer.

If no results block the push, continue silently.

---

## Push

Run the push workflow script. Remove `--quick` from the arguments if they contain it. If this session owns a graph unit in this worktree, pass `--unit <id> --progress <absolute state path>`. Read the two values from the active graph. Do not guess them.

The `enforce_pr_workflow` hook checks the trusted push helper before it checks authority for the push. For a graph unit, run from its canonical assigned worktree. Use the unit ID and absolute graph path that this session owns. If the hook refuses the binding, read the active graph. Correct the directory or arguments before you retry.

If there is no active graph unit, omit the two flags. This read-only check does not consume a receipt. The authority and receipt checks continue to apply.

The hook accepts the documented `${CLAUDE_PLUGIN_ROOT}` syntax and direct Python script options. The check excludes Python `-c`/`-m`, arbitrary shell expansions, and custom execution wrappers. Invoke the helper directly for graph publication.

`push.py` adds modified tracked files to the index with `git add -u`. New files stay out of the index unless you name them. This keeps unrelated files out of the PR. Use `--add <path>` for each new file in the PR. Do not add new files to the index with a broad `git add` command.

Use one `--add` flag for each file. Give one path with each flag. Do not use a space-separated expansion such as `--add $FILES`. The flag reads only the first token as the path. The script misreads the other tokens as arguments without a warning. The next token becomes part of the commit message.

Name individual files. Do not use directories or globs. A directory adds all its contents to the index and can add files you do not own.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/push.py" "$ARGUMENTS" --add path/to/newfile --add path/to/another
```

The script handles:
1. Add modified tracked files and the files you name with `--add <path>` to the index.
2. Commit with the given message or a generated message.
3. Push the branch to the `origin` remote.
4. Open or update the PR.

## JIRA Auto-Resolve

After the PR opens, check for a linked JIRA ticket and resolve it:

```bash
BRANCH=$(git branch --show-current)
JIRA_KEY=$(git config branch.$BRANCH.jira-ticket 2>/dev/null)
```

If `JIRA_KEY` is set, use the available Jira MCP to set the ticket status to **Resolved**:
Read `config.jira.mcp_namespace` from the project config. Use `jira` if the value is unset or the config is `NO_CONFIG`.

Use `mcp__<mcp_namespace>__transition_jira_status_by_name` with `{issueIdOrKey: JIRA_KEY, statusName: "<config.jira.transitions.resolve>", comment: "..."}`.

A non-default namespace uses the standard permission system. It can show a one-time prompt or use a `mcp__<mcp_namespace>__*` rule in `settings.json` `permissions.allow`. See INSTALLATION.md.

Then:
1. Use comment text: `"Resolved via PR merge. Work implemented via AI-assisted development (Claude Code). Branch: $BRANCH."`
2. Report the resolved ticket key alongside the PR URL

If `JIRA_KEY` is empty, skip silently — not all branches have tickets.

Report the PR URL (and resolved JIRA key if applicable) when complete.
