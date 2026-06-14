---
allowed-tools: Bash(./worktree-add*), Bash(git branch*), Bash(git status*), Bash(git config*), Bash(git worktree*), Bash(cat*), mcp__jira__search_jira_issues, mcp__jira__create_jira_issue, mcp__jira__transition_jira_status_by_name (update these to match your Jira MCP server's tool namespace)
argument-hint: <branch> [--type TYPE] [--summary "..."] [--description "..."]
description: Create safety branch, new feature/bug branch, and create a Jira ticket
---

## Project config

Config: !`GIT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null) && { cat "$GIT_ROOT/projects/$(basename $(pwd))/.claude/workflow.config.yaml" 2>/dev/null || cat "$GIT_ROOT/.claude/workflow.config.yaml" 2>/dev/null || echo "NO_CONFIG"; }`

If the config block above says `NO_CONFIG`, do NOT stop. Run in minimal mode with these defaults:
- `config.jira` = null → skip all Jira steps (Task Part 2)
- `config.wiki_path` = null → skip wiki phases
- `config.worktree_base` = `<git-root>` (the repo root from `git rev-parse --show-toplevel`)
- `config.worktree_script` = null → use plain `git worktree add`
- `config.strictcode_paths` = null → skip strictcode pre-flight

## Current Git Status

- Current branch: !`git branch --show-current`
- Git status: !`git status --short`

## Raw arguments

```
$ARGUMENTS
```

## Parse Arguments

The raw args block above is whatever the user typed after `/prep`. **Parse it yourself** — do NOT rely on positional `$1`/`$2` substitution, which does a naive whitespace-split that does not honour quotes and breaks on tokens containing `/`, `:`, or spaces.

Extract four fields from `$ARGUMENTS`:

1. **Branch name** (required). The first whitespace-separated token that starts with `feature/`, `bug/`, or `bugfix/`. If no such token exists, ask the user for the branch name before doing anything else.

2. **Issue Type** (optional). Look for `--type X` / `--issuetype X` flag OR the literal word `Task`/`Bug` after the branch name. If neither present, infer:
   - `feature/*` → `Task`
   - `bug/*` / `bugfix/*` → `Bug`

3. **Summary** (optional). Look for `--summary "..."` flag (handle both double and single quotes; take everything up to the matching close-quote). If a flag-quoted summary isn't present, generate one by humanising the branch name (e.g. `feature/user-auth` → "Implement user auth").

4. **Description** (optional). Look for `--description "..."` or `--desc "..."`. If absent, generate one from the branch name and issue type. Always include `Branch: <branch>` in the final description body.

### Accepted input shapes

All of these must work:

```
/prep feature/foo-bar
/prep bug/fix-timeout --summary "Request timeout too short"
/prep feature/add-retry-logic Task "Add retry logic" "Implement exponential back-off..."
/prep feature/add-retry-logic --type Task --summary "Add retry logic" --description "Implement exponential back-off..."
```

If the user's args don't match any of these shapes but the intent is clear, best-effort parse and proceed. If the intent is ambiguous, ask one targeted clarifying question — don't guess the branch name.

## Task Part 1: Worktree Creation

Feature and bug work must be isolated in a git worktree — never branch off or edit on main.

1. Derive the worktree path from the branch description:
   - Strip the `feature/`, `bug/`, or `bugfix/` prefix from the parsed branch name
   - Path: `<config.worktree_base>-<description>`
   - Example: `bug/fix-timeout` with `worktree_base: /Users/you/Documents/Github/my-project` → `/Users/you/Documents/Github/my-project-fix-timeout`
   - In minimal mode (NO_CONFIG), `worktree_base` is the git root, so the worktree is a sibling dir, e.g. `/path/to/repo` → `/path/to/repo-fix-timeout`.

2. Create the worktree:
   - If `config.worktree_script` is non-null, run from the project root:
     ```bash
     <config.worktree_script> <derived-path> <branch-name>
     ```
   - If `config.worktree_script` is null, use plain git:
     ```bash
     git worktree add <derived-path> -b <branch-name>
     ```

3. Report the worktree path to the user so they can point their editor at it.

## Task Part 2: Jira Ticket Creation

**Skip this entire section if `config.jira` is null.**

**How to reach Jira:** Call whichever Jira MCP tool you have available (the default expected tool name is `mcp__jira__create_jira_issue` — update `allowed-tools` in the frontmatter if your server uses a different namespace). If no Jira MCP is available, stop and tell the user Jira features need a Jira MCP server configured; the branches are already created, so this is non-fatal.

After successfully creating the branches, create a Jira ticket:

1. Create the ticket with these exact settings:
   - **Project key**: `config.jira.project`
   - **Issue type**: parsed or inferred type
   - **Summary**: parsed or generated summary
   - **Assignee**: the currently authenticated Jira user (use `get_current_user` or equivalent; do not hardcode)
   - **Description**: parsed or generated description (always include `Branch: <branch>`)
   - **Epic link**: Set `config.jira.epic_field` (e.g. `customfield_12345` — set for your project) to `config.jira.epic` (only if both are non-null)
   - **Component**: Set to `config.jira.component_name` (id: `config.jira.component_id`) — only if both component_name and component_id are non-null

2. Use the update parameter for these fields:
   - **Fix Version** (only if `config.jira.fix_version` is non-null): `{"fixVersions": [{"set": [{"name": "<config.jira.fix_version>"}]}]}`
   - **Story points** (only if `config.jira.points_field` is non-null): `{"<config.jira.points_field>": [{"set": 1}]}`  (e.g. `customfield_67890` — set for your project)

3. After successful creation, advance the ticket out of its initial state:
   - Transition to `config.jira.transitions.start` (e.g. `"In Progress"` — set for your project in workflow.config.yaml) using `transition_jira_status_by_name`. Run `get_jira_transitions` on one of your project's issues to find the correct name. If `config.jira.transitions.start` is null, skip this step.
   - **Then** attempt `config.jira.transitions.resolve` the same way, but treat a failure as non-fatal — not every project workflow exposes this transition from the start state. If it fails (or if the field is null), leave the ticket at the start state and continue; do not abort `/prep`.

4. Store the ticket key in git branch config for auto-resolve at push time:
   ```bash
   git config branch.<branch-name>.jira-ticket <KEY>
   ```

## Important Notes
- Git operations are performed first to ensure workspace safety
- Jira ticket creation follows only after successful branch creation
- Story points and fixVersions must use update parameter with "set" operation
- If Jira creation fails, the Git branches are already created and safe
- The stored git config key enables /push to auto-resolve the ticket on PR creation

Report both the branch creation and Jira ticket key (if created) to the user after completion.