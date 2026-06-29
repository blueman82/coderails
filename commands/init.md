---
allowed-tools: Bash(git rev-parse*), Bash(basename*), Bash(ls*), Write
argument-hint: [project-name]
description: Scaffold a workflow.config.yaml for the current project
---

## Purpose

Create `workflow.config.yaml` in the current project directory. This file is read by `/coderails:prep`, `/coderails:workflow`, and `/coderails:push` to avoid hardcoded project-specific values.

## Steps

1. Determine the git root: `git rev-parse --show-toplevel`
2. Determine the project name: use `$ARGUMENTS` if provided, otherwise `basename $(pwd)`
3. Determine the config path: `$(pwd)/.claude/workflow.config.yaml` (create `.claude/` if needed). The workflow commands resolve config by walking up from the current directory to the git root — the first `.claude/workflow.config.yaml` found wins (see "Config resolution" in `AGENTS.md`). Run `/init` from the directory whose config you want to set: a project subdir in a monorepo, or the git root for a standalone repo.
4. Check if that file already exists. If it does, confirm before overwriting.

5. Ask the user for each field (one prompt is fine — list all fields at once):
   - **Jira project key** (e.g. `MYPROJ`) — or "none"
   - **Jira epic key** (e.g. `MYPROJ-100`) — or "none"
   - **Jira component name** (e.g. `MyComponent`) — or "none"
   - **Jira component ID** (numeric, from Jira URL) — or "none"
   - **Jira epic field ID** (custom field for epic link, e.g. `customfield_12345`) — or blank
   - **Jira story points field ID** (e.g. `customfield_67890`) — or blank
   - **Jira fix version name** (e.g. `v1.0`) — or blank
   - **Jira start transition name** (moves ticket in-progress, e.g. `"In Progress"`) — or blank
   - **Jira resolve transition name** (on PR merge, e.g. `"Resolved"`) — or blank
   - **Jira MCP tool namespace** (the `<ns>` between `mcp__` and `__` in your Jira MCP's tool names, e.g. `jira`, `acme-jira`, `atlassian`) — default: `jira`. Only relevant if Jira is configured.
   - **Wiki path** (relative to project dir, e.g. `../my-project-wiki`) — or "none"
   - **Worktree base path** — where sibling worktrees will be created. Default: parent directory of the git root (i.e. `dirname $(git rev-parse --show-toplevel)`). Show the resolved default to the user so they can confirm or override.
   - **Worktree script** (path from project root, e.g. `./worktree-add`) — or "none"
   - **Engineering-principles paths** (comma-separated glob patterns, e.g. `**/container.py,**/typed_di/**`) — or "none"
   - **Engineering-principles skill** (the slash-command to run, e.g. `/engineering-principles-python`, `/engineering-principles-go`, `/engineering-principles-ts`) — detect a sensible default: look for `go.mod` → `/engineering-principles-go`, `package.json` with `.ts` files → `/engineering-principles-ts`, otherwise `/engineering-principles-python`. Ask and let the user override. Answer "none" to disable engineering-principles entirely.

6. Write `workflow.config.yaml` at the resolved config path from step 3 with the collected values. Use `null` for any field answered "none".

Example output:
```yaml
project: my-project
wiki_path: ../my-project-wiki    # or null
worktree_base: /Users/john/Downloads  # parent dir of git root, or whatever the user specified
worktree_script: ./worktree-add   # or null
jira:
  project: MYPROJ
  epic: MYPROJ-100
  component_name: MyComponent
  component_id: "123456"
  epic_field: ""      # Jira custom field id for epic link (e.g. customfield_12345). Blank => skip.
  points_field: ""    # Jira custom field id for story points (e.g. customfield_67890). Blank => skip.
  fix_version: ""     # Jira fix version name (e.g. v1.0). Blank => skip.
  mcp_namespace: "jira"   # the <ns> in mcp__<ns>__create_jira_issue — set to match your Jira MCP server
  transitions:
    start: ""         # transition to move in-progress (e.g. "In Progress"). Blank => skip.
    resolve: ""       # transition on PR merge (e.g. "Resolved"). Blank => skip.
# or: jira: null
engineering_principles_paths:
  - "**/container.py"
# or: engineering_principles_paths: null
engineering_principles_skill: "/engineering-principles-python"   # nil = skip engineering-principles entirely; /engineering-principles-go, /engineering-principles-ts also supported
```

7. Report the path written and remind the user to commit it.

8. If `config.jira.mcp_namespace` was set to anything other than the default `jira`, tell the user:

   > Your Jira MCP namespace is `<mcp_namespace>`. The `allowed-tools` frontmatter in the workflow commands pre-authorises `mcp__jira__*` for the default namespace; calls to `mcp__<mcp_namespace>__*` will still work but will fall through to the normal permission system (one-time prompt or auto-allowed by a `settings.json` rule).
   >
   > To silence the permission prompt, add this line to `.claude/settings.json` under `permissions.allow`:
   >
   > ```json
   > "mcp__<mcp_namespace>__*"
   > ```
   >
   > See INSTALLATION.md for details.
