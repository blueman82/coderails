# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Wiki Knowledge Base

**At the start of every conversation**, read `AGENTS.md` in this directory for wiki
maintenance protocols. The coderails wiki is a persistent, compounding knowledge
base maintained by Claude and browsed by the maintainer in Obsidian. The wiki vault lives at
the wiki vault directory (e.g. `../coderails-wiki` relative to the plugin, or wherever you placed it).

## What this repo is

`coderails` is a **Claude Code plugin** — not an application. It ships as a zip,
installs via `install.sh` + `/plugin install`, and bundles three things:

1. **Workflow commands** — the `prep → push → merge → wiki` chain (`commands/*.md`)
2. **Skills** — agentic-loop, planning-sequence, premortem, handoff (`skills/*/SKILL.md`)
3. **A discipline loop** — hooks that nudge or block on confidence labels,
   unverified claims, destructive bash, and failing tests (`hooks/`)

There is no build step and no compiled artifact. "Source" is markdown (commands,
skills) and bash (hook scripts, workflow scripts). It is version-controlled in the
version-controlled in your own private fork/repo.

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
| `PreToolUse` (Write/Edit/MultiEdit) | `no_edit_on_main.sh` | **block** — on main/master, blocks edits to ANY file EXCEPT an explicit allowlist: `.md`/`.txt`/`.rst` (plain docs), `.yaml`/`.yml`/`.json`/`.toml`/`.ini`/`.cfg` (config), the literal `.gitignore` dotfile (by basename), and `LICENSE`. Plugin source markdown (`skills/*/SKILL.md`, `commands/*.md`) is also blocked (they are source, not docs) when the file's repo carries `.claude-plugin/plugin.json`. Both the gated-ness and the branch check key off the **file's own repo** — a sibling non-plugin repo's `commands/`/`skills/` markdown is never falsely blocked. |

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
- Read the hook payload from stdin via `input=$(cat)`, parse with `jq`.
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
inline via a `!` bash substitution in its frontmatter, using a dual-path lookup:

```bash
GIT_ROOT=$(git rev-parse --show-toplevel)
cat "$GIT_ROOT/projects/$(basename $(pwd))/.claude/workflow.config.yaml" \  # monorepo layout
  || cat "$GIT_ROOT/.claude/workflow.config.yaml" \                         # standalone repo
  || echo "NO_CONFIG"
```

If you add a config field, update **all four** of `workflow.md`, `prep.md`,
`push.md`, and `init.md` (the scaffolder) — they each read the file
independently. `NO_CONFIG` is the sentinel for "not initialised."

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
