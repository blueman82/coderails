---
name: Codex evidence tampering closure
description: Close the remaining Codex evidence-encoding bypass and require an independent exact-head tampering audit before merge.
type: project
---

# Codex evidence tampering closure

> Supersession note (2026-09-21): This is a historical handoff for worker-record normalization. Current native transcript parsers and Python adversarial suites supersede the historical shell paths and repair status. The pure schema-3 semantic core excludes checks of raw provider records. Use current source and the current owned graph for a new audit.

## Goal

Close only the native Codex graph-record tampering bypass in `packages/codex/`. PR #446 closed the six known single-layer shapes and nested identity reuse. A new probe showed that a JSON worker record with two encoding layers evades the classifier. The same worker identity can then count for multiple nodes when the graph ends.

Before merge, test the PR head independently against the defined threat model for worker-record shapes. Check that no tested shape bypasses the checks. Do not use “tests passed” to claim that the tests rule out unknown software defects.

## Decisions

- Change only Codex in `packages/codex/`. Do not change the root Claude plugin.
- Keep Claude and Codex implementations operating independently. Do not copy Claude code or introduce shared provider code.
- Correct the class of defects. Decode JSON strings until decoding no longer succeeds. Recursively examine all resulting objects, arrays, keys, and values.
- Limit input length and total work. One more encoding layer can bypass a fixed limit on decoding depth.
- Use the same classifier when binding, collecting, and checking records for uniqueness. Use it again for the checks that let the graph finish.
- The canonical Codex worker record is a top-level object. It must contain the required fields with no other fields and use `kind: codex_agent`.
- Reject a noncanonical value if it contains worker markers or identifiers at a nesting or encoding depth. Do not keep it as an ordinary record.
- One `spawn_call_id`, `agent_thread_id`, or `task_complete_turn_id` can belong to only one try at a graph node.
- Keep ordinary records that contain no worker provenance.
- Do not add a scheduler, record store, daemon, database, dashboard coupling, provider router, or dependency.

## Constraints

- Keep transcript-backed worker identity, matching task start, and the last `task_complete` with a success result. Keep retries, follow-ups, joins, proof, eval, retro, ownership, and end checks.
- Do not let a malformed record replace the required canonical worker record.
- After binding, a shape change must not bypass checks that run before the graph ends.
- Use Python standard library for deterministic generated probes. Do not add a fuzzing dependency.
- Start from clean current `main`, create an isolated worktree, and freeze task evals before editing.
- Use no more than three spawned agents at a time.
- Record the runtime for each test. Rerun broad suites only when necessary.

## Schema / Taxonomy

Only this worker-record shape is canonical:

```json
{
  "kind": "codex_agent",
  "attempt": 1,
  "wave_id": "wave-2",
  "spawn_call_id": "call_...",
  "agent_thread_id": "01a...",
  "task_complete_turn_id": "01a..."
}
```

The tampering threat model includes arbitrary compositions of:

- Arrays and nested objects.
- Multiple JSON string encodings up to the accepted input-length limit.
- Unicode normalization and lookalike characters.
- Whitespace at the start or end.
- Field subsets and isolated worker identifiers.
- Worker fields hidden in keys or values.
- The same identity across nodes, waves, retries, and record entries.
- Shape changes after legitimate binding and before the graph ends.

## Key files

- `packages/codex/skills/agentic-loop/scripts/graph_identity.py` decodes a JSON string one time. This causes the bypass when a string has two encoding layers.
- `packages/codex/skills/agentic-loop/scripts/graph_evidence.py` binds and collects worker records, checks uniqueness, and checks the records again before the graph ends.
- `packages/codex/skills/agentic-loop/scripts/graph.py` validates worker records before the graph ends.
- `packages/tests/codex_graph_evidence_shapes.test.sh` tests the six known shape regressions. Extend it to combinations made by the test code.
- `packages/tests/codex_graph_runtime_adversarial.test.sh` tests native transcripts and lifecycle records.
- `packages/tests/provider_graph_parity.test.sh` and sibling adversarial suites — provider contract checks.

## Done so far

- PR #446 added a recursive classifier for Codex worker records. It closed the array wrapper, benign nesting, trailing space in `kind`, and missing field shapes. It also closed the Cyrillic lookalike and one JSON-string encoding shapes.
- The targeted Codex graph, lifecycle, and provider adversarial suites passed after PR #446. The suite for accepting the full change also succeeded.
- A new end-to-end probe ran independently. It hid a verbatim copy of node B's worker record in node A as twice-encoded JSON.
- The classifier found no worker shape for that value, so the uniqueness check missed it. The graph could finish and the validation at the end reported success.
- `graph_identity.py` calls `json.loads` only one time. It does not examine the decoded string.
- No repository files were changed during the audit.

## Next steps

1. Check that `main` is clean and current. Make a worktree and branch for the Codex change.
2. Freeze task evals independently before implementation. Include an adversarial audit of the PR head in the criteria for accepting the work.
3. In `graph_identity.py`, add a terminating decode loop and recursive inspection. Use the same logic for all shapes.
4. Add deterministic tests that combine nesting, arrays, Unicode, whitespace, field subsets, keys, and multiple JSON encodings.
5. Test the initial binding and the checks at the end after a change to a legitimate record.
6. For all three native identifiers, test uniqueness across nodes, waves, retries, and multiple record entries.
7. Keep negative controls. Accept canonical records. Accept unrelated nested text and JSON when they contain no worker provenance.
8. Run targeted Codex worker-record and runtime suites and provider parity and adversarial suites one time. Record commands, head SHA, results, and runtimes.
9. Open the PR and keep it unmerged.
10. Spawn a new source-auditor against the PR head. It must use more than the implementation plan and author tests. Have it make new combinations and test binding and the checks at the end.
11. Give a pre-merge verdict of `PASS` only when all checks below succeed.
     - All tests for the defined threat families reject tampering.
     - Canonical and benign record controls succeed.
     - Transcript identity and last success checks succeed.
     - The auditor works independently and finds no bypass in the documented threat model.
     - No applicable result is `UNSUPPORTED` or unexecuted.
     - All records identify the same PR head SHA.
12. If a test finds a bypass, continue implementation and run the targeted audit again on the new head. Do not merge or claim closure.
13. Post the reviewer and eval artifacts for the PR head. Stop for explicit merge approval.

## Open questions

- None. “No more tampering holes” means that tests run independently against the PR head found no bypass in the defined threat families. The claim covers those tests only.
