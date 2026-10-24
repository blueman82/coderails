# Installing coderails

This clone installs two independent plugins: Claude Code at the root and Codex
under `packages/codex/`. Both provide workflow commands, planning and
orchestration skills, and discipline hooks. `/push` and `/merge` use GitHub's
`gh` CLI.

## Requirements

- macOS
- Python 3.9 or newer; runtime code uses only the standard library
- Claude Code 2.1.x for the default provider, or the Codex CLI for `--provider codex`
- `git` and `gh` on your PATH for workflow operations (checked by the Claude installer); `jq` is not required by the Python runtime
- An authenticated GitHub CLI (`gh auth login`). For enterprise GitHub: `gh auth login --hostname <your-git-host>` (e.g. `git.example.com`)
- `pr-review-toolkit@claude-plugins-official` installed — required for the review stage of `/workflow`
- `superpowers@claude-plugins-official` installed — required for dev-workflow skills (planning, TDD, systematic debugging, code review, git worktrees)
- **For Jira features:** Connect a Jira MCP server under the configured
  namespace. `/prep`, `/workflow`, and `/push` can then resolve Jira work.
  Jira is optional. Leave `jira: null` in `workflow.config.yaml` when no
  server is configured. The commands use `config.jira.mcp_namespace` to
  build tool names. Its default is `jira`, which gives `mcp__jira__*`.
  Set `mcp_namespace` to your server name, such as `acme-jira` or
  `atlassian`. You do not need to edit the command files. For another
  namespace, allow `"mcp__<namespace>__*"` in `.claude/settings.json` under
  `permissions.allow`. This prevents a prompt for each call. Without Jira
  MCP, `/prep` still creates branches and `/push` still opens PRs. Their
  Jira ticket and resolve steps do nothing.

## Choose the provider

The four-step walkthrough below installs Claude. For Codex, complete the
clone in step 1. Then run these commands from the clone:

```bash
python3 install.py --provider codex --dry-run
python3 install.py --provider codex
```

This registers `coderails-codex@coderails`. It also installs native agent
definitions under `${CODEX_HOME:-~/.codex}/agents`. The installer refuses
unrelated agent-name collisions. It backs up managed definitions that change.
Start a fresh Codex session. Run `/hooks`, then review and trust the
Coderails hooks. Initialize each project with `$coderails-codex:init`.
The memory-target flag applies only to Claude. Both providers offer the
integrity-gate setup prompt.

Both providers use graph schema 3. Each handles its own dispatch, evidence,
and locks. The installer copies shared pure graph semantics into each plugin.
It does not install retired `.sh` entrypoints or schema-2 graph readers.
Use the current Python commands shown here. Do not give schema-2 loop state
to the current graph helpers.

## Migrating from the old separate Claude plugins

If you installed `workflow-tools` or `claude-guardrails` before, remove them
inside Claude Code. Only `/plugin uninstall` deregisters a plugin and clears
its cached files. The installer does not do this.

```
/plugin uninstall workflow-tools
/plugin uninstall claude-guardrails
```

The installer checks `~/.claude/plugins/installed_plugins.json` for these
plugins. If one remains, it prints the exact `/plugin uninstall` command.
It exits without changes. Uninstall that plugin in Claude Code, then run
`install.py` again. The installer then removes stale plugin keys from
`settings.json`.

## Install (4 steps)

**1. Clone somewhere stable.** The installer records the clone path.
Do not use a temporary directory that you plan to clear.

```bash
git clone https://github.com/blueman82/coderails.git ~/Documents/Github/coderails
```

