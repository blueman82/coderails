---
name: neutral workflow config init
description: Implement provider-native SessionStart nudges and migrate Claude and Codex to one canonical .coderails/workflow.config.yaml.
type: project
---

# Neutral workflow config init

> Supersession note (2026-09-21): This is a historical configuration-migration handoff. The canonical `.coderails/workflow.config.yaml` contract continues to apply. The shell runtime and test filenames below are historical. Each provider resolves configuration through its own `scripts/lib/config.py`. Current hook and test commands use Python.

## Goal

Make the approved clean break from provider-specific workflow configuration to one canonical `.coderails/workflow.config.yaml`. Each plugin owns its SessionStart behavior and init instructions. The two plugins read the same project configuration path and operate independently.

## Decisions

- `.coderails/workflow.config.yaml` is the only canonical configuration path. This removes provider-dependent project configuration.
- Do not add fallback to `.claude/workflow.config.yaml` or `.codex/workflow.config.yaml`. A repository with only legacy configuration is unconfigured until init migrates it.
- Use each plugin's existing SessionStart bootstrap script for the nudge. Do not add a second hook.
- The SessionStart hook detects the condition and prompts the user. It must not make, edit, move, or remove configuration files.
- If the legacy provider config exists and the canonical file does not, show a stable nudge without duplicates. Tell Claude users to run `/coderails:init`. Tell Codex users to run `$coderails-codex:init`.
- Init writes and validates `.coderails/workflow.config.yaml` first. Only if validation succeeds can it move `.claude/workflow.config.yaml` and `.codex/workflow.config.yaml` to the macOS Trash.
- Stop and report the problem if the canonical write, validation, or Trash move does not succeed. Do not remove legacy configuration directly.
- Make `.coderails/workflow.config.yaml` committable. Continue to ignore runtime data in `.coderails/`.
- Keep graph hardening, graph parity, mixed-provider inspection, and shared provider executables out of scope.

## Constraints

- Claude owns the root plugin. Codex owns `packages/codex/`. Duplicate provider-facing hook and skill behavior where necessary. Each package operates independently at runtime.
- Claude init is `commands/init.md`. Codex init is `packages/codex/skills/init/SKILL.md`.
- Do not show the nudge again on resume, clear, or compact SessionStart invocations.
- Keep all existing workflow configuration values, such as `sandbox_workers`. Change the location and migration behavior only. Keep the schema unchanged.
- The current `.gitignore` ignores `.coderails/` and all `workflow.config.yaml` files. Init says to commit the generated config. Unignore only the canonical file and continue to ignore runtime graph data.
- After unit tests, install the two provider packages and test each in a new session before reporting the migration complete.

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

Use this sequence

```text
detect legacy -> nudge -> run provider init -> write canonical -> validate canonical -> move legacy to Trash
```

## Key files

- `hooks/hooks.json` and `hooks/scripts/inject_bootstrap.sh` — Claude SessionStart registration and existing bootstrap behavior.
- `packages/codex/hooks/hooks.json` and `packages/codex/hooks/scripts/inject_bootstrap.sh` — Codex SessionStart registration and bootstrap behavior.
- `commands/init.md` — Claude init workflow.
- `packages/codex/skills/init/SKILL.md` — Codex init workflow.
- `scripts/lib/config.sh` is the Claude configuration resolver. Change it to use only the canonical path.
- `packages/codex/scripts/lib/config.sh` is the Codex configuration resolver. Change it to use only the canonical path.
- `hooks/scripts/wiki_taxonomy_gate.sh`, `packages/codex/hooks/scripts/wiki_taxonomy_gate.sh`, `scripts/merge.sh`, and `packages/codex/scripts/merge.sh` — direct configuration readers that must use the canonical path.
- `packages/codex/skills/prep/SKILL.md` and `packages/codex/skills/push/SKILL.md` — Codex instructions containing direct provider-specific paths.
- `skills/wiki-{ingest,init,lint,query}/SKILL.md` and matching `packages/codex/skills/wiki-*` files — wiki path resolution instructions.
- Provider-specific paths appear in `examples/workflow.config.yaml`, `.gitignore`, `README.md`, `INSTALLATION.md`, `AGENTS.md`, `AGENTS-wiki-schema.md`, and `docs/REFERENCE.md`.
- `hooks/scripts/tests/inject_bootstrap.test.sh`, `hooks/scripts/tests/config.test.sh`, `hooks/scripts/tests/wiki_taxonomy_gate.test.sh`, `hooks/scripts/tests/enforce_pr_workflow.test.sh`, and `hooks/scripts/tests/merge_wiki_debt_gate.test.sh` — focused Claude-side tests.
- `packages/tests/codex_hooks.test.sh` and `packages/tests/codex_native_package.test.sh` cover Codex hooks and packaging. Test the resolver there or in one targeted package test.

## Done so far

- The provider separation has merged. Claude is at the repository root. Codex is in `packages/codex/`.
- The prior session selected the neutral config migration and recorded it in memory. It did not write an implementation, tests, commit, or PR.
- The source inventory shows that each provider has a SessionStart bootstrap hook. There is no need for a new lifecycle hook or manifest entry.
- The source inventory also found the `.gitignore` problem and the direct readers above.

## Next steps

1. Start with a clean, current `main`. Make a worktree and branch for this migration.
2. Before implementation, freeze task evals for the behavior that each provider must demonstrate.
3. Update the two resolvers and all direct readers to use only `.coderails/workflow.config.yaml`.
4. Add the stable legacy-config nudge to each provider's existing SessionStart bootstrap and test non-repetition.
5. Update Claude and Codex init instructions to write and validate the canonical file, then safely move legacy files to Trash.
6. Change `.gitignore` to make only `.coderails/workflow.config.yaml` committable. Keep other `.coderails` runtime data ignored.
7. Update provider-facing skills, examples, installation guidance, the working guide, wiki schema, and component documentation.
8. Run focused checks:
   - `bash hooks/scripts/tests/inject_bootstrap.test.sh`
   - `bash hooks/scripts/tests/config.test.sh`
   - `bash hooks/scripts/tests/wiki_taxonomy_gate.test.sh`
   - `bash hooks/scripts/tests/enforce_pr_workflow.test.sh`
   - `bash hooks/scripts/tests/merge_wiki_debt_gate.test.sh`
   - `bash packages/tests/codex_hooks.test.sh`
   - `bash packages/tests/codex_native_package.test.sh`
   - `scripts/quality/check.sh --strict --changed`
9. After targeted tests succeed, run `bash hooks/scripts/tests/run_all.sh` one time.
10. Install each provider independently in a clean temporary location. Start new Claude and Codex sessions. Check the nudge and init without cross-provider dependencies.
11. Commit, push, and open a PR. Report the test results and the results from the live sessions.

## Open questions

- None. The earlier decision sets the migration and provider ownership. Stop implementation only if a newly discovered problem materially changes this contract.
