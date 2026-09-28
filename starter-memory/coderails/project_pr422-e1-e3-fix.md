---
name: pr422-e1-e3-fix-and-rerun
description: PR #422 exact-head investigation, root-cause fixes, and fresh E1-E3 eval rerun handoff.
type: project
---

# PR #422 E1-E3 Fix and Rerun

> Supersession note (2026-09-21): This is a historical PR #422 repair handoff, not current authorization or an instruction to post artifacts. Its shell paths and prior Codex package-test names were retired by the Python/schema-3 cutover. Consult the current implementation and component reference before reusing an old diagnostic.

## Goal

Investigate and fix PR #422's E1-E3 and related exact-head NO-GO findings, rerun the acceptance evals, and publish a new truthful SHA-bound review/eval result. The user explicitly prefers both investigation and repair; formally disclose any item that cannot be fixed within the PR contract instead of masking it.

## Decisions

- Scope is PR #422 only. Never inspect, mention, or use PR #418 as evidence.
- Current live PR repository is `blueman82/coderails`; branch is `codex/live-graph-wiring`; base is `neutral-integration/parallel-review`.
- Current PR head when this handoff was written: `e8704dd0ac1b915ad2b38fabfaf5ceb527a00598`.
- Work in a fresh sibling worktree. Do not edit the primary checkout.
- Preserve provider ownership and the frozen mixed-provider contract. Do not weaken fail-closed gates or substitute fixtures for real provider evidence.
- Minimal root-cause fixes are preferred; generated Codex runtime and canonical runtime must remain byte-identical.
- No merge is authorized. A branch commit/push is in scope only if needed to deliver the requested fix; post review/eval artifacts only after the final exact head is known.

## Constraints

- Read `AGENTS.md` before substantive edits. Independently verify the live PR head/base and `origin/main`/relevant base before editing.
- Freeze or update task-eval material before implementation according to the repository task-evals rules; do not hand-write a result. Result must be computed by the supported eval tooling.
- The checkout's local `origin` is a fixture-only path and must not be used for live GitHub operations. Use `gh -R blueman82/coderails` or explicit `GH_REPO=blueman82/coderails`.
- Active GitHub CLI account is now `blueman82` on `github.com`; verified with `gh api user --hostname github.com`. Do not expose tokens.
- Existing review/eval artifacts are NO-GO evidence, not proof of the new run. Fresh exact-head evidence is required after any fix.

## Key files

- `codex/runtime/graph.py`: inspect `evaluate_parallel_review_join`; prior review found it required top-level `route` and nested `provenance.provider` fields that the real Claude writer does not emit.
- `packages/codex/runtime/graph.py`: generated/packaged Codex runtime; compare byte-for-byte with canonical runtime after changes.
- `codex/scripts/run_graph.py`: inspect the path from reviewer JSON into the neutral join; prior review found no normalization adapter.
- `codex/tests/test_graph_runtime.py`, `codex/tests/test_live_graph_wiring.py`: existing tests reportedly enrich fixtures with route/provenance and therefore may miss the real Claude writer output shape.
- `hooks/scripts/lib/parallel_review.sh`: Claude-owned production writer; inspect its actual record shape but preserve ownership unless the frozen contract explicitly permits a Claude-side change.
- `hooks/scripts/lib/parallel_review_join.sh`: pre-existing Claude-side join and frozen contract reference.
- `docs/evals/live-graph-wiring.evals.json`: checked-in PR eval file; at the handoff head it had E1-E4 with null status/evidence and `head_sha`/`frozen_sha` pointing at the old base `1a9c38a301a4a4b83fe07d52d419fd5e9398eeaa`.
- `scripts/post_evals.sh`, `scripts/lib/eval-artifact.sh`: structural validation, smoke/discriminating checks, computed result, and posting mechanics.
- `commands/post-review.md`, `commands/post-evals.md`, `scripts/post_review.sh`: SHA-bound artifact posting conventions.
- `packages/tests/codex_package.test.sh`: prior exact-head failure: standalone Codex package contained provider-specific Claude content.
- Executable-bit manifest/invariant tests and tracked hook scripts: prior exact-head failure reported two tracked hook scripts missing from the manifest.
- `skills/agentic-loop/execution-graph.md`, `skills/index.yaml`: E3 graph contract and provider routing/parity.

## Done so far

- Fresh reviewer agent independently reviewed 21 changed files and reported NO-GO.
- Live PR metadata was verified with `gh -R blueman82/coderails`: PR #422 is OPEN and head is exactly `e8704dd0ac1b915ad2b38fabfaf5ceb527a00598`.
- SHA-bound review artifact posted at comment `5328969094`: https://github.com/blueman82/coderails/pull/422#issuecomment-5328969094
- SHA-bound eval artifact posted at comment `5329706802`, result `NO-GO`, verification_level `2`: https://github.com/blueman82/coderails/pull/422#issuecomment-5329706802
- Live marker verification confirmed both artifacts bind to PR 422 and head `e8704dd0ac1b915ad2b38fabfaf5ceb527a00598`.
- No tracked files were changed, no commit/push/merge/deploy occurred in this session.

## Prior NO-GO findings to reproduce and fix

- E1-E3 checked-in eval evidence was empty/ungraded and pointed at the old base rather than the PR head.
- No real provider-run/Claude-shaped evidence was available; fixture/canned wiring evidence is insufficient.
- Codex join required `route` and `provenance.provider` fields absent from the real Claude writer's output, so legitimate Claude evidence would be rejected as mismatched.
- Neutral join accepted records from non-provider identities; wrong-creator/provider identity was not fail-closed.
- Standalone Codex package independence/parity test failed because provider-specific Claude content appeared in the package.
- Exact-head executable-bit invariant failed because two tracked hook scripts were missing from the manifest.
- Tests that passed previously included Python graph tests (27), runtime parity, parallel-review/join/harness tests, skills-index/provider-graph tests, discriminating check, and review-summary grammar; these must be rerun after changes, not trusted as current proof.

## Next steps

1. Start a fresh session and read this file plus `AGENTS.md`, current live PR metadata, and the relevant current skill instructions.
2. Create/use a fresh sibling worktree at the exact PR branch/head; verify primary worktree remains untouched.
3. Investigate E1-E3 and every prior blocker against actual files and the frozen contract. Identify the smallest shared/root-cause fix; do not paper over failures with fixture fields or relaxed gates.
4. Freeze/update eval definitions before implementation, then implement the minimum coherent fix and regression tests. Keep Claude-owned files/provider boundaries intact unless the contract requires a coordinated change.
5. Run relevant graph, provider-parity, package-independence, fail-closed/wrong-creator, executable-bit/protected-path, and eval tests. Check canonical/packaged byte identity.
6. Commit and push only the PR branch if the fix is valid. Record the new exact head SHA.
7. Run fresh review and eval ceremonies against that exact head. If any E1-E3 or other P0 remains unresolved, formally disclose it and post a truthful `NO-GO`; only post `GO` when all P0 evidence and independent checks pass.
8. Verify live review/eval markers, SHA, result, comment URLs, changed files, and PR remains unmerged. Report exact commands/exit codes and remaining limitations.

## Open questions

- Whether the route/provenance mismatch is fixed by removing the Codex-only requirements or by an explicitly frozen contract extension and coordinated Claude writer change.
- Whether the package independence failure is a source-generation boundary issue or an actual provider-specific import/content leak.
- Exact identities/paths of the two executable-bit manifest failures; derive them from the current exact-head tests rather than relying on the prior summary.