Prefer `git clone`. You can instead download a
[tagged release archive](https://github.com/blueman82/coderails/releases).
Use its git-archive zip. Do not use an ad-hoc zip. Unzip it to the same path:

```bash
unzip coderails.zip -d ~/Documents/Github/
```

**2. Run the installer.** First do a dry run to see what it would change:

```bash
cd ~/Documents/Github/coderails
python3 install.py --dry-run
python3 install.py
```

It does everything that has to happen outside Claude Code:
- checks `gh` and `git`
- registers the plugin as a local marketplace in `~/.claude/settings.json`
  (`extraKnownMarketplaces.coderails`, directory source — this is what makes the
  next step resolve on 2.1.x)
- cleans up the old plugins' marketplace state, which `/plugin uninstall` leaves
  behind: it strips the `workflow-tools`/`claude-guardrails` keys from both
  `settings.json` and the REPL's `known_marketplaces.json`, and removes any empty
  leftover marketplace cache dirs under `~/.claude/plugins/marketplaces/` (it only
  touches dirs that are stale-named *and* contain no files — your real
  marketplaces are never at risk). Backups are written before each edit.
- appends the discipline rules to `~/.claude/CLAUDE.md` (idempotent)
- seeds four feedback memories (won't overwrite)
- aligns Python script permissions with their git index mode (tracked executables get `+x`, tracked import-only modules stay non-executable; untracked files default to `+x`)

The installer offers an optional integrity gate. It does not run `sudo`.
It does not read a token or give either provider privileged access.
If you select the gate, it prints a setup command. Replace `123` in this
example with your test PR number:

```bash
python3 scripts/integrity-gate/setup.py --candidate-pr 123 --apply
```

First, merge the trusted workflow and enable GitHub Actions. Allow its
events in the repository Actions policy. Use a test PR to confirm that the
workflow posts a passing and a failing `integrity-review` status.
The setup command checks the policy and the test PR's passing status.
It then creates the rule on `main` with your current `gh` login.
The workflow uses GitHub's built-in `GITHUB_TOKEN`. You need no machine-user
token, root-owned service, or sudo.

See [INTEGRITY-GATE.md](docs/INTEGRITY-GATE.md) for the full order and
migration steps. Run `python3 install.py --integrity-gate` to select the
setup prompt without interaction. Run `python3 install.py --no-integrity-gate`
to suppress that prompt.

**3. Restart Claude Code, then run in order:**

```
/plugin marketplace add ~/Documents/Github/coderails
/plugin install coderails@coderails
/plugin install pr-review-toolkit@claude-plugins-official
/plugin install superpowers@claude-plugins-official
/reload-plugins
```

The installer already wrote the settings entry. `marketplace add` therefore
resolves the local directory. Run `marketplace add` before `install`.

**4. Per project (run once per repo):**

```
/coderails:init               # scaffolds .coderails/workflow.config.yaml
/coderails:test-gate-setup     # optional — blocks commits when tests fail
```

Both providers retain complete output from each configured test-command run in
`~/.coderails/test-output/`; set `CODERAILS_TEST_OUTPUT_DIR` in the hook environment
to choose another storage root. One run may execute many tests. Failure notices
provide the log path, measurements and a reader command rather than a fixed
excerpt. Completed logs, including passing runs, rotate and compress
automatically. The default compressed-log budget is 1 GiB; override it with
`CODERAILS_TEST_LOG_BUDGET_BYTES`. Oldest completed logs expire first, while
active and just-completed runs are protected and may exceed the budget.
Compact measurement and expiry records persist separately. See [retrieval examples and delivery
measurement limits](docs/REFERENCE.md#retained-test-gate-output).

`/coderails:init` writes `.coderails/workflow.config.yaml` in the current
directory. It creates settings if no legacy config exists. During migration,
it preserves the legacy contents, schema, and values. It validates the new
file, then moves legacy files to the macOS Trash. Runtime reads do not use
legacy paths. Review the result before you commit it as shared project
config. It is not local machine config like `.claude/settings.local.json`.

For Coderails itself, activate the repository quality hook once per clone:

```
git config core.hooksPath scripts/git-hooks
```

See [docs/CODE-QUALITY.md](./docs/CODE-QUALITY.md) for the strict and warn-only
commands, required Python check tools, test-only dependencies, and coverage limits.

## What you get

| Commands | Skills | Hooks (automatic) |
|---|---|---|
| `/workflow` `/prep` `/push` `/merge` `/coderails:init` | **Workflow & evals:** agentic-loop, task-evals | confidence-label check (Stop) |
| `/post-review` `/post-evals` | **Planning:** planning-sequence, premortem, `superpowers:brainstorming`, `superpowers:writing-plans` | Did-Not-Verify check (Stop) |
| `/assumptions` `/cite-check` `/notchecked` `/disconfirm` | **Dev discipline:** `superpowers:test-driven-development`, `superpowers:systematic-debugging`, engineering-principles (+ go/python/ts/bash variants), `superpowers:verification-before-completion` | destructive-bash gate (PreToolUse) |
| `/test-gate-setup` | **Multi-agent:** `superpowers:dispatching-parallel-agents`, `superpowers:subagent-driven-development`, `superpowers:executing-plans`, `superpowers:finishing-a-development-branch` | project test gate (PreToolUse) |
| | **Wiki:** wiki-init, wiki-query, wiki-ingest, wiki-lint | |
| | **Review & handoff:** `superpowers:requesting-code-review`, `superpowers:receiving-code-review`, handoff, improve-prompt, `superpowers:using-git-worktrees`, using-coderails, `superpowers:writing-skills` | |

25 skills ship in total (`ls skills/` in the plugin dir to see the full list).
General dev-workflow skills — planning, TDD, debugging, code review,
worktrees — are provided by the required `superpowers@claude-plugins-official`
plugin, not bundled here.
`/post-review` and `/post-evals` post SHA-bound review/eval-artifact summaries
as durable PR comments; `task-evals` freezes a game-resistant success-eval set
at task intake and gates `/merge` on it.

Two UserPromptSubmit hooks run silently. `inject_context` adds context.
`crack_on_gate` grants an expiring, revocable authority object when the raw
prompt contains "crack on". Its AskUserQuestion gate blocks that tool while
the authority is live. It does not block prose questions. Revoke the grant
with `python3 scripts/authority.py revoke --session <id>`.

The loop-state and loop-stall Stop hooks can block. Confidence-label and
verify-loop checks only advise on Stop and SubagentStop. Verify-loop also
warns when a turn edits at least three files without a Did Not Verify
section. Other Stop hooks announce or nudge.

PreToolUse hooks enforce the PR workflow, source edit rules, test gate,
verification volume limit, and graph dispatch ownership where configured.
Other hooks check comments, wiki paths, reviewer tools, and action authority.
`agent_only_gate` nudges by default; `AGENT_ONLY_GATE_ENFORCE=1` makes it
block inline orchestrator work. Read the [hook event map](AGENTS.md#hook-event-map-hookshooksjson)
for the current matcher, mode, and limit of each hook.

## Notes

- **Memory seeds land in a per-project memory dir derived from your current
  directory.** If you want them in a specific project, run the installer from
  inside that project, or pass `--memory-target /path/to/project/memory`.
- **The `[ctx]` line** the discipline loop injects on each prompt is invisible to
  you — only Claude sees it. To confirm the loop is live: `/help` lists
  `/assumptions /cite-check /notchecked /disconfirm`, and `~/.claude/discipline.log`
  starts filling with entries after a few responses.
- **Configure `/prep`'s Jira fields for your project.** Use
  `/coderails:init` to set `jira.epic_field`, `jira.points_field`, and
  `jira.fix_version` in `workflow.config.yaml`. Examples of custom fields
  are `customfield_12345` and `customfield_67890`. Set the project's
  transition names too. `/prep` tries `config.jira.transitions.start`,
  then `config.jira.transitions.resolve`. A failed resolve transition does
  not stop the command. Run `get_jira_transitions` on a project issue to
  find the correct names.
- **`jira.mcp_namespace` selects the Jira MCP tool namespace.** The default
  is `jira`. Commands build names such as
  `mcp__<mcp_namespace>__create_jira_issue` at runtime. A different server
  needs a config change, not a command edit. For a custom namespace, add
  `"mcp__<namespace>__*"` to `.claude/settings.json` under
  `permissions.allow`. This avoids a prompt for each call. The
  `allowed-tools` frontmatter is parsed before config substitution. It
  always lists the default `mcp__jira__*` tools. The `permissions.allow`
  rule grants access to non-default namespaces on this machine.
- **`/merge` review and eval artifact trust rule:** The comment author must
  match the GitHub login used by `gh` for the merge. That login must have
  `ADMIN`, `MAINTAIN`, or `WRITE` access to this repo. The gate checks access
  through `viewerPermission`. It applies to personal and organization repos.

  The earlier rule also required `author_association: OWNER`. That rule
  blocked valid comments in organization repos. The same user's comments
  can have `MEMBER` or `COLLABORATOR` there. The login match still rejects
  comments from a different account, whatever access that account has.

  A failed identity or permission lookup blocks the merge. A `READ` result
  means no trusted comment was found; it is not a lookup failure. The gate
  establishes who posted the artifact marker. It cannot prove the content
  is true. A compromised account with write access can post a false marker.

## Uninstall Claude

```bash
python3 ~/Documents/Github/coderails/uninstall.py   # reverses CLAUDE.md + settings changes
```

then in Claude Code:

```
/plugin uninstall coderails
```

Your `discipline.log` and memory entries are preserved (your data).
