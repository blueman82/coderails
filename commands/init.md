---
allowed-tools: Bash(git rev-parse*), Bash(basename*), Bash(ls*), Bash(cmp*), Bash(ruby*), Bash(osascript*), Write
argument-hint: [project-name]
description: Scaffold a workflow.config.yaml for the current project
---

## Purpose

Create the provider-neutral `.coderails/workflow.config.yaml` in the current project directory. This file is read by `/coderails:prep`, `/coderails:workflow`, and `/coderails:push` to avoid hardcoded project-specific values.

## Steps

1. Determine the git root: `git rev-parse --show-toplevel`
2. Determine the project name: use `$ARGUMENTS` if provided, otherwise `basename $(pwd)`
3. Determine the config path: `$(pwd)/.coderails/workflow.config.yaml` (create `.coderails/` if needed). The workflow commands resolve config by walking up from the current directory to the git root — the first `.coderails/workflow.config.yaml` found wins (see "Config resolution" in `AGENTS.md`). Run `/init` from the directory whose config you want to set: a project subdir in a monorepo, or the git root for a standalone repo.
4. Before migration, confirm that every provider the user will continue to use is upgraded and reloaded to a version that reads `.coderails/workflow.config.yaml`. If any is not, stop and report it. Do not call or reload another provider.
5. Check the target and both legacy paths in this same directory: `.claude/workflow.config.yaml` and `.codex/workflow.config.yaml`.
   - If both legacy files exist, compare them byte-for-byte with `cmp -s`. If they differ, stop before writing anything and ask the user to reconcile them. Never choose one silently.
   - If one legacy file exists, or both exist and match, migrate by reading that file and writing its complete contents unchanged to the canonical target. Do not prompt field-by-field: preserving unknown fields and values, including `sandbox_workers`, is required.
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
   - **Engineering-principles skill** (the slash-command to run, e.g. `/engineering-principles-python`, `/engineering-principles-go`, `/engineering-principles-ts`, `/engineering-principles-bash`) — detect a sensible default: look for `go.mod` → `/engineering-principles-go`, `package.json` with `.ts` files → `/engineering-principles-ts`, no `go.mod`/`package.json` but `.sh` files present (e.g. an all-shell `bin/`/`scripts/` layout) → `/engineering-principles-bash`, otherwise `/engineering-principles-python`. Ask and let the user override. Answer "none" to disable engineering-principles entirely.
   - **Sandbox workers** — dispatch agentic-loop implementation-unit workers as separate OS-sandboxed processes (`@anthropic-ai/sandbox-runtime`) instead of in-process `Agent` calls, for write containment outside the agent's trust domain. Requires node/npx and a supported platform (macOS Seatbelt, Linux/WSL2 bubblewrap). Default: `false` (or omit the field — same effect).
   - **Integrity machine user** (advanced, most projects should answer "none") — the GitHub login of a dedicated machine-user identity that posts SHA-bound `integrity-review` attestations. When set, `scripts/merge.sh` and the `enforce_pr_workflow` hook require a successful attestation from exactly this login. Default: `null` (or omit the field — same effect, check inactive).

7. Write `workflow.config.yaml` at the resolved config path from step 3 with the collected values. Use `null` for any field answered "none". Then validate the file with Ruby's standard YAML parser (`ruby -e 'require "yaml"; YAML.safe_load(File.read(ARGV.fetch(0)), permitted_classes: [], aliases: false)' <path>`). If the write or validation fails, stop. Leave every legacy file untouched and report the failure.

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
sandbox_workers: false   # true = agentic-loop dispatches implementation-unit workers via @anthropic-ai/sandbox-runtime (OS write containment); requires node/npx, macOS or Linux/WSL2
integrity_review:
  machine_user: null   # GitHub login of the integrity machine user; null/omitted = local gate inactive
```

8. After the canonical file validates, move each legacy file found in step 5 to the macOS Trash using Finder via `osascript`, one at a time. After each move, check that source path no longer exists. If a move or check fails, stop immediately: report the failed file and every file already moved, and do not attempt the remaining files. Never delete a legacy file directly. Files already moved remain recoverable in Trash; the moves are not atomic.

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
