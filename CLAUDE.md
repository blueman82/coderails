# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Wiki Knowledge Base

**At the start of every conversation**, read `AGENTS.md` in this directory for wiki
maintenance protocols. The coderails wiki is a persistent, compounding knowledge
base maintained by Claude and browsed by Gary in Obsidian. The wiki vault lives at
`/Users/harrison/Documents/Github/coderails-wiki`.

## What this repo is

`coderails` is a **Claude Code plugin** — not an application. It ships as a zip,
installs via `install.sh` + `/plugin install`, and bundles three things:

1. **Workflow commands** — the `prep → push → merge → wiki` chain (`commands/*.md`)
2. **Skills** — agentic-loop, planning-sequence, premortem, handoff (`skills/*/SKILL.md`)
3. **A discipline loop** — hooks that nudge or block on confidence labels,
   unverified claims, destructive bash, and failing tests (`hooks/`)

There is no build step and no compiled artifact. "Source" is markdown (commands,
skills) and bash (hook scripts, workflow scripts). It is version-controlled in the
private repo `github.com/blueman82/coderails`.

## How the pieces wire together

```
.claude-plugin/plugin.json      → plugin manifest (name, version, metadata)
.claude-plugin/marketplace.json → local-directory marketplace entry (source: ./)
hooks/hooks.json                → maps lifecycle events → hook scripts
  └─ hooks/scripts/*.sh         → the actual gate/nudge logic
commands/*.md                   → slash commands (frontmatter + prose instructions)
  └─ scripts/*.sh               → bash the commands shell out to (push.sh, merge.sh)
       └─ scripts/lib/git-common.sh → shared git/gh/PR helpers, sourced by both
skills/*/SKILL.md               → skills with triggering descriptions
instructions/                   → the discipline rules appended to ~/.claude/CLAUDE.md
starter-memory/                 → feedback memories seeded into the user's memory dir
templates/failure_log.md        → seeded once, never overwritten
```

`${CLAUDE_PLUGIN_ROOT}` in `hooks.json` resolves to this repo's root at runtime —
that's how hook commands locate `hooks/scripts/*.sh`.

## Two enforcement mechanisms — don't confuse them

This is the central design distinction (`commands/workflow.md` calls it out
explicitly at the bottom):

- **Hooks = mechanical enforcement.** They run automatically on lifecycle events
  and can *block* (exit 2 / `permissionDecision: deny`). Use a hook when behaviour
  must be enforced regardless of whether Claude cooperates.
- **Slash commands = advisory.** Claude has to *choose* to invoke them. Use a
  command to encode a workflow, not to enforce one.

If you're asked to "make X mandatory," that belongs in a `PreToolUse` hook, not a
command.

## Hook event map (`hooks/hooks.json`)

| Event | Script | Mode |
|---|---|---|
| `UserPromptSubmit` | `inject_context.sh` | silent — prepends `[ctx]` (cwd, branch, date) |
| `UserPromptSubmit` | `discipline_catchup.sh` | warn |
| `Stop` | `check_confidence_labels.sh` | **block** (exit 2) when a substantive response (≥200 chars) carries no `(verified)`/`(inferred)`/`(guess)` label — promoted from warn-mode 2026-05-05 |
| `Stop` | `check_verify_loop.sh` | **block** (exit 2) when a `## Did Not Verify` bullet names a source-resolvable token (a `file.ext` or `file:line`) — items naming no file pass as genuinely unverifiable |
| `PreToolUse` (Bash) | `destructive_bash_gate.sh` | **block** |
| `PreToolUse` (Bash) | `test_gate.sh` | **block** on `git commit` if tests fail — opt-in only |

**Hook script conventions** (follow these when editing or adding a script):
- Read the hook payload from stdin via `input=$(cat)`, parse with `jq`.
- **Exit early and often.** `check_verify_loop.sh` uses a documented chain of
  numbered gates (1–6) where each skip gate `exit 0`s immediately. Preserve that
  pattern — cheap escape hatches first, expensive transcript parsing last.
