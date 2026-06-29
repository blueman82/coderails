# AGENTS.md — Coderails

This file is the single source the LLM reads at conversation start. It covers two
things, in order:

1. **The repo working guide** — what coderails is, how the pieces wire together,
   the enforcement model, the hook map, workflow command architecture, and how to
   edit this repo safely.
2. **The wiki schema** — how the coderails wiki (a persistent, compounding
   knowledge base maintained by Claude and browsed in Obsidian) is structured,
   maintained, and queried.

The wiki vault lives at the wiki vault directory (e.g. `../coderails-wiki`
relative to the plugin, or wherever you placed it during `/wiki-init`).
`CLAUDE.md` in this repo is a thin pointer to this file — edit here, not there.

# Part 1 — Working in this repo

## What this repo is

`coderails` is a **Claude Code plugin** — not an application. It ships as a zip,
installs via `install.sh` + `/plugin install`, and bundles three things:

1. **Workflow commands** — the `prep → push → merge → wiki` chain (`commands/*.md`)
2. **Skills** — agentic-loop, planning-sequence, premortem, handoff (`skills/*/SKILL.md`)
3. **A discipline loop** — hooks that nudge or block on confidence labels,
   unverified claims, destructive bash, and failing tests (`hooks/`)

There is no build step and no compiled artifact. "Source" is markdown (commands,
skills) and bash (hook scripts, workflow scripts). It is version-controlled in
your own private fork/repo.

## How the pieces wire together

```
.claude-plugin/plugin.json      → plugin manifest (name, version, metadata)
.claude-plugin/marketplace.json → local-directory marketplace entry (source: ./)
hooks/hooks.json                → maps lifecycle events → hook scripts
  └─ hooks/scripts/*.sh         → the actual gate/nudge logic
commands/*.md                   → slash commands (frontmatter + prose instructions)
  └─ scripts/*.sh               → bash the commands shell out to (push.sh, merge.sh)
       └─ scripts/lib/git-common.sh → shared git/gh/PR helpers, sourced by both
       └─ scripts/lib/config.sh     → workflow.config.yaml resolver (single source of truth; see "Config resolution")
skills/*/SKILL.md               → skills with triggering descriptions
instructions/                   → the discipline rules appended to ~/.claude/CLAUDE.md
starter-memory/                 → feedback memories seeded into the user's memory dir
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

### Enforcement ceiling — what a local hook can and can't guarantee

"Enforced regardless of whether Claude cooperates" has a real ceiling, and
`enforce_pr_workflow` is the clearest case. That hook checks **evidence of
invocation** — a `/coderails:push` or `/pr-review-toolkit:review-pr` step appears
in the transcript — **not evidence of completion**. A hollow invocation (the step
ran but did nothing, or errored) still satisfies it. More fundamentally, a hook
runs inside the agent's own trust domain: anything the hook checks, the agent can
also satisfy directly, because there is no privilege boundary between them. So
treat these gates as a **redirect-and-audit layer** — they steer a cooperating
agent onto the workflow and leave a greppable trail in `discipline.log` — not as a
tamper-proof barrier. The real "no unreviewed change reaches `main`" guarantee
lives **server-side: GitHub branch protection** (required PR + required reviews +
no direct pushes), which no local agent can fake. The local hook complements
branch protection; it does not replace it. (The same honest boundary applies to
the Stop-hook gates — they can force a declared step to appear, not to be real.)

### Skills↔hooks seam convention

When a skill instructs an action that a hook gates — e.g. `git merge`/`gh pr create`/`gh pr merge` → `enforce_pr_workflow`; code-file & plugin-source (`SKILL.md`/command) edits on main → `no_edit_on_main`; `git commit` → `test_gate` — the skill must name the gating hook and the resolution path (what the user needs to do, or what bypass flag satisfies it). When you add a hook that gates a common action, update the skills that instruct it. The merge gate (`enforce_pr_workflow`) recognises PR-review evidence as the `/pr-review-toolkit:review-pr <PR#>` Skill invocation (with the PR number in args), NOT a manually-spawned agent fanout — so the agentic loop must invoke the Skill to clear the merge gate.

