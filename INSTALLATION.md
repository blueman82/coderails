# Installing coderails

Two independent plugins are installed from this clone: Claude Code at the
root, and Codex under `packages/codex/`. Both provide workflow commands,
planning/orchestration skills, and discipline hooks. `/push` and `/merge`
invoke GitHub's `gh` CLI.

## Requirements

- macOS
- Python 3.9 or newer; runtime code uses only the standard library
- Claude Code 2.1.x for the default provider, or the Codex CLI for `--provider codex`
- `git` and `gh` on your PATH for workflow operations (checked by the Claude installer); `jq` is not required by the Python runtime
- An authenticated GitHub CLI (`gh auth login`). For enterprise GitHub: `gh auth login --hostname <your-git-host>` (e.g. `git.example.com`)
- `pr-review-toolkit@claude-plugins-official` installed — required for the review stage of `/workflow`
- `superpowers@claude-plugins-official` installed — required for dev-workflow skills (planning, TDD, systematic debugging, code review, git worktrees)
- **For Jira features** (`/prep`, `/workflow`, `/push` auto-resolve): a Jira MCP server, reachable via your configured MCP tool namespace. Jira is optional — leave `jira: null` in `workflow.config.yaml` unless you've configured a Jira MCP server. The commands build Jira tool names at runtime from `config.jira.mcp_namespace` in `workflow.config.yaml` (default: `jira`, giving `mcp__jira__*`). Set `mcp_namespace` to match your server (e.g. `acme-jira`, `atlassian`) — no edits to command files needed. For non-default namespaces, add a `permissions.allow` rule to `.claude/settings.json` so calls run without prompting: `"mcp__<namespace>__*"`. Without a Jira MCP, `/prep` still creates branches and `/push` still opens PRs — only the Jira ticket/resolve steps no-op.

## Choose the provider

The four-step walkthrough below installs Claude. For Codex, run:

```bash
python3 install.py --provider codex --dry-run
python3 install.py --provider codex
```

This registers `coderails-codex@coderails` and installs the bundled native
agent definitions under `${CODEX_HOME:-~/.codex}/agents`. It refuses unrelated
agent-name collisions and backs up changed managed definitions. Start a fresh
Codex session, run `/hooks`, and review and trust the Coderails hooks. Initialize
each project with `$coderails-codex:init`. The memory-target and integrity-gate
installer flags apply only to Claude.

Both providers use graph schema 3, with provider-local dispatch, evidence and
locks. The shared pure graph semantics are materialized into each installation.
Retired `.sh` entrypoints and schema-2 graph readers are not installed; invoke
the current Python commands shown here. Existing schema-2 loop state must not
be passed to the current graph helpers.

## Migrating from the old separate Claude plugins

If you previously installed `workflow-tools` and/or `claude-guardrails` as separate
plugins, remove them first — **inside Claude Code**, because only `/plugin uninstall`
deregisters a plugin and clears its cached files (the installer does not):

```
/plugin uninstall workflow-tools
/plugin uninstall claude-guardrails
```

The installer enforces this. On launch it scans `~/.claude/plugins/installed_plugins.json`
for either plugin; if it finds one still installed it prints the exact
`/plugin uninstall` command and exits without changing anything. Run the uninstall
in Claude Code, then re-run `install.py`. Once they're gone, the installer also
strips the stale `workflow-tools`/`claude-guardrails` keys from `settings.json` so
you don't have to touch it.

## Install (4 steps)

**1. Clone somewhere stable.** Where you clone is where it lives — the installer
records that path. Don't clone to a temp folder you'll clear.

```bash
git clone https://github.com/blueman82/coderails.git ~/Documents/Github/coderails
```

Prefer git clone. If you'd rather not clone, download a
[release archive](https://github.com/blueman82/coderails/releases) (a git-archive
zip of a tagged release, not an ad-hoc zip) and unzip it to the same path instead:

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

The installer also offers the optional integrity gate. It never runs `sudo`,
reads a token, or grants privileged access to Claude, Codex, or any other
agent. If you choose it, the installer prints one command for you to run
yourself:

```bash
python3 scripts/integrity-gate/setup.py
```

That owner-run helper first uses your current `gh` login to create or verify an
active `coderails-integrity-review` ruleset on `main`, with an explicit
confirmation before creation. It then prompts for the dedicated GitHub
machine-user token and installs the independent root-owned launchd validator.
To select the prompt non-interactively, use `python3 install.py --integrity-gate`;
to suppress it, use `python3 install.py --no-integrity-gate`.

**3. Restart Claude Code, then run in order:**

```
/plugin marketplace add ~/Documents/Github/coderails
/plugin install coderails@coderails
/plugin install pr-review-toolkit@claude-plugins-official
/plugin install superpowers@claude-plugins-official
/reload-plugins
```

The installer already wrote the settings entry, so `marketplace add` resolves the
local directory instead of trying to clone it as a git URL. `marketplace add` first,
then `install`.

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
directory. It scaffolds new settings when no legacy config exists. When migrating,
it preserves the legacy contents, schema, and values, validates the canonical
file, then moves the legacy files to the macOS Trash. Runtime reads do not fall
back to legacy paths. Review the result before committing it as shared project
config; it is not machine-local config like `.claude/settings.local.json`.

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

