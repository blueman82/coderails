---
allowed-tools: Bash(git rev-parse*), Bash(basename*), Bash(ls*), Bash(cmp*), Bash(ruby*), Bash(osascript*), Write
argument-hint: [project-name]
description: Scaffold a workflow.config.yaml for the current project
---

## Purpose

Create `.coderails/workflow.config.yaml` in the current project directory. `/coderails:prep`, `/coderails:workflow`, and `/coderails:push` read this shared file for project settings.

## Steps

1. Determine the git root: `git rev-parse --show-toplevel`
2. Determine the project name: use `$ARGUMENTS` if provided, otherwise `basename $(pwd)`
3. Set the config path to `$(pwd)/.coderails/workflow.config.yaml`. Create `.coderails/` if needed.
   Workflow commands search upward to the git root. They use the first `.coderails/workflow.config.yaml` they find. See "Config resolution" in `AGENTS.md`.
   Run `/init` in the directory you want to configure. Use a project subdirectory in a monorepo. Use the git root in a standalone repo.
4. Before migration, confirm that every provider the user will continue to use has been upgraded and reloaded. Each must read `.coderails/workflow.config.yaml`. If any does not, stop and report it. Do not call or reload another provider.
5. Check the target and both legacy paths in this same directory: `.claude/workflow.config.yaml` and `.codex/workflow.config.yaml`.
   - If both legacy files exist, compare them byte-for-byte with `cmp -s`. If they differ, stop before writing anything and ask the user to reconcile them. Never choose one silently.
   - If one legacy file exists, or both exist and match, read one of them. Write its complete contents unchanged to the canonical target. Preserve all fields and values, including unknown fields and `sandbox_workers`. Do not ask for each field again.
   - If the canonical target already exists, confirm before replacing it.
   - If no legacy file exists, continue with the field collection below.

6. Ask the user for each field (one prompt is fine — list all fields at once):
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
   - **Wiki supervision mode** (`discuss` or `autonomous`) — default: `discuss`. See the `wiki-ingest` skill for what each mode does.
   - **Wiki git worktree flow** (`true` = PR flow, `false` = write and commit directly to the vault) — default: `true`. Only relevant if a wiki path is set.
   - **Wiki git bypass flag** (env var to set when creating/merging the wiki's own PRs, e.g. `BYPASS_REVIEW=1`) — or "none". Only relevant if wiki git worktree flow is `true`.
   - **Wiki git pull path** (a source repo to `git pull` after a wiki PR merges) — or "none". Only relevant if wiki git worktree flow is `true`.
   - **Worktree base path** — where sibling worktrees will be created. Default: parent directory of the git root (i.e. `dirname $(git rev-parse --show-toplevel)`). Show the resolved default to the user so they can confirm or override.
   - **Worktree script** (path from project root, e.g. `./worktree-add`) — or "none"
   - **Engineering-principles paths** (comma-separated glob patterns, e.g. `**/container.py,**/typed_di/**`) — or "none"
   - **Engineering-principles skill** — select the slash command from the project files:
     - `go.mod` → `/engineering-principles-go`
     - `package.json` with `.ts` files → `/engineering-principles-ts`
     - `.sh` files but no `go.mod` or `package.json` → `/engineering-principles-bash`
     - Otherwise → `/engineering-principles-python`
     Show the selected default and let the user change it. "None" disables engineering-principles.
   - **Sandbox workers** — run Claude implementation-unit workers in separate OS-sandboxed processes (`@anthropic-ai/sandbox-runtime`). This limits their writes. It requires node/npx and macOS Seatbelt or Linux/WSL2 bubblewrap. The default is `true`; omitting the field selects that default. The Claude graph dispatch and worker launcher read the value. Codex workers inherit the parent session sandbox; this field does not set a separate Codex worker sandbox.
   - **Integrity review local check** — choose `true` only after the GitHub Actions workflow and server rule are active. The check requires a current-head status from `github-actions[bot]`. Default: `false`. GitHub supplies the workflow token.

7. Write `workflow.config.yaml` at the path from step 3. Use `null` for each field answered "none". Validate the file with Ruby's standard YAML parser (`ruby -e 'require "yaml"; YAML.safe_load(File.read(ARGV.fetch(0)), permitted_classes: [], aliases: false)' <path>`). If writing or validation fails, stop. Leave every legacy file untouched and report the failure.

Example output:
```yaml
project: my-project
wiki_path: ../my-project-wiki    # or null
wiki_supervision: discuss   # or "autonomous" — see wiki-ingest skill
wiki_git_worktree: true   # true = PR flow for wiki commits, false = write directly
wiki_git_bypass_flag: null   # e.g. "BYPASS_REVIEW=1" — env var for the wiki's own PR create/merge
wiki_git_pull_path: null   # e.g. /path/to/source-repo — pulled after a wiki PR merges
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
engineering_principles_skill: "/engineering-principles-python"   # nil = skip engineering-principles entirely; /engineering-principles-go, /engineering-principles-ts, /engineering-principles-bash also supported
sandbox_workers: true    # default ON; requires npx and a supported OS for contained worker dispatch
action_authority: advisory  # shipped setting: warn without a receipt; omitted means off; enforce requires a signed receipt
integrity_review:
  enabled: false   # Turn on local status checks after the GitHub Actions ruleset is live
```

8. After validation, move each legacy file from step 5 to the macOS Trash. Use Finder through `osascript`. Move one file at a time.
   After each move, check that the old path is absent. If the move or check fails, stop. Report the failed file and the files already moved. Leave the remaining files in place.
   Never delete a legacy file directly. The files in Trash remain recoverable. The moves are not atomic.

9. Report the path written, any legacy files moved to Trash, and remind the user to commit the canonical file.

10. If `config.jira.mcp_namespace` was set to anything other than the default `jira`, tell the user:

   > Your Jira MCP namespace is `<mcp_namespace>`. The `allowed-tools` frontmatter in the workflow commands pre-authorises `mcp__jira__*` for the default namespace; calls to `mcp__<mcp_namespace>__*` will still work but will fall through to the normal permission system (one-time prompt or auto-allowed by a `settings.json` rule).
   >
   > To silence the permission prompt, add this line to `.claude/settings.json` under `permissions.allow`:
   >
   > ```json
   > "mcp__<mcp_namespace>__*"
   > ```
   >
   > See INSTALLATION.md for details.
