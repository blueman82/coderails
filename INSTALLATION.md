# Installing coderails

This repository contains the Claude Code plugin at its root and the Codex plugin in `packages/codex/`.
Each plugin gives you workflow commands, planning skills, and discipline hooks.
`/push` and `/merge` use the GitHub CLI (`gh`).

## Requirements

- macOS.
- Python 3.9 or newer. The runtime uses only the standard library.
- For the default provider, use Claude Code 2.1.x. Step 3 needs 2.1.292 or newer. Update Claude Code first if necessary. Run the marketplace command in a terminal.
- For `--provider codex`, use the Codex CLI.
- Put `git` and `gh` on your PATH for workflow operations. The Claude installer checks them. The Python runtime does not use `jq`.
- Sign in with `gh auth login`. For GitHub Enterprise, use `gh auth login --hostname <your-git-host>` (for example, `git.example.com`).
- Install `pr-review-toolkit@claude-plugins-official` for the inspection step of `/workflow`.
- Install `superpowers@claude-plugins-official` for planning, TDD, systematic debugging, code inspection, and Git worktrees.

Jira is optional. Jira functions in `/prep`, `/workflow`, and `/push` need a Jira MCP server.
If you do not use Jira, set `jira: null` in `workflow.config.yaml`. `/prep` can make branches and `/push` can open PRs without Jira.

The commands get the tool names from `config.jira.mcp_namespace` in `workflow.config.yaml`.
The default namespace is `jira`, which gives `mcp__jira__*` names.
Set `mcp_namespace` to the namespace of your server, for example `acme-jira` or `atlassian`.
For a different namespace, add `"mcp__<namespace>__*"` to `permissions.allow` in `.claude/settings.json` to let the commands use the tools without a prompt.

## Choose the provider

The four steps below install Claude. For Codex, run these commands.

```bash
python3 install.py --provider codex --dry-run
python3 install.py --provider codex
```

The installer registers `coderails-codex@coderails` and installs the agent definitions in `${CODEX_HOME:-~/.codex}/agents`.
If an unmanaged agent uses the same name, the installer refuses the installation.
It keeps a copy before it changes a definition that it manages.
Start a new Codex session. Run `/hooks` and inspect and trust the Coderails hooks. Run `$coderails-codex:init` in each project.

The memory-target and integrity-gate installer flags apply only to Claude.
Each provider uses graph schema 3 and has its own dispatch, records, and locks.
The installer puts a copy of the shared graph semantics in each installation.
Use the Python commands below. Do not give schema 2 loop data to the graph helpers. The installer omits the retired `.sh` commands and schema 2 readers.

## Migrating from the old separate Claude plugins

If you installed `workflow-tools` or `claude-guardrails`, remove them in Claude Code first.
The `/plugin uninstall` command deregisters a plugin and removes its cache files.

```
/plugin uninstall workflow-tools
/plugin uninstall claude-guardrails
```

The installer checks `~/.claude/plugins/installed_plugins.json` for these plugins.
If it finds one, it gives the necessary `/plugin uninstall` command and stops without changes.
Run that command in Claude Code. Then run `install.py` again.
The installer removes the remaining `workflow-tools` and `claude-guardrails` keys from `settings.json` after uninstallation.

## Install (4 steps)

**1. Clone to a directory you will keep.** The installer records this path. Do not use a temporary directory.

```bash
git clone https://github.com/blueman82/coderails.git ~/Documents/Github/coderails
```