- Block by either `exit 2` with a message on **stderr** (Stop hooks) or by
  emitting `hookSpecificOutput.permissionDecision: "deny"` JSON (PreToolUse).
- Append a structured single-line log entry to `$CLAUDE_DISCIPLINE_LOG`
  (default `~/.claude/discipline.log`) — keep the `key=value` format greppable.
- Guard against the transcript-flush race: `check_verify_loop.sh` retries
  `extract_last_text` with backoff until the length stabilises.

## Workflow command architecture

`/coderails:workflow` is the umbrella orchestrator; every phase delegates to a
standalone sub-command that also works on its own:

```
/workflow  →  /prep → (code) → /push → /pr-review-toolkit:review-pr → /merge → /wiki-ingest + /wiki-lint
```

Two interactive pauses where the user drives: the code/iterate loop, and final
ship-it authorization. Everything else auto-chains.

**Config resolution** — every workflow command reads `workflow.config.yaml`
inline via a `!` bash substitution in its frontmatter, using a dual-path lookup:

```bash
GIT_ROOT=$(git rev-parse --show-toplevel)
cat "$GIT_ROOT/projects/$(basename $(pwd))/.claude/workflow.config.yaml" \  # monorepo layout
  || cat "$GIT_ROOT/.claude/workflow.config.yaml" \                         # standalone repo
  || echo "NO_CONFIG"
```

If you add a config field, update **all four** of `workflow.md`, `prep.md`,
`push.md`, and `workflow-init.md` (the scaffolder) — they each read the file
independently. `NO_CONFIG` is the sentinel for "not initialised."

**`scripts/` vs `commands/`** — `push.sh`/`merge.sh` hold the deterministic git
plumbing (commit, push, `gh pr create`, merge). The `.md` commands hold the
prose/decision logic and shell out to those scripts. Shared git/gh helpers live
in `scripts/lib/git-common.sh` (sourced via `source "$(dirname "$0")/lib/..."`);
add reusable git/PR primitives there, not inline.

## Project-specific assumptions baked in (change these when generalising)

These are tuned to Gary's Adobe CPGNCX setup and are the things most likely to
need editing for another user/project:

- **Reviewers**: `push.sh` defaults `REVIEWERS="mhudson,pieczyra,omeara"`
  (overridable via `$GIT_REVIEWERS`).
- **Auth host**: `push.sh` hard-requires `gh auth status` to mention
  `git.corp.adobe.com`.
- **Jira fields**: `prep.md` uses CPGNCX-specific custom-field IDs
  (`customfield_11800` epic, `customfield_10003` story points) and transition
  names (`Acknowledged` is verified; `In Progress` is attempted and treated as
  non-fatal). See INSTALLATION.md "Notes" for the full caveat.
- **Jira route**: commands auto-detect `mcp__corp-jira__*` vs the `mcp-exec`
  wrapper; without either, Jira steps no-op (branches/PRs still work).

## Working in this repo

- **Editing a command or skill**: changes take effect after `/reload-plugins` in
  a running Claude Code session — there's nothing to compile.
- **Editing a hook**: same; test by triggering the event and checking
  `~/.claude/discipline.log`. `bash install.sh --dry-run` shows what the
  installer would touch without changing anything.
- **`install.sh` is idempotent** — re-running won't duplicate CLAUDE.md edits or
  overwrite seeded memories / `failure_log.md`. Preserve that property.
- **`uninstall.sh` must reverse exactly what `install.sh` adds** (CLAUDE.md
  block, settings keys) while preserving user data (`failure_log.md`,
  `discipline.log`, memories). Keep the two scripts in lockstep.
- The discipline rules in `instructions/self-checking-discipline.md` are the
  authoritative copy that `install.sh` appends to `~/.claude/CLAUDE.md`; edit the
  instructions file, not the installed copy.

## Requirements

Claude Code 2.1.x · `gh`, `jq`, `git` on PATH · authenticated git host for
`/push`/`/merge` · `pr-review-toolkit@claude-plugins-official` for the review
stage of `/workflow`.
