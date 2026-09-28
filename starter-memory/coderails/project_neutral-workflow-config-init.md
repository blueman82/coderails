---
name: neutral workflow config init
description: Implement provider-native SessionStart nudges and migrate Claude and Codex to one canonical .coderails/workflow.config.yaml.
type: project
---

# Neutral workflow config init

> Supersession note (2026-09-21): This is a historical configuration-migration handoff. The canonical .coderails/workflow.config.yaml contract remains current, but the shell runtime/test filenames below were retired. Both providers now resolve configuration through their own scripts/lib/config.py, and current hook/test commands use Python.

## Goal

Implement the previously selected clean-break migration from provider-specific workflow configuration to one canonical `.coderails/workflow.config.yaml`. Keep the Claude and Codex plugins independent: each provider owns its own SessionStart behavior and init instructions, while both read the same project configuration path.

## Decisions

- `.coderails/workflow.config.yaml` is the only canonical configuration path. This removes provider-dependent project configuration.
- Do not add resolver fallback to `.claude/workflow.config.yaml` or `.codex/workflow.config.yaml`; legacy-only repositories must be treated as unconfigured until init migrates them.
- Reuse each plugin's existing SessionStart bootstrap script. Do not add a second hook when the registered bootstrap can emit the nudge.
- The SessionStart hook only detects and prompts. It must not create, edit, move, or delete configuration.
- When a legacy provider config exists and the canonical file does not, emit a stable, non-spamming nudge to run that provider's init entry point: `/coderails:init` for Claude and `$coderails-codex:init` for Codex.
- Init writes and validates `.coderails/workflow.config.yaml` first. Only after successful validation may it move legacy `.claude/workflow.config.yaml` and `.codex/workflow.config.yaml` files to the macOS Trash.
- A failed canonical write, failed validation, or failed Trash move must stop and report the problem. Never delete legacy configuration directly.
- Keep `.coderails/workflow.config.yaml` committable while leaving runtime state under `.coderails/` ignored.
- Do not implement graph hardening, graph parity, mixed-provider review, or shared provider executables in this change.

## Constraints

- The root plugin is Claude-owned; `packages/codex/` is the independent Codex plugin. Duplicate provider-facing hook and skill behavior where required instead of coupling the packages at runtime.
- Claude init is currently `commands/init.md`; Codex init is `packages/codex/skills/init/SKILL.md`.
- The nudge must not repeat on resume, clear, or compact SessionStart events.
- Preserve existing workflow configuration values, including `sandbox_workers`; this task changes location and migration behavior, not the schema.
- The current `.gitignore` ignores `.coderails/` and every `workflow.config.yaml`, while init says the generated config should be committed. Narrowly unignore the canonical file without exposing runtime graph state.
- Do not claim completion from unit tests alone. Verify both provider packages in fresh sessions after installation.

## Schema / Taxonomy

Canonical path:

```text
<project-root>/.coderails/workflow.config.yaml
```

Legacy inputs eligible for migration:

```text
<project-root>/.claude/workflow.config.yaml
<project-root>/.codex/workflow.config.yaml
```

Required order:

```text
detect legacy -> nudge -> run provider init -> write canonical -> validate canonical -> move legacy to Trash
```

## Key files

- `hooks/hooks.json` and `hooks/scripts/inject_bootstrap.sh` — Claude SessionStart registration and existing bootstrap behavior.
- `packages/codex/hooks/hooks.json` and `packages/codex/hooks/scripts/inject_bootstrap.sh` — Codex SessionStart registration and bootstrap behavior.
- `commands/init.md` — Claude init workflow.
- `packages/codex/skills/init/SKILL.md` — Codex init workflow.
- `scripts/lib/config.sh` — Claude configuration resolver; change to canonical path only.
- `packages/codex/scripts/lib/config.sh` — Codex configuration resolver; change to canonical path only.
- `hooks/scripts/wiki_taxonomy_gate.sh`, `packages/codex/hooks/scripts/wiki_taxonomy_gate.sh`, `scripts/merge.sh`, and `packages/codex/scripts/merge.sh` — direct configuration readers that must use the canonical path.
- `packages/codex/skills/prep/SKILL.md` and `packages/codex/skills/push/SKILL.md` — Codex instructions containing direct provider-specific paths.
- `skills/wiki-{ingest,init,lint,query}/SKILL.md` and matching `packages/codex/skills/wiki-*` files — wiki path resolution instructions.
- `examples/workflow.config.yaml`, `.gitignore`, `README.md`, `INSTALLATION.md`, `AGENTS.md`, `AGENTS-wiki-schema.md`, and `docs/REFERENCE.md` — examples and documentation that currently name provider-specific paths.
- `hooks/scripts/tests/inject_bootstrap.test.sh`, `hooks/scripts/tests/config.test.sh`, `hooks/scripts/tests/wiki_taxonomy_gate.test.sh`, `hooks/scripts/tests/enforce_pr_workflow.test.sh`, and `hooks/scripts/tests/merge_wiki_debt_gate.test.sh` — focused Claude-side tests.
- `packages/tests/codex_hooks.test.sh` and `packages/tests/codex_native_package.test.sh` — Codex hook and package tests; add resolver behavior coverage here or in one focused package test.

## Done so far

- The provider split is already merged: Claude remains at the repository root and Codex remains under `packages/codex/`.
- The neutral config migration was selected and documented in prior session memory, but no implementation, tests, commit, or PR were produced.
- Current source inventory confirms both providers already have registered SessionStart bootstrap hooks, so this work does not require a new lifecycle event or hook manifest entry.
- Current source inventory also found the `.gitignore` conflict and the direct readers listed above.

## Next steps

1. Start from a completely clean, current `main`; create a focused worktree and branch for this migration.
2. Freeze task evals for the two-provider acceptance behavior before implementation.
3. Update both resolvers and every direct reader to use only `.coderails/workflow.config.yaml`.
4. Add the stable legacy-config nudge to each provider's existing SessionStart bootstrap and test non-repetition.
5. Update Claude and Codex init instructions to write and validate the canonical file, then safely move legacy files to Trash.
6. Resolve `.gitignore` so only `.coderails/workflow.config.yaml` becomes committable while other `.coderails` state stays ignored.
7. Update provider-facing skills, examples, installation guidance, the working guide, wiki schema, and reference documentation.
8. Run focused checks:
   - `bash hooks/scripts/tests/inject_bootstrap.test.sh`
   - `bash hooks/scripts/tests/config.test.sh`
   - `bash hooks/scripts/tests/wiki_taxonomy_gate.test.sh`
   - `bash hooks/scripts/tests/enforce_pr_workflow.test.sh`
   - `bash hooks/scripts/tests/merge_wiki_debt_gate.test.sh`
   - `bash packages/tests/codex_hooks.test.sh`
   - `bash packages/tests/codex_native_package.test.sh`
   - `scripts/quality/check.sh --strict --changed`
9. Run `bash hooks/scripts/tests/run_all.sh` once after focused tests pass.
10. Install each provider independently into clean temporary locations, start fresh Claude and Codex sessions, and verify the correct nudge and init behavior without cross-provider dependencies.
11. Commit, push, open a PR, and report exact tested versus live-verified evidence.

## Open questions

- None. The migration shape and provider ownership are settled; implementation should stop only for a newly discovered conflict that materially changes this contract.