Two UserPromptSubmit hooks run silently: inject_context, and crack_on_gate (which
stamps a per-session flag when the raw prompt contains "crack on"). Eight Stop hooks
are registered; five of them block via exit 2: confidence-label check, verify-loop
check (both promoted from warn-mode on 2026-05-05), loop-state guard, loop-stall
guard, and crack_on_prose_gate (blocks a final message that asks the user a question in
prose while the crack-on flag is stamped — pattern-matching, so a question with
no interrogative marker, or any ask past its per-turn cap of 3, still gets
through). The other three (voice_announce, unregistered_loop_guard,
offload_push_guard) nudge only and never block. verify-loop
also blocks when a turn edits 3+ files and the response omits the
Did-Not-Verify section entirely (added 2026-07-13), not just on untagged
bullets. The same two
content-discipline checks (confidence-label and verify-loop) also run on
SubagentStop — so subagents are held to the same standards as the parent session.
On PreToolUse, ten hooks can block: the destructive-bash gate, the opt-in test
gate, the config-gated `enforce_pr_workflow` (opt-in via workflow.config.yaml,
like the test gate — enforces the PR chain, e.g. blocks a direct `git push` to
`main` unless `/pr-review-toolkit:review-pr` already ran this session),
`no_edit_on_main` (blocks editing source files, but not docs/config, while on
`main` — use `/coderails:prep` or a worktree instead; it also blocks editing
`.claude/settings.json`/`settings.local.json` on any branch),
`comment_citation_gate` (blocks new code comments that cite a session-artifact
label like `E#:`/`Task A#`/`CHANGE B#` instead of stating the constraint the
code enforces; `.md` files are exempt), `wiki_taxonomy_gate` (blocks a write into
an LLM wiki vault's top-level directory that isn't sanctioned by the vault's own
`AGENTS.md` "## Page types" table; fails open on any ambiguity),
`verification_volume_ceiling` (hard-blocks, with no override, the 3rd+
invocation per work-unit of `hooks/scripts/tests/run_all.py` or a
`scripts/post_evals.py` validate-structure ceremony), `loop_dispatch_guard` on `Agent` dispatches
(validates current graph schema, native ownership envelope and available provider role; nonempty work-unit rosters require owned frozen or valid graded evals before implementation), the
opt-in `agent_only_gate` (nudges by default; blocks the orchestrator's own
inline do-work tool calls only under `AGENT_ONLY_GATE_ENFORCE=1`), and
`crack_on_gate` on
`AskUserQuestion` (denies the tool while the session's crack-on flag is
stamped — proceed autonomously instead of asking).

## Notes

- **Memory seeds land in a per-project memory dir derived from your current
  directory.** If you want them in a specific project, run the installer from
  inside that project, or pass `--memory-target /path/to/project/memory`.
- **The `[ctx]` line** the discipline loop injects on each prompt is invisible to
  you — only Claude sees it. To confirm the loop is live: `/help` lists
  `/assumptions /cite-check /notchecked /disconfirm`, and `~/.claude/discipline.log`
  starts filling with entries after a few responses.
- **`/prep`'s Jira fields must be configured for your project.** Set `jira.epic_field` (e.g. `customfield_12345`), `jira.points_field` (e.g. `customfield_67890`), and `jira.fix_version` in `workflow.config.yaml` via `/coderails:init`. Transition names are also project-specific: `/prep` attempts `config.jira.transitions.start` then `config.jira.transitions.resolve`; the resolve transition failure is non-fatal. Run `get_jira_transitions` on one of your project's issues to find the correct names.
- **`jira.mcp_namespace`** sets the MCP tool namespace used by all Jira calls (default: `jira`). Commands build tool names like `mcp__<mcp_namespace>__create_jira_issue` at runtime, so pointing at a different Jira MCP server requires only a config change — not a command edit. If you use a non-default namespace, add `"mcp__<namespace>__*"` to `.claude/settings.json` under `permissions.allow` to avoid per-call permission prompts. Background: the `allowed-tools` frontmatter is parsed statically before config substitution runs, so it always lists the default `mcp__jira__*` tools; the `permissions.allow` rule is the machine-local home for granting non-default MCP namespaces.
- **`/merge`'s review/eval artifact gates trust rule:** artifact comments are trusted only from the merging identity, which must hold write access on the repo — identical on personal and org-owned repos. Concretely: a PR comment only counts as a coderails review/eval artifact if (a) its author's GitHub login matches the identity `gh` is authenticated as, AND (b) that identity holds write access or better (`ADMIN`/`MAINTAIN`/`WRITE`) on the current repo, checked via `viewerPermission`. This replaced an earlier rule that additionally required the comment's `author_association` to be `OWNER`, which failed closed on org-owned repos — the same authenticated user's own comments there carry `MEMBER`/`COLLABORATOR`, never `OWNER`. The login-match half of the check is unchanged and is the actual anti-spoof property: a different login can never pass regardless of permission level. If the permission lookup itself fails (network/auth), the gate fails closed (blocks the merge) the same way an identity-fetch failure does; insufficient permission (e.g. `READ`) is treated as "no trusted comment found," not a fetch failure. This does not change what the artifact comments assert — a compromised identity that holds write access can still post a false artifact; the gate proves *who* posted a marker, not that its contents are truthful.

## Uninstall Claude

```bash
python3 ~/Documents/Github/coderails/uninstall.py   # reverses CLAUDE.md + settings changes
```

then in Claude Code:

```
/plugin uninstall coderails
```

Your `discipline.log` and memory entries are preserved (your data).
