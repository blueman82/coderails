---
allowed-tools: Bash(./worktree-add*), Bash(git branch*), Bash(git status*), Bash(git config*), Bash(git worktree*), Bash(cat*), mcp__jira__search_jira_issues, mcp__jira__create_jira_issue, mcp__jira__transition_jira_status_by_name (zero-config default; for a different Jira MCP set config.jira.mcp_namespace in workflow.config.yaml — no edit here needed; see INSTALLATION.md)
argument-hint: <branch> [--type TYPE] [--summary "..."] [--description "..."]
description: Create safety branch, new feature/bug branch, and create a Jira ticket
---

## Project config

Config: !`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lib/config.py" resolve-config`

If the config block above says `NO_CONFIG`, do NOT stop. Run in minimal mode with these defaults:
- `config.jira` = null → skip all Jira steps (Task Part 2)
- `config.wiki_path` = null → skip wiki phases
- `config.worktree_base` = `<git-root>` (the repo root from `git rev-parse --show-toplevel`)
- `config.worktree_script` = null → use plain `git worktree add`
- `config.engineering_principles_paths` = null → skip engineering-principles pre-flight

## Current Git Status

- Current branch: !`git branch --show-current`
- Git status: !`git status --short`

## Raw arguments

```
$ARGUMENTS
```

## Parse Arguments

The raw arguments block contains what the user typed after `/prep`. Parse that block directly. Do not use positional `$1`/`$2` substitution. It uses whitespace as the delimiter and ignores quotes. It also breaks tokens that contain `/`, `:`, or spaces.

Read four fields from `$ARGUMENTS`:

1. Use the first whitespace-separated token that starts with `feature/`, `bug/`, or `bugfix/` as the required **Branch name**. If there is no such token, get the branch name from the user before you continue.

2. For the optional **Issue Type**, look for `--type X` or `--issuetype X`. You can also use the literal word `Task`/`Bug` after the branch name. If the input gives no type, infer it:
   - `feature/*` → `Task`
   - `bug/*` / `bugfix/*` → `Bug`

3. For the optional **Summary**, look for `--summary "..."`. Accept double or single quotes. Read all text up to the matching closing quote. If the flag has no quoted summary, convert the branch name to plain language. Example: `feature/user-auth` → "Implement user auth".

4. For the optional **Description**, look for `--description "..."` or `--desc "..."`. If there is no description, write one from the branch name and issue type. Always include `Branch: <branch>` in the description body.

### Accepted input shapes

All of these must work:

```
/prep feature/foo-bar
/prep bug/fix-timeout --summary "Request timeout too short"
/prep feature/add-retry-logic Task "Add retry logic" "Implement exponential back-off..."
/prep feature/add-retry-logic --type Task --summary "Add retry logic" --description "Implement exponential back-off..."
```

If the args have a different shape but the intent is clear, parse them and proceed. If the intent is unclear, ask one targeted question. Do not guess the branch name.

## Task Part 1: Worktree Creation

Use an isolated Git worktree for feature and bug work. Do not start a branch or edit files in the `main` checkout.

1. Derive the worktree path from the branch description:
   - Strip the `feature/`, `bug/`, or `bugfix/` prefix from the parsed branch name
   - Path: `<config.worktree_base>-<description>`
   - Example: `bug/fix-timeout` with `worktree_base: /Users/you/Documents/Github/my-project` → `/Users/you/Documents/Github/my-project-fix-timeout`
   - In minimal mode (NO_CONFIG), `worktree_base` is the git root, so the worktree is a sibling dir, e.g. `/path/to/repo` → `/path/to/repo-fix-timeout`.

2. Make the worktree:
   - If `config.worktree_script` is non-null, run from the project root:
     ```bash
     <config.worktree_script> <derived-path> <branch-name>
     ```
   - If `config.worktree_script` is null, use plain git:
     ```bash
     git worktree add <derived-path> -b <branch-name>
     ```

3. Report the worktree path to the user so they can point their editor at it.

## Task Part 1b: Progress Stub (best-effort, non-blocking)

