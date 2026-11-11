---
name: init
description: Create or update a Coderails workflow configuration for the current Codex project or monorepo directory.
---

# Initialize Coderails

Make the provider-neutral `.coderails/workflow.config.yaml` for the current project. The Codex plugin owns this init flow.
It does not invoke the Claude plugin.

## Locate the configuration

1. Run `git rev-parse --show-toplevel` to find the repository root.
2. Use the current directory as the configuration scope. This allows a monorepo subdirectory to have its own settings.
3. Set the target to `<current-directory>/.coderails/workflow.config.yaml`.
4. Before migration, check each provider the user will continue to use.
   Its upgraded and reloaded version must read `.coderails/workflow.config.yaml`.
   If a provider does not satisfy this condition, stop and name it.
   Do not invoke or reload other providers.

5. Examine `<current-directory>/.claude/workflow.config.yaml` and `<current-directory>/.codex/workflow.config.yaml` as legacy inputs.
   - If the two files exist, compare them byte-for-byte with `cmp -s`.
     If they are different, stop before writing and tell the user to reconcile them. Do not silently select one.
   - If there is one legacy file or the files are the same, read one.
     Write its full contents unchanged to the canonical target.
     Do not collect replacement settings. Keep unknown fields and values, such as `sandbox_workers`.
   - If the canonical target exists, read it and get confirmation before replacing it.
     Keep it unless the user explicitly approves replacement.

6. If there is no legacy input, use the project name the user supplied.
   If the user did not supply a name, use the current directory's basename. Then collect settings below.

## Collect settings

Use `request_user_input` when available. Group related fields into a small number of questions and show defaults.
Accept `none` for optional values and write those values as YAML `null`.

Collect:

- Jira project key, epic key, component name and ID, epic-link field ID, story-points field ID, and fix-version name.
  Also collect the start and resolve status changes and the MCP namespace.
  Default the namespace to `jira`. If the project does not use Jira, set `jira` to `null`.

- Wiki path, supervision mode (`discuss` by default or `autonomous`), and git worktree flow (`true` by default).
  Also collect the git bypass environment assignment and git pull path.
  Set wiki-dependent fields to `null` if the config has no wiki path.

- Worktree base path. Default to the parent of the repository root and show the resolved path before accepting it.
- Worktree script path relative to the repository root, or `none`.

- Engineering-principles path globs and skill.
  Find a default from repository files. Use Go for `go.mod`. Use TypeScript for a `package.json` project containing TypeScript.
  Use Bash for a shell-only project. If none of those conditions apply, use Python.

  Use the installed native Coderails Codex skill name, such as `coderails-codex:engineering-principles-python`, without command syntax.
  Accept `none` to disable it.

- Sandbox workers. Default to `true` for Claude workers only. Codex workers rely on Codex's own `sandbox_mode`.
  A value of `false` switches it off. Keep this field unchanged during migration.

- `integrity_review.enabled`. Default to `false`. Set `true` after the GitHub ruleset for the integrity check is live.

## Write the file

Make `.coderails/` if needed and write YAML in this shape without comments:

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
sandbox_workers: true
action_authority: enforce
integrity_review:
  enabled: false
```

Use `jira: null`, `engineering_principles_paths: null`, or other `null` values where the user disabled an optional feature.

Validate the canonical file with Ruby's standard YAML parser (`ruby -e 'require "yaml"; YAML.safe_load(File.read(ARGV.fetch(0)), permitted_classes: [], aliases: false)' <path>`).
If the write or validation fails, stop and report the error. Keep each legacy file unchanged.

Only after validation succeeds, move each legacy file found above to the macOS Trash using Finder through `osascript`.
Move one file at a time and check that its source path no longer exists.

If a move or check fails, stop immediately. Name the file that caused the error and each file you moved.
Do not try to move the remaining files.
Do not remove a legacy file directly.
Files you moved stay in Trash, where the user can get them back. The moves are not atomic.

Report the path of the file you wrote and the legacy files you moved to Trash.
Tell the user to commit the config file.