## Hook event map (`hooks/hooks.json`)

| Event | Script | Mode |
|---|---|---|
| `SessionStart` | `inject_bootstrap.sh` | silent — injects `using-coderails` skill into every new session |
| `UserPromptSubmit` | `inject_context.sh` | silent — prepends `[ctx]` (cwd, branch, date) |
| `UserPromptSubmit` | `discipline_catchup.sh` | warn |
| `Stop` + `SubagentStop` | `check_confidence_labels.sh` | **block** (exit 2) when a substantive response (≥200 chars) carries no `(verified)`/`(inferred)`/`(guess)` label. On `SubagentStop`, reads `last_assistant_message` directly (avoids the parent-transcript flush race). |
| `Stop` + `SubagentStop` | `check_verify_loop.sh` | **block** (exit 2) when a `## Did Not Verify` bullet is left untagged — enforced regardless of whether files were edited this turn; only an explicit `(unverifiable: <reason>)` tag passes. On `SubagentStop`, reads `last_assistant_message` directly. `loop_state_guard`/`loop_stall_guard` remain Stop-only (loop-state ownership is a parent-session concept). |
| `Stop` | `loop_state_guard.sh` | **block** (exit 2) when an agentic loop is active but no session-owned `progress.json` exists — enforces presence + ownership |
| `Stop` | `loop_stall_guard.sh` | **block** (exit 2) when an agentic loop is active and incomplete with no valid `LOOP-STOP` declaration in the stopping turn |
| `PreToolUse` (Bash) | `destructive_bash_gate.sh` | **block** — permanent blocklist: `rm -rf`, `git push --force`, `git reset --hard`, SQL `DROP TABLE/DATABASE/SCHEMA` and `TRUNCATE TABLE`, `dd if=`, `mkfs.*`, `chmod -R 777`, `git commit --no-verify`, `git clean -f/--force`, `find -delete/--delete`, `truncate -s/--size`, `shred`. Also blocks in-Bash source-file edits (`sed -i`, `perl -i`, `>` / `>>` redirects, `tee`, `cp`/`mv`/`dd of=` targeting source extensions or plugin markdown) when on main/master (best-effort). No approval path — settings.json Bash permission rule is the only escape. |
| `PreToolUse` (Bash) | `enforce_pr_workflow.sh` | **block** — `gh pr create` without `/coderails:push`; `gh pr merge <N>` without `/pr-review-toolkit:review-pr <N>` (per-PR, consume-on-use); `git merge` on main/master without `review-pr` since the last merge; `git push` to main/master (by current branch, colon refspec, or positional bare branch token) without `review-pr`. Scans `agent_transcript_path` in subagent context. `git merge-base/merge-file/merge-tree` and `--abort/--continue/--quit/--skip` excluded. No-op if no `workflow.config.yaml`. |
| `PreToolUse` (Bash) | `test_gate.sh` | **block** on `git commit` if tests fail — opt-in only |
| `PreToolUse` (Write/Edit/MultiEdit) | `no_edit_on_main.sh` | **block** — on main/master, blocks edits to ANY file EXCEPT an explicit allowlist: `.md`/`.txt`/`.rst` (plain docs), `.yaml`/`.yml`/`.json`/`.toml`/`.ini`/`.cfg` (config), the literal `.gitignore` dotfile (by basename), and `LICENSE`. Plugin source markdown (`skills/*/SKILL.md`, `commands/*.md`) is also blocked (they are source, not docs) when the file's repo carries `.claude-plugin/plugin.json`. Both the gated-ness and the branch check key off the **file's own repo** — a sibling non-plugin repo's `commands/`/`skills/` markdown is never falsely blocked. Separately, a permission-file arm blocks edits to `.claude/settings.json` / `.claude/settings.local.json` on **any** branch, in any repo (matched on the `.claude/` parent, so an unrelated `settings.json` elsewhere passes). These hold the `permissions.allow` rules that pre-approve commands upstream of every PreToolUse gate — editing them is the one move that can dismantle the discipline layer, so the agent never edits them. |

### Enforcement ceilings — what the hooks deliberately do NOT fully cover