After you make the worktree, you can initialize a current-schema `progress.json` if there is no file at the resolved path. Do not overwrite an active or completed loop. Keep ownership, graph data, the reviewer cache, and hook-owned fields. If initialization does not succeed, `/prep` continues. The graph has its own dispatch and end gates.

Run the path helper to resolve the path. Use its output. The helper reads the current working directory and `$CLAUDE_CODE_SESSION_ID` as path keys. Run it without arguments.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/lib/agentic_loop_path.py"
```

If no file exists at that path, put the user's `/prep` invocation verbatim in a temporary file. Run `python3 "${CLAUDE_PLUGIN_ROOT}/skills/agentic-loop/scripts/graph.py" start "$STATE" --session "$CLAUDE_CODE_SESSION_ID" --loop-id "<a unique non-blank id>" --prompt-file "$PROMPT_FILE"`. The `start` command writes the current graph schema atomically. It refuses to replace an unfinished loop and gives a `[reason_code=...]`. This keeps existing graph data as the agentic-loop workflow does. Do not hand-write `progress.json`.

If the path helper is unavailable or `start` does not succeed, give the user a warning and continue to Task Part 2. At this point the worktree and branches are safe.

## Task Part 2: Jira Ticket Creation

**Skip this section if `config.jira` is null.**

Read the Jira MCP tool namespace from `config.jira.mcp_namespace`. Use `jira` if the value is unset. Build the tool names at runtime:
- Open a ticket: `mcp__<mcp_namespace>__create_jira_issue`
- Change ticket status: `mcp__<mcp_namespace>__transition_jira_status_by_name`
- Find tickets: `mcp__<mcp_namespace>__search_jira_issues`

The `allowed-tools` frontmatter pre-authorises `mcp__jira__*` for the zero-config default. A different namespace uses the standard permission system. It can show a one-time prompt or use a `mcp__<mcp_namespace>__*` rule in `settings.json` `permissions.allow`. See INSTALLATION.md.

If no Jira MCP is available, skip the Jira steps. Tell the user that Jira functions need a configured Jira MCP server. The Git branches are safe and `/prep` can continue.

Open a Jira ticket only after the Git operations make the branches:

1. Use these settings for the ticket:
   - **Project key**: `config.jira.project`
   - **Issue type**: parsed or inferred type
   - **Summary**: parsed or generated summary
   - **Assignee**: use `get_current_user` or an equivalent tool to get the authenticated Jira user. Do not hardcode it.
   - **Description**: parsed or generated description (always include `Branch: <branch>`)
   - **Epic link**: If the two values are non-null, set `config.jira.epic_field` (e.g. `customfield_12345` for your project) to `config.jira.epic`.
   - **Component**: If the name and ID are non-null, use `config.jira.component_name` with ID `config.jira.component_id`.

2. Use the update parameter for these fields:
   - If `config.jira.fix_version` is non-null, set the Jira **Fix Version**: `{"fixVersions": [{"set": [{"name": "<config.jira.fix_version>"}]}]}`
   - **Story points** (only if `config.jira.points_field` is non-null): `{"<config.jira.points_field>": [{"set": 1}]}`  (e.g. `customfield_67890` — set for your project)

3. After Jira opens the ticket, change its status:
   - If `config.jira.transitions.start` is set, use `mcp__<mcp_namespace>__transition_jira_status_by_name` to set that status. An example is `"In Progress"` from workflow.config.yaml. Use `mcp__<mcp_namespace>__get_jira_transitions` on an issue in the project to find the correct name. Skip this step if the setting is null.
   - Then try `config.jira.transitions.resolve` with the same tool. Jira workflows can disallow this status change from the start status. If Jira rejects it or the setting is null, keep the ticket at its start status and continue `/prep`.

4. Record the ticket key in Git branch config so push can resolve it automatically:
   ```bash
   git config branch.<branch-name>.jira-ticket <KEY>
   ```

## Important Notes
- Run Git operations first to keep the workspace safe.
- Open the Jira ticket only if Git makes the branches.
- Story points and fixVersions must use update parameter with "set" operation
- If Jira cannot open a ticket, the Git branches are safe.
- The stored git config key enables /push to auto-resolve the ticket on PR creation

Report the branch and the Jira ticket key if Jira opened a ticket.
