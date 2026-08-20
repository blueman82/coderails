---
name: init
description: Create or update a Coderails workflow configuration for the current Codex project or monorepo directory.
---

# Initialize Coderails

Create the provider-neutral `.coderails/workflow.config.yaml` for the current project. The Codex plugin owns this init flow; it does not call the Claude plugin.

## Locate the configuration

1. Run `git rev-parse --show-toplevel` to find the repository root.
2. Use the current directory as the configuration scope. This allows a monorepo subdirectory to have its own settings.
3. Set the target to `<current-directory>/.coderails/workflow.config.yaml`.
4. Before migration, confirm that every provider the user will continue to use is upgraded and reloaded to a version that reads `.coderails/workflow.config.yaml`. If any is not, stop and report it. Do not call or reload another provider.
5. Inspect `<current-directory>/.claude/workflow.config.yaml` and `<current-directory>/.codex/workflow.config.yaml` as legacy inputs.
   - If both exist, compare them byte-for-byte with `cmp -s`. If they differ, stop before writing anything and ask the user to reconcile them. Never choose one silently.
   - If one exists, or both exist and match, read one and write its complete contents unchanged to the canonical target. Do not collect replacement settings: unknown fields and values, including `sandbox_workers`, must survive migration.
   - If the canonical target exists, read it and ask for confirmation before replacing it. Preserve it unless replacement is explicitly approved.
6. When no legacy input exists, use the project name supplied in the user's request; otherwise use the current directory's basename, then collect settings below.

## Collect settings

Use `request_user_input` when available. Group related fields into a few clear rounds and show defaults. Accept `none` for optional values and write those values as YAML `null`.

Collect:

- Jira project key, epic key, component name, component ID, epic-link field ID, story-points field ID, fix-version name, start transition, resolve transition, and MCP namespace. Default the namespace to `jira`; set the whole `jira` value to `null` if Jira is not used.
- Wiki path, supervision mode (`discuss` by default or `autonomous`), git worktree flow (`true` by default), git bypass environment assignment, and git pull path. Set wiki-dependent fields to `null` when no wiki path is configured.
- Worktree base path. Default to the parent of the repository root and show the resolved path before accepting it.
- Worktree script path relative to the repository root, or `none`.
- Engineering-principles path globs and skill. Detect a default from repository files: Go for `go.mod`; TypeScript for a `package.json` project containing TypeScript; Bash for a shell-only project; otherwise Python. Use the installed native Coderails Codex skill name, such as `coderails-codex:engineering-principles-python`, without command syntax. Accept `none` to disable it.
- Sandbox workers. Default to `false`. Preserve this field exactly during migration.
- Integrity-review machine user. Default to `none`; this is only for a dedicated GitHub identity that posts SHA-bound `integrity-review` attestations.

## Write the file

Create `.coderails/` if needed and write valid YAML in this shape, omitting comments:

```yaml
project: my-project
wiki_path: ../my-project-wiki
wiki_supervision: discuss
wiki_git_worktree: true
wiki_git_bypass_flag: null
wiki_git_pull_path: null
worktree_base: /path/to/worktrees
worktree_script: null
jira:
  project: MYPROJ
  epic: MYPROJ-100
  component_name: MyComponent
  component_id: "123456"
  epic_field: ""
  points_field: ""
  fix_version: ""
  mcp_namespace: jira
  transitions:
    start: ""
    resolve: ""
engineering_principles_paths:
  - "**/container.py"
engineering_principles_skill: coderails-codex:engineering-principles-python
sandbox_workers: false
integrity_review:
  machine_user: null
```

Use `jira: null`, `engineering_principles_paths: null`, or other `null` values where the user disabled an optional feature.

Validate the canonical file with Ruby's standard YAML parser (`ruby -e 'require "yaml"; YAML.safe_load_file(ARGV.fetch(0), permitted_classes: [], aliases: false)' <path>`). If the write or validation fails, stop, leave every legacy file untouched, and report the failure.

Only after validation succeeds, move each legacy file found above to the macOS Trash using Finder via `osascript`, one at a time. After each move, check that source path no longer exists. If a move or check fails, stop immediately: report the failed file and every file already moved, and do not attempt the remaining files. Never delete a legacy file directly. Anything already moved remains recoverable in Trash; the moves are not atomic.

Report the exact file written, any legacy files moved to Trash, and remind the user to commit it.
