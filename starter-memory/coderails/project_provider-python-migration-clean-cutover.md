---
name: provider-python-migration-clean-cutover
description: Resume the approved clean-cutover migration of both Coderails providers to Python and a single current graph contract.
type: project
---

# Provider Python Migration: Clean Cutover

> Supersession note (2026-09-21): This records the migration requirements and the work unit that was active. The current checkout uses maintained Python entrypoints and schema 3 only. The shell paths, active node, and continuation instructions are historical. Use the owned session graph for current work status. Use the implementation plan for the criteria for accepting the work.

## Goal

Migrate all Coderails-owned Bash runtime scripts for the root Claude plugin and `packages/codex` plugin to Python. Align the two providers on one current graph contract. Keep provider-native dispatch, the links to provider records, and safety gates.

## Decisions

- Python is the only implementation language for Coderails-owned runtime scripts in the two providers.
- The graph contract is a clean cutover with the current schema only. Do not keep, read, convert, dual-write, or grandfather historical or active graph data.
- Keep provider-native dispatch and provider-local records. Keep each provider's own agent loop.
- When migrating Codex `test_gate.sh`, keep the five-second hook-input timeout and allowance for trusted Git-internal commands. Keep `/bin/bash -c` behavior where required. Keep denial on error and the 1,500-byte output cap.
- All pre-existing quality violations are in scope. Check PEP 8/20/257, strict docstrings, Ruff, Black, comment quality, function/file-size limits, and coverage. Do not suppress results, raise caps, add broad exclusions, or use `--no-verify`.

## Constraints

- Use the existing Coderails agentic-loop graph. The top-level session is its only writer.
- Do not start Factory work.
- Keep behavior in the current graph path during refactoring. The user explicitly rejected compatibility with legacy graph data.
- Do not publish, open a PR, or merge without new authorization.
- Xcode license approval occurred on 2026-09-18. Check that `git` and `python3` work before using them.

## Graph State Incident

The active Codex graph record was:

`/Users/garyharr/.coderails/agentic-loop/-Users-garyharr-Github-coderails-.git/01a061b6-79e2-7bf0-8935-57399e7d52bc/progress.json`

After repair of the missing active-wave envelope, `python3 graph.py inspect` did not run because macOS had no Xcode license approval. That error led to a message that called the graph invalid. The message did not show that a different invariant broke. The user asked for a handoff to a new session, so the loop deliberately hard-stopped at revision 66.

Node `M3` is `hard-stop` with cause `user-requested handoff`. Keep this graph as a closed historical record. Do not continue or change it.

## Key Files

- `docs/superpowers/plans/2026-09-03-provider-graph-alignment-implementation.md`: approved implementation plan.
- `skills/agentic-loop/scripts/graph.py`: root Claude graph runtime.
- `packages/codex/skills/agentic-loop/scripts/graph.py`: Codex graph runtime.
- `packages/graph-semantics/graph_semantics.py`: intended shared graph semantics source.
- `skills/agentic-loop/scripts/graph_semantics.py` and `packages/codex/skills/agentic-loop/scripts/graph_semantics.py` are the provider copies during migration. Check them against the cutover decision.
- Installed `packages/codex/hooks/scripts/graph_completion_guard.sh` calls Python graph inspection. The integration worktree can have different source.
- `scripts/quality/check.py` and `scripts/quality/tests/quality.test.sh`: strict quality checks and their migration work.
- `hooks/scripts/loop_cost.sh` is part of the quality decomposition work. Its targeted test is `hooks/scripts/tests/loop_cost.test.sh`.

## Current Worktree and State

- Integration worktree: `/Users/garyharr/Github/coderails-provider-python-migration`
- Git branch `feature/provider-python-migration`
- Current repository cwd at handoff: `/Users/garyharr/Github/coderails` on `main`.
- Known earlier commits: `637f2445 feat(claude): migrate test gate to python` and `5655b4fb feat: materialize shared graph semantics`.
- M3 was the stopped integration node. Its intended scope was removal of remaining Coderails-owned Bash scripts, clean v3 graph cutover, cross-provider parity, and strict-quality remediation.

## Next Steps

1. Check that `xcodebuild -checkFirstLaunchStatus`, `python3 --version`, and `git status` work.
2. Examine the stopped graph only to check for the hard stop. Start a new loop for the remaining work.
3. Re-read the approved plan and the active integration diff.
4. Apply the user-approved clean cutover. Remove v2 graph readers, fixtures, validation paths, fallback, conversion, and dual-write paths. Keep only the current schema.
5. Finish remaining Bash-to-Python migrations for the two providers, preserving each command's observable contract.
6. Correct all strict-quality violations through small refactors and targeted checks. Do not weaken checks.
7. Run full strict checks and tests through each provider's native path. Report the results. Do not publish without authorization.

## Open Questions

- None before implementation. Publishing has its own approval.
