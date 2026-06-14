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
3. Determine the config path:
   - If `<git-root>/projects/` exists **AND** `<git-root>/projects/<project-name>/` exists → monorepo layout → write to `<git-root>/projects/<project-name>/.claude/workflow.config.yaml` (create `.claude/` if needed)
   - Otherwise → standalone repo → write to `<git-root>/.claude/workflow.config.yaml` (create `.claude/` if needed)
4. Check if that file already exists. If it does, confirm before overwriting.

5. Ask the user for each field (one prompt is fine — list all fields at once):
   - **Jira project key** (e.g. `MYPROJ`) — or "none"
   - **Jira epic key** (e.g. `MYPROJ-100`) — or "none"
   - **Jira component name** (e.g. `MyComponent`) — or "none"
   - **Jira component ID** (numeric, from Jira URL) — or "none"
   - **Wiki path** (relative to project dir, e.g. `../my-project-wiki`) — or "none"
   - **Worktree base path** — where sibling worktrees will be created. Default: parent directory of the git root (i.e. `dirname $(git rev-parse --show-toplevel)`). Show the resolved default to the user so they can confirm or override.
   - **Worktree script** (path from project root, e.g. `./worktree-add`) — or "none"
   - **Strictcode paths** (comma-separated glob patterns, e.g. `**/container.py,**/typed_di/**`) — or "none"

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
# or: jira: null
strictcode_paths:
  - "**/container.py"
# or: strictcode_paths: null
```

7. Report the path written and remind the user to commit it.