If you cannot clone, download a [release archive](https://github.com/blueman82/coderails/releases).
Use the ZIP archive that Git makes for a release tag. Unzip it to the same path.

```bash
unzip coderails.zip -d ~/Documents/Github/
```

**2. Run the installer.** Use the dry run to see the changes before you apply them.

```bash
cd ~/Documents/Github/coderails
python3 install.py --dry-run
python3 install.py
```

The installer does these steps before you open Claude Code.

- Checks `gh` and `git`.
- Adds the local marketplace with `extraKnownMarketplaces.coderails` in `~/.claude/settings.json`. This gives step 3 its directory source.
- Removes the `workflow-tools` and `claude-guardrails` entries from `settings.json` and the REPL's `known_marketplaces.json`. The uninstall command leaves these entries.
- Removes directories in `~/.claude/plugins/marketplaces/` only if they have an earlier plugin's marketplace name and contain no files. It keeps a copy of each file before it edits it.
- Adds the discipline rules to `~/.claude/CLAUDE.md`. A repeat run does not add the rules again.
- Adds four feedback memory entries. It does not overwrite entries.
- Sets Python file permissions from the Git index. It sets `+x` for executables in the Git index. Modules in the Git index for import stay non-executable. Untracked files get `+x`.

The installer also offers the integrity gate. It does not run `sudo`, read a token, or give an agent privileged access.
If you select this option, the installer gives you this command.

```bash
python3 scripts/integrity-gate/setup.py
```

The owner runs this command. The command uses the current `gh` login to check for an active `coderails-integrity-review` ruleset on `main`.
If it must make the ruleset, it waits for explicit approval first.
Then it prompts for the dedicated GitHub machine-user token. It installs the validator, which launchd runs as root.

To select the integrity-gate option without a prompt, use `python3 install.py --integrity-gate`.
To disable the prompt, use `python3 install.py --no-integrity-gate`.

**3. Install Coderails from the local marketplace in a terminal.** Use Claude Code 2.1.292 or newer.

```
claude plugin install coderails --marketplace ~/Documents/Github/coderails
```

Close and start Claude Code again and run these commands.

```
/plugin install pr-review-toolkit@claude-plugins-official
/plugin install superpowers@claude-plugins-official
/reload-plugins
```

The `--marketplace` option adds the local directory and installs Coderails in one command.
See the [Claude Code version requirement](https://code.claude.com/docs/en/plugins/cli-reference#plugin-install).
Use the path where you cloned this repository.

**4. Set up each project.** Run these commands one time in each repository.

```
/coderails:init               # scaffolds .coderails/workflow.config.yaml
/coderails:test-gate-setup     # optional — blocks commits when tests fail
```

Each provider keeps all output from each test command run in `~/.coderails/test-output/`.
To use a different log directory, set `CODERAILS_TEST_OUTPUT_DIR` in the hook environment.
One run can do many tests. If a run fails, the notice gives the log path, measurements, and the command to read the log.

The hooks rotate and compress logs from all completed runs.
The default budget for compressed logs is 1 GiB. Use `CODERAILS_TEST_LOG_BUDGET_BYTES` to change it.
The oldest completed logs expire first. The hooks keep logs from active runs and the latest completed runs. Those logs can go above the budget.

The hooks keep short measurement and expiry records in their own files. See the [retrieval examples and measurement limits](docs/REFERENCE.md#retained-test-gate-output).

`/coderails:init` writes `.coderails/workflow.config.yaml` in the current directory. If there is no earlier config, it writes new settings.
For migration, it keeps the earlier contents, schema, and values. It validates the new file before it moves the earlier files to the macOS Trash.
The runtime reads the new path only.

Check the result before you commit it as shared project config. Use `.claude/settings.local.json` for settings for one machine.

For the Coderails repository, activate the quality hook one time for each clone.

```
git config core.hooksPath scripts/git-hooks
```

See [docs/CODE-QUALITY.md](./docs/CODE-QUALITY.md) for the commands, necessary Python tools, test dependencies, and coverage limits.

## What you get

| Commands | Skills | Hooks |
|---|---|---|
| `/workflow` `/prep` `/push` `/merge` `/coderails:init` | Workflow and evals. `agentic-loop`, `task-evals` | Confidence labels at `Stop` |
| `/post-review` `/post-evals` | Planning. `planning-sequence`, `premortem`, `superpowers:brainstorming`, `superpowers:writing-plans` | `Did Not Verify` at `Stop` |
| `/assumptions` `/cite-check` `/notchecked` `/disconfirm` | Development. `superpowers:test-driven-development`, `superpowers:systematic-debugging`, `engineering-principles` (Go, Python, TypeScript, and Bash), `superpowers:verification-before-completion` | Destructive Bash gate at `PreToolUse` |
| `/test-gate-setup` | Multiple agents. `superpowers:dispatching-parallel-agents`, `superpowers:subagent-driven-development`, `superpowers:executing-plans`, `superpowers:finishing-a-development-branch` | Project test gate at `PreToolUse` |
| | Wiki. `wiki-init`, `wiki-query`, `wiki-ingest`, `wiki-lint` | |
| | PR checks and handoff. `superpowers:requesting-code-review`, `superpowers:receiving-code-review`, `handoff`, `improve-prompt`, `superpowers:using-git-worktrees`, `using-coderails`, `superpowers:writing-skills` | |

Coderails includes 25 skills. Run `ls skills/` in the plugin directory for the full list.
The required `superpowers@claude-plugins-official` plugin supplies the general development skills for planning, TDD, debugging, code inspection, and worktrees.

`/post-review` and `/post-evals` post PR comments with artifact summaries for the PR head SHA.
`task-evals` freezes the conditions for success at task intake, before implementation.
`/merge` checks the artifacts.

`inject_context` and `autonomous_gate` run at `UserPromptSubmit`.
If the raw prompt contains `autonomous`, `autonomous_gate` gives the `/coderails:authorise` command when no authority exists.
Only the typed `authority.py grant` command can give authority that expires and that the owner can revoke.
While that authority is live, `autonomous_gate` blocks the `AskUserQuestion` tool. The earlier prose gate no longer blocks text questions.

Claude has seven `Stop` hooks. The `loop_state_guard` and `loop_stall_guard` can block with exit 2.
`check_confidence_labels` and `check_verify_loop` give advice at `Stop` and `SubagentStop`.
`check_verify_loop` gives advice for untagged bullets. It also gives advice if a turn edits three files or more and omits `Did Not Verify`.
`voice_announce`, `unregistered_loop_guard`, and `offload_push_guard` do not block.

Ten `PreToolUse` hooks can block operations.

- The destructive Bash gate blocks destructive shell commands. The optional project test gate blocks commits if tests do not succeed.
- When config enables the PR workflow, `enforce_pr_workflow` checks the PR steps. For example, it can block a direct `git push` to `main` without a `/pr-review-toolkit:review-pr` invocation in the session.
- `no_edit_on_main` blocks source edits on `main`. It lets you edit documentation and config. For source edits, use `/coderails:prep` or a worktree.
  On all branches, it blocks edits to `.claude/settings.json` and `.claude/settings.local.json`.
- `comment_citation_gate` blocks new code comments that cite session artifacts, for example `E#:`, `Task A#`, or `CHANGE B#`. Give the constraint that the code checks. The hook does not check `.md` files.
- `wiki_taxonomy_gate` checks a wiki vault's top-level directory against the vault's `AGENTS.md` table, `## Page types`. It blocks unlisted locations. If it cannot determine the scope, it lets the write proceed.
- `verification_volume_ceiling` blocks the third and subsequent uses of `hooks/scripts/tests/run_all.py` or `scripts/post_evals.py validate-structure` for a work unit. The hook has no override.
- `loop_dispatch_guard` checks the graph schema, ownership envelope, and provider role for `Agent` calls. If the roster has work units, implementation needs owned frozen evals or correctly graded evals.
- `agent_only_gate` gives advice by default. If `AGENT_ONLY_GATE_ENFORCE=1`, it blocks the orchestrator's own tool calls that do the work.
- `autonomous_gate` blocks `AskUserQuestion` while the session has live autonomous authority. Continue in the approved scope. To revoke authority, run `python3 scripts/authority.py revoke --session <id>`.

## Notes

**Memory entries.** The installer gets the project memory directory from the current directory.
Run the installer from the project directory, or give `--memory-target /path/to/project/memory`.

**Prompt context.** Only Claude sees the `[ctx]` line. To check the hooks, use `/help` to find `/assumptions /cite-check /notchecked /disconfirm`.
After you send and receive prompts, check for entries in `~/.claude/discipline.log`.

**Jira fields.** Use `/coderails:init` to set `jira.epic_field` (for example, `customfield_12345`), `jira.points_field` (for example, `customfield_67890`), and `jira.fix_version` in `workflow.config.yaml`.
Set the Jira workflow step names for your project. `/prep` tries `config.jira.transitions.start` first, then `config.jira.transitions.resolve`.
If the resolve step does not succeed, the workflow continues. Run `get_jira_transitions` on one project issue to find the names.

**Jira tool namespace.** The default for `jira.mcp_namespace` is `jira`.
The commands build tool names such as `mcp__<mcp_namespace>__create_jira_issue` from the config at runtime.

Change the config to use a different server.
Claude reads the `allowed-tools` frontmatter before config substitution. It always lists the default `mcp__jira__*` tools.
For a different namespace, add `"mcp__<namespace>__*"` to `permissions.allow` in `.claude/settings.json` to let the tools run without a prompt.

**Trust for PR artifacts.** `/merge` accepts a comment only if the author's GitHub login matches the login that `gh` uses to merge.
That login must have `ADMIN`, `MAINTAIN`, or `WRITE` access to the current repository. The gate checks `viewerPermission`.
This rule applies to personal and organization repositories.

An earlier rule accepted only `OWNER` for `author_association`.
In an organization repository, the same user can have `MEMBER` or `COLLABORATOR` and the earlier rule refused their own comment.

If the login or permission check cannot run, the gate blocks the merge. If the login has only `READ` access, the gate finds no trusted comment.
A different login cannot supply the artifact.
A compromised login with write access can post an incorrect artifact. The gate checks who posted it.

## Uninstall Claude

```bash
python3 ~/Documents/Github/coderails/uninstall.py   # Removes the changes from CLAUDE.md and settings.
```

Then run this in Claude Code.

```
/plugin uninstall coderails
```

The uninstall keeps your `discipline.log` and memory entries.
