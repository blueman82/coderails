---
allowed-tools: Bash(git rev-parse*), Bash(basename*), Bash(ls*), Bash(cmp*), Bash(ruby*), Bash(osascript*), Write
argument-hint: [project-name]
description: Scaffold a workflow.config.yaml for the current project
---

## Purpose

Make the provider-neutral `.coderails/workflow.config.yaml` in the current project directory. `/coderails:prep`, `/coderails:workflow`, and `/coderails:push` read this shared file for project settings.

## Steps

1. Find the Git root with `git rev-parse --show-toplevel`.
2. Use `$ARGUMENTS` as the project name if it contains a name. If it is empty, use `basename $(pwd)`.
3. Set the config path to `$(pwd)/.coderails/workflow.config.yaml`. Make `.coderails/` if necessary.
   Workflow commands search from the current directory to the Git root. They use the first `.coderails/workflow.config.yaml` they find. See "Config resolution" in `AGENTS.md`.
   Run `/init` in the directory you want to configure. Use a project subdirectory in a monorepo. Use the git root in a standalone repo.
4. Before migration, check that each provider the user will use has the upgrade and has reloaded. Each must read `.coderails/workflow.config.yaml`. Stop and report a provider that cannot read it. Do not invoke or reload a different provider.
5. Check the target and the two legacy paths in this directory: `.claude/workflow.config.yaml` and `.codex/workflow.config.yaml`.
   - If the two legacy files exist, compare them byte-for-byte with `cmp -s`. If their bytes are different, stop before you write. Get the user to reconcile them. Do not select one silently.
   - If only one legacy file exists or the two files match, read one. Write its full contents unchanged to the canonical target. Keep all fields and values, such as unknown fields and `sandbox_workers`. Do not prompt again for field values.
   - If the canonical target exists, get user approval before you replace it.
   - If no legacy file exists, continue with the field collection below.

6. Get these field values from the user. You can use one prompt for all fields:
   - **Jira project key** (e.g. `MYPROJ`) — or "none"
   - **Jira epic key** (e.g. `MYPROJ-100`) — or "none"
   - **Jira component name** (e.g. `MyComponent`) — or "none"
   - **Jira component ID** (numeric, from Jira URL) — or "none"
   - **Jira epic field ID** (custom field for epic link, e.g. `customfield_12345`) — or blank
   - **Jira story points field ID** (e.g. `customfield_67890`) — or blank
   - **Jira fix version name** (e.g. `v1.0`) — or blank
   - **Name of Jira status change at start** (e.g. `"In Progress"`) — or blank
   - **Name of Jira status change on PR merge** (e.g. `"Resolved"`) — or blank
   - **Jira MCP tool namespace**: the `<ns>` between `mcp__` and `__` in Jira tool names. Examples are `jira`, `acme-jira`, and `atlassian`. Use `jira` by default. Applies only if Jira has a configuration.
   - **Wiki path** (relative to project dir, e.g. `../my-project-wiki`) — or "none"
   - **Wiki supervision mode** (`discuss` or `autonomous`) — default: `discuss`. See the `wiki-ingest` skill for what each mode does.
   - **Wiki git worktree flow**: `true` uses PR flow. `false` writes and commits directly to the vault. Default: `true`. Applies only if a wiki path is set.
   - **Wiki git bypass flag**: environment flag for the wiki's own PRs, such as `BYPASS_REVIEW=1`, or "none". Set it for PR creation and merge. Applies only if wiki git worktree flow is `true`.
   - **Wiki git pull path**: source repository for `git pull` after a wiki PR merges, or "none". Applies only if wiki git worktree flow is `true`.
   - **Worktree base path**: the base path for sibling worktrees. The default is the parent of the Git root, from `dirname $(git rev-parse --show-toplevel)`. Show the computed default for the user to accept or override.
   - **Worktree script** (path from project root, e.g. `./worktree-add`) — or "none"
   - **Engineering-principles paths** (comma-separated glob patterns, e.g. `**/container.py,**/typed_di/**`) — or "none"
   - **Engineering-principles skill**: the slash command to run. Use `/engineering-principles-go` if the project has `go.mod`. Use `/engineering-principles-ts` if it has `package.json` and `.ts` files. If it has `.sh` files but no `go.mod` or `package.json`, use `/engineering-principles-bash`. An example is a shell-only `bin/` and `scripts/` layout. In other projects use `/engineering-principles-python`. Get the user's selection and permit an override. Use "none" to disable engineering-principles.
   - **Sandbox workers**: `@anthropic-ai/sandbox-runtime` runs agentic-loop implementation-unit workers in their own OS sandboxes. This replaces in-process `Agent` calls. The OS limits writes independently of the agent's trust domain. Use node/npx with macOS Seatbelt or Linux/WSL2 bubblewrap. Use `false` by default or omit the field for the same effect. Status `read_by_prose_only` in `config.schema.json` means only the agentic-loop skill reads this setting from resolve-config text.
   - **Integrity check for local merge**: Set `true` only after the GitHub workflow and server rule are active. The check needs a status for the current head from `github-actions[bot]`. Default: `false`. GitHub supplies the workflow token.

