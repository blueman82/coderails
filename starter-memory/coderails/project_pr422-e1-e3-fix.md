---
name: pr422-e1-e3-fix-and-rerun
description: PR #422 exact-head investigation, root-cause fixes, and fresh E1-E3 eval rerun handoff.
type: project
---

# PR #422 E1-E3 Fix and Rerun

> Supersession note (2026-09-21): This is a historical PR #422 repair handoff. Work and artifact posting require current authorization. The Python and schema 3 cutover retired its shell paths and earlier Codex package-test names. Check the current implementation and component documentation before using an earlier diagnostic.

## Goal

Examine and repair PR #422's E1-E3 and related NO-GO results at the PR head. Rerun the evals and publish new, accurate SHA-bound reviewer and eval results. The user explicitly wants investigation and repair. Formally disclose all items that the PR contract prevents you from correcting. Do not conceal them.

## Decisions

- Scope is PR #422 only. Do not examine, mention, or cite PR #418.
- The live PR repository is `blueman82/coderails`. Its branch is `codex/live-graph-wiring`. Its base is `neutral-integration/parallel-review`.
- Current PR head when this handoff was written: `e8704dd0ac1b915ad2b38fabfaf5ceb527a00598`.
- Work in a new sibling worktree. Do not edit the primary checkout.
- Keep provider ownership and the frozen mixed-provider contract. Do not weaken fail-closed gates. Use records from live provider runs to prove live behavior.
- Prefer the smallest repair that corrects the cause. The generated Codex runtime and canonical runtime must stay byte-identical.
- Keep the PR unmerged. Commit and push the PR branch only if the repair needs it. Identify the last head SHA before posting reviewer or eval artifacts.

## Constraints

- Read `AGENTS.md` before substantive edits. Independently check the live PR head and base, `origin/main`, and the applicable base before editing.
- Freeze or update task evals before implementation. Follow the repository task-evals rules. Use the repository eval tooling to calculate the result. Do not write it manually.
- The checkout's local `origin` is a fixture-only path and must not be used for live GitHub operations. Use `gh -R blueman82/coderails` or explicit `GH_REPO=blueman82/coderails`.
- `gh api user --hostname github.com` showed that the active GitHub CLI account is `blueman82` on `github.com`. Do not disclose tokens.
- The existing reviewer and eval artifacts record NO-GO for the earlier run. After a repair, obtain new records for the current PR head.

## Key files

- In `codex/runtime/graph.py`, examine `evaluate_parallel_review_join`. The prior reviewer found that it rejects records without top-level `route` and nested `provenance.provider`. The live Claude writer omits them.
- `packages/codex/runtime/graph.py` is the generated, packaged Codex runtime. Compare it byte-for-byte with the canonical runtime after changes.
- In `codex/scripts/run_graph.py`, examine how reviewer JSON reaches the neutral join. The prior reviewer found no normalization adapter.
- `codex/tests/test_graph_runtime.py` and `codex/tests/test_live_graph_wiring.py` reportedly add `route` and provenance to fixtures. They can miss the output shape of the live Claude writer.
- Examine the record shape from the Claude-owned production writer in `hooks/scripts/lib/parallel_review.sh`. Keep ownership unless the frozen contract explicitly permits a Claude-side change.
- `hooks/scripts/lib/parallel_review_join.sh` is the existing Claude-side join and documents the frozen contract.
- `docs/evals/live-graph-wiring.evals.json` is the checked-in PR eval file. At the handoff head, E1-E4 had null status and `evidence`. The fields `head_sha` and `frozen_sha` pointed at the previous base `1a9c38a301a4a4b83fe07d52d419fd5e9398eeaa`.
- `scripts/post_evals.sh`, `scripts/lib/eval-artifact.sh`: structural validation, smoke/discriminating checks, computed result, and posting mechanics.
- `commands/post-review.md`, `commands/post-evals.md`, `scripts/post_review.sh`: SHA-bound artifact posting conventions.
- At the prior head, `packages/tests/codex_package.test.sh` found provider-specific Claude content in the standalone Codex package.
- At the prior head, executable-bit manifest and invariant tests found two tracked hook scripts missing from the manifest.
- `skills/agentic-loop/execution-graph.md`, `skills/index.yaml`: E3 graph contract and provider routing/parity.

## Done so far

- A new reviewer agent independently examined 21 changed files and reported NO-GO.
- At handoff, `gh -R blueman82/coderails` showed PR #422 was OPEN at `e8704dd0ac1b915ad2b38fabfaf5ceb527a00598`.
- SHA-bound reviewer artifact at comment `5328969094`: https://github.com/blueman82/coderails/pull/422#issuecomment-5328969094
- SHA-bound eval artifact posted at comment `5329706802`, result `NO-GO`, verification_level `2`: https://github.com/blueman82/coderails/pull/422#issuecomment-5329706802
- Live marker verification confirmed the two artifacts bind to PR 422 and head `e8704dd0ac1b915ad2b38fabfaf5ceb527a00598`.
- No tracked files were changed, no commit/push/merge/deploy occurred in this session.

## Prior NO-GO findings to reproduce and fix

- The checked-in E1-E3 evals had no grades or run records. They pointed at the previous base. They must point at the PR head.
- There were no records from a live provider run with the Claude output shape. Fixtures and canned wiring records cannot establish live behavior.
- The Codex join required `route` and `provenance.provider`. The live Claude writer omitted those fields, so the join would reject legitimate Claude records.
- The neutral join accepted records from non-provider identities. It did not reject records with an incorrect creator or provider identity.
- The standalone Codex package independence and parity test found provider-specific Claude content in the package.
- The executable-bit invariant check for the PR head found two tracked hook scripts missing from the manifest.
- Prior checks passed for Python graph behavior (27 tests), runtime parity, parallel-review, join, harness, skills-index, and provider-graph. The discriminating and review-summary grammar checks also succeeded. Rerun them after changes to get the result for the new head.

## Next steps

1. Start a new session. Read this file, `AGENTS.md`, the current PR metadata, and the applicable current skill instructions.
2. Use a new sibling worktree at the PR branch and head. Check that the primary worktree stays unchanged.
3. Examine E1-E3 and all earlier blockers against the actual files and frozen contract. Correct the shared cause with the smallest repair. Do not conceal errors with fixture fields or relaxed gates.
4. Freeze or update eval definitions before implementation. Make the smallest coherent repair and add regression tests. Keep Claude-owned files and provider boundaries unless the contract requires a joint change.
5. Run the applicable graph, provider-parity, package-independence, fail-closed/wrong-creator, executable-bit/protected-path, and eval tests. Check canonical and packaged byte identity.
6. Commit and push only the PR branch if the repair satisfies the checks. Record the new head SHA.
7. Run new reviewer checks and evals against that head. If E1-E3 or a different P0 is unresolved, formally disclose it and post `NO-GO`. Post `GO` only if the records for all P0 checks and the checks done independently show success.
8. Check the live reviewer and eval markers, SHA, result, comment URLs, and changed files. Check that the PR is unmerged. Report commands verbatim, exit codes, and remaining limits.

## Open questions

- Can we remove Codex-only routing and provenance requirements? Or does this need an explicitly frozen contract extension and a joint Claude writer change?
- Did the package independence check detect a source-generation boundary issue or a leak of provider-specific imports or content?
- Which two scripts does the executable-bit manifest omit? Get their paths from the current PR-head tests. Use the prior summary as historical context.
