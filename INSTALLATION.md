# Installing coderails

A single Claude Code plugin shipped as a zip — no GitHub, no git remote needed.
It bundles the workflow command chain, the planning/orchestration skills, and a
self-checking discipline loop.

## Prerequisites

- Claude Code 2.1.x
- `gh`, `jq`, `git` on your PATH (the installer checks and stops if any are missing)
- For `/push` and `/merge`: authenticated with your git host. For Adobe enterprise:
  `gh auth login --hostname git.corp.adobe.com`
- **For Jira features** (`/prep`, `/workflow`, `/push` auto-resolve): the `corp-jira`
  MCP server, reachable either directly (`mcp__corp-jira__*` tools) or via the
  `mcp-exec` wrapper. The commands auto-detect which route you have. Without either,
  `/prep` still creates branches and `/push` still opens PRs — only the Jira
  ticket/resolve steps no-op. The plugin doesn't ship corp-jira; an MCP server is
  your own machine's config, not something a plugin can bundle.

## Migrating from the old separate plugins

If you previously installed `workflow-tools` and/or `claude-guardrails` as separate
plugins, remove them first — **inside Claude Code**, because only `/plugin uninstall`
deregisters a plugin and clears its cached files (a shell script can't):

```
/plugin uninstall workflow-tools
/plugin uninstall claude-guardrails
```

The installer enforces this. On launch it scans `~/.claude/plugins/installed_plugins.json`
for either plugin; if it finds one still installed it prints the exact
`/plugin uninstall` command and exits without changing anything. Run the uninstall
in Claude Code, then re-run `install.sh`. Once they're gone, the installer also
strips the stale `workflow-tools`/`claude-guardrails` keys from `settings.json` so
you don't have to touch it.

## Install (4 steps)

**1. Unzip somewhere stable.** Where you unzip is where it lives — the installer
records that path. Don't unzip to a temp folder you'll clear.

```bash
unzip coderails.zip -d ~/Documents/Github/
```

**2. Run the installer.**

```bash
bash ~/Documents/Github/coderails/install.sh
```

It does everything that has to happen outside Claude Code:
- checks `gh`/`jq`/`git`
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
- seeds four feedback memories and a `failure_log.md` template (won't overwrite)
- arms the scripts (`chmod +x`)

`bash install.sh --dry-run` shows everything it would do without touching anything.

**3. Restart Claude Code, then run in order:**

```
/plugin marketplace add ~/Documents/Github/coderails
/plugin install coderails@coderails
/reload-plugins
```

The installer already wrote the settings entry, so `marketplace add` resolves the
local directory instead of trying to clone it as a git URL. `marketplace add` first,
then `install`.

**4. Per project (run once per repo):**

```
/workflow-init                 # scaffolds .claude/workflow.config.yaml
/coderails:test-gate-setup     # optional — blocks commits when tests fail
```

## What you get

| Commands | Skills | Hooks (automatic) |
|---|---|---|
| `/workflow` `/prep` `/push` `/merge` `/workflow-init` | agentic-loop | confidence-label check (Stop) |
| `/assumptions` `/verify` `/notchecked` `/disconfirm` | planning-sequence | Did-Not-Verify catch-up (UserPromptSubmit) |
| `/test-gate-setup` | premortem | destructive-bash gate (PreToolUse) |
| | handoff | project test gate (PreToolUse) |

The two UserPromptSubmit hooks nudge: inject_context runs silently, and the
discipline catch-up injects a reminder into the next turn. The two Stop hooks
(confidence-label check and verify-loop) block via exit 2 — they were promoted
from warn-mode on 2026-05-05. The destructive-bash gate and the opt-in test
gate also block.

## Notes

- **Memory seeds land in a per-project memory dir derived from your current
  directory.** If you want them in a specific project, run the installer from
  inside that project, or pass `--memory-target /path/to/project/memory`.
- **The `[ctx]` line** the discipline loop injects on each prompt is invisible to
  you — only Claude sees it. To confirm the loop is live: `/help` lists
  `/assumptions /verify /notchecked /disconfirm`, and `~/.claude/discipline.log`
  starts filling with entries after a few responses.
- **`/prep`'s Jira fields are tuned to the CPGNCX workflow.** The epic field
  (`customfield_11800`), story points (`customfield_10003` = 1), and `GA` fix
  version match a specific Jira project. Custom-field IDs are usually consistent
  across Adobe Jira, but **transition names are project-specific.** `/prep`
  transitions a new ticket to `Acknowledged` (verified reachable on CPGNCX), then
  *attempts* `In Progress` and treats failure as non-fatal — CPGNCX's workflow has
  no "In Progress" transition, so the ticket simply stays at "Acknowledged." If
  your project uses different state names, run `get_jira_transitions` on one of its
  issues and adjust `commands/prep.md` Part 2 accordingly.

## Uninstall

```bash
bash ~/Documents/Github/coderails/uninstall.sh   # reverses CLAUDE.md + settings changes
```

then in Claude Code:

```
/plugin uninstall coderails
```

Your `failure_log.md`, `discipline.log`, and memory entries are preserved (your data).
