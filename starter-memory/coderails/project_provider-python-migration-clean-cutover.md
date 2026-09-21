---
name: provider-python-migration-clean-cutover
description: Resume the approved clean-cutover migration of both Coderails providers to Python and a single current graph contract.
type: project
---

# Provider Python Migration: Clean Cutover

## Goal

Migrate all Coderails-owned Bash runtime scripts for the root Claude plugin and `packages/codex` plugin to Python. Align both providers on one current graph contract while preserving provider-native dispatch, evidence binding, and safety gates.

## Decisions

- Python is the single implementation language for Coderails-owned runtime scripts in both providers.
- The graph contract is a clean cutover: current schema only. Do not preserve, read, convert, dual-write, or grandfather historical or active graph state.
- Keep provider-native dispatch and provider-local evidence. The shared contract must not replace either provider's agent loop.
- Keep the five-second hook-input timeout, Git-internal trusted command allowance, `/bin/bash -c` behavior where required, failure denial, and 1,500-byte output cap when migrating Codex `test_gate.sh`.
- All pre-existing quality violations are in scope: PEP 8/20/257, strict docstrings, Ruff, Black, comment quality, function/file-size checks, and coverage. Do not suppress findings, raise caps, add broad exclusions, or use `--no-verify`.

## Constraints

- Use the existing Coderails agentic-loop graph; the top-level session is its only graph writer.
- Do not start Factory work.
- Preserve behavior before refactoring. The user has explicitly rejected compatibility for legacy graph states, not behavior loss in the current supported path.
- Do not publish, create a PR, or merge without fresh user authorization.
- Xcode licence was accepted on 2026-09-18. `git` and `python3` should now be usable again; verify this before relying on it.

## Graph State Incident

The active Codex graph state is:

`/Users/garyharr/.coderails/agentic-loop/-Users-garyharr-Github-coderails-.git/01a061b6-79e2-7bf0-8935-57399e7d52bc/progress.json`

It was structurally repaired after a missing active-wave envelope. The subsequent message calling it invalid was caused by `python3 graph.py inspect` failing because macOS had not accepted the Xcode licence; it was not evidence of another graph invariant failure. The loop was then deliberately hard-stopped at revision 66 because the user requested a fresh-session handoff; node `M3` is `hard-stop`, with reason `user-requested handoff`. Treat this graph as closed historical evidence. Do not resume or mutate it.

## Key Files

- `docs/superpowers/plans/2026-09-03-provider-graph-alignment-implementation.md`: approved implementation plan.
- `skills/agentic-loop/scripts/graph.py`: root Claude graph runtime.
- `packages/codex/skills/agentic-loop/scripts/graph.py`: Codex graph runtime.
- `packages/graph-semantics/graph_semantics.py`: intended shared graph semantics source.
- `skills/agentic-loop/scripts/graph_semantics.py` and `packages/codex/skills/agentic-loop/scripts/graph_semantics.py`: provider copies under active migration; assess against clean-cutover decision.
- `packages/codex/hooks/scripts/graph_completion_guard.sh`: installed version calls Python graph inspection; source may differ in the integration worktree.
- `scripts/quality/check.py` and `scripts/quality/tests/quality.test.sh`: strict quality checks and their migration work.
- `hooks/scripts/loop_cost.sh`: ongoing quality decomposition; focused test is `hooks/scripts/tests/loop_cost.test.sh`.

## Current Worktree and State

- Integration worktree: `/Users/garyharr/Github/coderails-provider-python-migration`
- Branch: `feature/provider-python-migration`
- Current repository cwd at handoff: `/Users/garyharr/Github/coderails` on `main`.
- Known earlier commits: `637f2445 feat(claude): migrate test gate to python`; `5655b4fb feat: materialize shared graph semantics`.
- M3 was the stopped integration node. Its intended scope was removal of remaining Coderails-owned Bash scripts, clean v3 graph cutover, cross-provider parity, and strict-quality remediation.

## Next Steps

1. Verify `xcodebuild -checkFirstLaunchStatus`, `python3 --version`, and `git status` now work.
2. Inspect the stopped graph only to confirm the hard stop; begin a new loop for remaining work.
3. Re-read the approved plan and the active integration diff.
4. Apply the user-approved clean cutover: remove v2 graph readers, fixtures, validation routes, fallback, conversion, and dual-write paths; leave one current schema only.
5. Finish remaining Bash-to-Python migrations for both providers, preserving each command's observable contract.
6. Eliminate every strict-quality finding through small refactors and targeted checks; do not weaken checks.
7. Run provider-native acceptance and full strict checks. Report evidence; do not publish without authorization.

## Open Questions

- None before implementation. Publishing remains separately authorized.