7. Write `workflow.config.yaml` at the path from step 3. Use `null` for each field answered "none". Validate the file with Ruby's standard YAML parser: `ruby -e 'require "yaml"; YAML.safe_load(File.read(ARGV.fetch(0)), permitted_classes: [], aliases: false)' <path>`. If writing or validation does not succeed, stop and report the problem. Keep all legacy files unchanged.

Example output:
```yaml
project: my-project
wiki_path: ../my-project-wiki    # or null
wiki_supervision: discuss   # or "autonomous" — see wiki-ingest skill
wiki_git_worktree: true   # With worktrees, use PRs for wiki commits. Without them, write directly.
wiki_git_bypass_flag: null   # e.g. "BYPASS_REVIEW=1" — env var for the wiki's own PR create/merge
wiki_git_pull_path: null   # e.g. /path/to/source-repo — pulled after a wiki PR merges
worktree_base: /Users/john/Downloads  # parent dir of git root, or whatever the user specified
worktree_script: ./worktree-add   # or null
jira:
  project: MYPROJ
  epic: MYPROJ-100
  component_name: MyComponent
  component_id: "123456"
  epic_field: ""      # Jira custom field ID for epic link, e.g. customfield_12345. Skip if empty.
  points_field: ""    # Jira custom field ID for story points, e.g. customfield_67890. Skip if empty.
  fix_version: ""     # Jira fix version name, e.g. v1.0. Skip if empty.
  mcp_namespace: "jira"   # Use the Jira MCP server namespace for <ns> in mcp__<ns>__create_jira_issue.
  transitions:
    start: ""         # Status change at start, e.g. "In Progress". Skip if empty.
    resolve: ""       # Status change on PR merge, e.g. "Resolved". Skip if empty.
# or: jira: null
engineering_principles_paths:
  - "**/container.py"
# or: engineering_principles_paths: null
engineering_principles_skill: "/engineering-principles-python"   # Use nil to skip. Other options are /engineering-principles-go, /engineering-principles-ts, and /engineering-principles-bash.
sandbox_workers: true    # Default ON. Contained worker dispatch needs npx and an OS that can run the sandbox.
action_authority: enforce  # Default uses signed owner receipts. Advisory warns. Off disables this gate.
integrity_review:
  enabled: false   # Turn on local status checks after the GitHub ruleset for the workflow is live.
```

8. After the canonical file validates, move each legacy file from step 5 to the macOS Trash. Use Finder through `osascript`. Move one file at a time.
   After each move, check that the legacy path is no longer there. If a move or check does not succeed, stop immediately.

   Report the file with the problem and the files you moved to Trash. Do not move the remaining files. Do not remove a legacy file directly. The files in Trash are recoverable. The moves are not atomic.

9. Report the written path and list the legacy files that moved to Trash. Remind the user to commit the canonical file.

10. If `config.jira.mcp_namespace` was set to anything other than the default `jira`, tell the user:

   > Your Jira MCP namespace is `<mcp_namespace>`. The `allowed-tools` frontmatter pre-authorises `mcp__jira__*` for the default namespace. Tools named `mcp__<mcp_namespace>__*` use the standard permission system.

   > The system prompts one time or uses a `settings.json` rule. To skip the prompt, add this rule to `permissions.allow` in `.claude/settings.json`:
   > ```json
   > "mcp__<mcp_namespace>__*"
   > ```

   > See INSTALLATION.md for more information.