These are honest limits by design, not bugs. Document them here so they aren't
re-opened as findings.

- **Bash blocklists are enumerated families, not exhaustive.** `destructive_bash_gate`
  and the in-Bash source-edit gate catch known destructive patterns; obfuscated forms,
  variable filenames, quoted paths with spaces, here-docs, process substitution, and
  `python -c open(...)` writes remain uncaught. The gate is best-effort.
- **`no_edit_on_main` allowlist breadth is intentional (fail-safe).** `.sh` is blocked
  on main while `.json`/`.yaml` config stays editable — an accepted classification.
  The allowlist may over-block edge cases; the settings.json `Write`/`Edit` permission
  escape covers any legitimate override.
- **Wiki/workflow sequence past merge is advisory, not enforced.** The `/workflow`
  chain (`/wiki-ingest` + `/wiki-lint`) after merge is a slash command — Claude must
  choose to invoke it. No hook enforces it.
- **`check_verify_loop` and the two loop guards short-circuit on `stop_hook_active=true`
  (block at most once per turn).** This is an intentional infinite-loop safety valve.
  `check_confidence_labels` does NOT read `stop_hook_active` and can re-block on a
  re-armed Stop.
- **TDD is not enforced test-first.** `test_gate` only checks that tests pass at
  commit time; it does not enforce the red-green-refactor sequence.
- **Skill invocation, ask-on-ambiguity, and verify-memory are structurally
  unenforceable by hooks.** They depend on Claude choosing to do them; a hook
  cannot observe or mandate internal reasoning steps.
- **No `SubagentStart` event exists.** The `inject_bootstrap.sh` SessionStart hook
  cannot inject the `using-coderails` skill into subagents. Subagents receive it only
  if it is included in their system prompt by the orchestrator.

**Hook script conventions** (follow these when editing or adding a script):
- Read the hook payload from stdin via `IFS= read -r -d '' -t 5 input || true`, then parse with `jq`. The 5-second timeout prevents a hook blocking forever if its parent process dies without closing stdin; `|| true` is mandatory because `read -d ''` returns exit 1 on normal EOF. The `read -t 5` bound is an in-process BACKSTOP for a hook orphaned past its parent's death (reparented to PID 1, where the hooks.json `timeout` can no longer kill it) — it is deliberately <= the smallest hooks.json `timeout` so the two never disagree. Do not "reconcile" them by raising hooks.json. On `read -t` timeout, `input` is empty -> jq yields empty -> the command gate stands aside (exit 0). This fail-open-on-stall is the deliberate, correct posture for a PreToolUse enforcement hook (a stalled hook must not block every tool call); do not add `set -e` or flip the empty-input branch to a deny.
- **Exit early and often.** Three scripts use named gate functions called in order at
  the bottom of the file: `enforce_pr_workflow.sh` (local `gate_*` functions) and
  `loop_state_guard.sh` / `loop_stall_guard.sh` (shared-lib `als_gate_*` variant
  sourced from `lib/loop_state_common.sh`). The other four scripts
  (`check_verify_loop.sh`, `check_confidence_labels.sh`, `no_edit_on_main.sh`,
  `destructive_bash_gate.sh`) use inline `if`-blocks — that pattern is equally fine.
  New scripts should prefer named gate functions. Cheap skip-gates first, expensive
  transcript-parsing last. Guard scripts do NOT use `set -euo pipefail` — preserve
  that; gate functions `exit` directly.
- Block via: `exit 2` with a message on **stderr** for Stop hooks; or emit
  `hookSpecificOutput.permissionDecision: "deny"` JSON to **stdout** then fall through
  to `exit 0` for PreToolUse hooks — do NOT use `exit 2` in PreToolUse hooks.
- Append a structured single-line log entry to `$CLAUDE_DISCIPLINE_LOG`
  (default `~/.claude/discipline.log`) — keep the `key=value` format greppable.
- Guard against the transcript-flush race: `loop_stall_guard.sh` retries
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
inline via a `!` bash substitution in its frontmatter. The substitution sources
a shared resolver and calls it:

```bash
source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/config.sh" && coderails::resolve_config
```

`scripts/lib/config.sh` is the **single source of truth** for locating the config.
`coderails::config_path [dir]` walks up from `dir` (default `$PWD`) to the git
root and echoes the first `.claude/workflow.config.yaml` found (empty if none);
`coderails::resolve_config [dir]` echoes its contents or `NO_CONFIG`. The walk-up
is layout-agnostic: standalone repos, classic `projects/<name>/` monorepos, and
arbitrary layouts (`apps/web`, `services/api`, …) all resolve from any subdir.
Nearest wins — replacement, not inheritance/merge.

`${CLAUDE_PLUGIN_ROOT}` is string-substituted by Claude Code in command
frontmatter (it was a bug that it wasn't for `allowed-tools`, since fixed), so
the path is always the real plugin dir — for a local/directory marketplace it
resolves to the source checkout, for an installed plugin to the cache copy; in
both the lib file exists. The same resolver is sourced (via `$(dirname "$0")`)
by `scripts/merge.sh` (`lib/config.sh`) and `hooks/scripts/enforce_pr_workflow.sh`
(`../../scripts/lib/config.sh`) — the hook's opt-in detection MUST use the same
resolver as the commands, or the merge gate would silently go inactive in a
non-`projects/` layout. If you add a config field, update **all four** of
`workflow.md`, `prep.md`, `push.md`, and `init.md` (the scaffolder) — they each
read the file independently. `NO_CONFIG` is the sentinel for "not initialised."

**`scripts/` vs `commands/`** — `push.sh`/`merge.sh` hold the deterministic git
plumbing (commit, push, `gh pr create`, merge). The `.md` commands hold the
prose/decision logic and shell out to those scripts. Shared git/gh helpers live
in `scripts/lib/git-common.sh` (sourced via `source "$(dirname "$0")/lib/..."`);
add reusable git/PR primitives there, not inline.

## Project-specific assumptions baked in (change these when generalising)

These are the things most likely to need editing for your project:

- **Auth host**: `push.sh` requires a `github.com` remote (validated by `require::repo`).
- **Jira fields**: `prep.md` reads epic and story-points field IDs from `config.jira.epic_field` and `config.jira.points_field` (set for your project in workflow.config.yaml). Transition names are also project-specific; see INSTALLATION.md "Notes".
- **Jira route**: commands build Jira MCP tool names at runtime from `config.jira.mcp_namespace` in `workflow.config.yaml` (default: `jira`, giving `mcp__jira__*`). Set `mcp_namespace` to your server's namespace (e.g. `acme-jira`) — no edits to command files needed. For non-default namespaces, add `"mcp__<namespace>__*"` to `.claude/settings.json` `permissions.allow`; without a Jira MCP, Jira steps no-op (branches/PRs still work). See INSTALLATION.md "Notes".

## Working in this repo

- **Editing a command or skill**: changes take effect after `/reload-plugins` in
  a running Claude Code session — there's nothing to compile.
- **Editing a hook**: same; test by triggering the event and checking
  `~/.claude/discipline.log`. `bash install.sh --dry-run` shows what the
  installer would touch without changing anything.
- **`install.sh` is idempotent** — re-running won't duplicate CLAUDE.md edits or
  overwrite seeded memories. Preserve that property.
- **`uninstall.sh` must reverse exactly what `install.sh` adds** (CLAUDE.md
  block, settings keys) while preserving user data (`discipline.log`,
  memories). Keep the two scripts in lockstep.
- The discipline rules in `instructions/self-checking-discipline.md` are the
  authoritative copy that `install.sh` appends to `~/.claude/CLAUDE.md`; edit the
  instructions file, not the installed copy.

## Requirements

Claude Code 2.1.x · `gh`, `jq`, `git` on PATH · authenticated git host for
`/push`/`/merge` · `pr-review-toolkit@claude-plugins-official` for the review
stage of `/workflow`.

---

# Part 2 — The coderails wiki schema

This is the single source of truth for wiki conventions. Do NOT create a separate
`schema.md` inside the vault.

## Wiki location

`<your-wiki-vault-path>/` (set during /wiki-init)

Vault structure:
```
coderails-wiki/
  index.md          ← content catalog; read this first on every wiki query
  log.md            ← append-only chronological record
  commands/         ← one page per slash command
  hooks/            ← one page per hook script
  skills/           ← one page per skill
  design/           ← architectural decisions and invariants
  investigations/   ← point-in-time filed analyses (<topic>_<YYYY-MM-DD>.md)
  sources/          ← ingested PR records (pr_<N>_<slug>.md)
  templates/        ← page skeletons (command.md, hook.md, skill.md, design.md, investigation.md, source.md)
  assets/           ← charts and images
```

## Three layers

1. **Raw sources** (immutable): The plugin repo at `<plugin-install-path>/` (wherever you unzipped coderails) — commands, hooks, scripts, skills, install.sh, CLAUDE.md. Read from these; never modify source when updating wiki.
2. **The wiki**: LLM-generated markdown in the vault above. Claude owns this layer entirely — creates pages, updates cross-references, maintains consistency.
3. **This file (AGENTS.md)**: Tells Claude how the wiki is structured, what conventions to follow, what workflows to run. Co-evolved between the maintainer and Claude over time. The maintainer edits this file to change conventions; Claude reads it on every session.

## Page types

| Type | Directory | Naming | Purpose |
|---|---|---|---|
| command | `commands/` | `<command-name>.md` | Documents one slash command: what it does, config fields, scripts invoked |
| hook | `hooks/` | `<script-name>.md` | Documents one hook script: event, mode, logic, block condition |
| skill | `skills/` | `<skill-name>.md` | Documents one skill: purpose, trigger phrases, phases, failure modes encoded |
| design | `design/` | `<topic>.md` | Architectural decisions and invariants; evergreen |
| investigation | `investigations/` | `<topic>_<YYYY-MM-DD>.md` | Point-in-time analysis filed during a workflow session; may be superseded |
| source | `sources/` | `pr_<N>_<slug>.md` | Immutable record of a merged PR, created by `/wiki-ingest` |

## Page format

Every page must have:

```yaml
---
title: "<Page title>"
type: <command|hook|skill|design|investigation|source>
created: YYYY-MM-DD
last_updated: YYYY-MM-DD
sources: []        # list of PR source page paths that informed this page
tags: []           # freeform list
---
```

Body rules:
- Use `[[wiki-links]]` for all cross-references between wiki pages.
- Keep pages concise — under 2 minutes to read.
- Focus on knowledge that compounds (relationships, decisions, patterns), not facts derivable directly from reading the source code.
- Confidence-label non-trivial assertions: `(verified)` (source cited), `(inferred)` (pattern-matched), `(guess)` (explicit speculation).

## Enforcement model (wiki lens)

The full treatment — hooks vs commands, the enforcement ceiling, and the
skills↔hooks seam convention — lives in the **Two enforcement mechanisms**
section of Part 1 above. For wiki purposes the rule is: when documenting a hook
page vs a command page, record *which* mechanism it is and *what it can/can't
guarantee*; link the page to [[enforcement-model]] and cite the ceiling caveats
verbatim so they aren't re-opened as findings.

## Workflows

### Ingest (after every PR merge)

Use `/wiki-ingest` from the coderails plugin. Never write wiki pages directly for PR content.

1. Create `sources/pr_<N>_<slug>.md` using `templates/source.md`
2. Update affected concept/design/hook/command/skill pages with new knowledge
3. Append an entry to `log.md`: `## [YYYY-MM-DD] ingest | PR #N merged: <description>`
4. Update `index.md` if new pages were created
5. Then run `/wiki-lint`

### Query

Use `/wiki-query` from the coderails plugin. The skill reads `index.md` first, then fetches relevant pages, then answers the question with citations.

### Lint

Use `/wiki-lint` from the coderails plugin. Always run after ingest. Checks for: orphaned pages (linked but not created), stale `last_updated` dates, missing cross-references, contradictions between pages.

Fix anything directly related to the current PR; defer unrelated findings.

## Evolution note

This file is co-evolved. When conventions change — new page types, new frontmatter fields, naming rule changes — update this file first, then update affected pages in the vault. The maintainer edits this file; Claude reads it. The wiki is a living system, not a snapshot.
