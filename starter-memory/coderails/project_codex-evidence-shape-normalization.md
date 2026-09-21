---
name: Codex evidence tampering closure
description: Close the remaining Codex evidence-encoding bypass and require an independent exact-head tampering audit before merge.
type: project
---

# Codex evidence tampering closure

## Goal

Fix only the native Codex graph-evidence tampering gap under `packages/codex/`. PR #446 closed the six known single-layer shapes and nested identity reuse, but a fresh executed probe found that a twice-encoded JSON reference still bypasses classification and allows one worker identity to be reused across nodes through completion.

Before merge, independently attack the exact PR head and confirm that no tampering bypass remains within the defined evidence-shape threat model. Do not turn “tests passed” into a universal claim that no undiscovered software defect can exist.

## Decisions

- Scope is Codex only under `packages/codex/`. Do not modify the root Claude plugin.
- Keep Claude and Codex implementations independent. Do not port Claude code or introduce shared provider code.
- Fix the class, not the twice-encoded example: repeatedly normalize JSON-encoded strings until they no longer decode, then recursively inspect every resulting object, array, key, and value.
- Do not use a fixed decoding-depth limit that can be bypassed by adding one more encoding layer. Bound input size and work instead.
- Route binding, stored-reference collection, uniqueness checking, and completion-time revalidation through the same classifier.
- A canonical Codex worker reference remains a top-level object with the exact required fields and `kind: codex_agent`.
- Any noncanonical value containing worker-reference markers or identifiers at any nesting or encoding depth must be rejected, not retained as ordinary evidence.
- One `spawn_call_id`, `agent_thread_id`, or `task_complete_turn_id` may belong to only one graph-node attempt.
- Preserve ordinary evidence that contains no worker provenance.
- No scheduler, new evidence store, daemon, database, dashboard coupling, provider router, or new dependency.

## Constraints

- Preserve transcript-backed worker identity, matching task start, successful final `task_complete`, retries, follow-ups, joins, proof, eval, retro, ownership, and completion checks.
- Do not let malformed evidence replace the required canonical worker reference.
- Do not allow evidence to pass binding and then bypass completion after its shape is changed.
- Use Python standard library for deterministic generated probes; do not add a fuzzing dependency.
- Start from clean current `main`, create an isolated worktree, and freeze task evals before editing.
- Use at most three spawned agents at once.
- Record individual test runtimes; avoid unnecessary repeated broad suites.

## Schema / Taxonomy

The only valid worker-reference shape remains:

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

- arrays and nested objects;
- JSON string encoding repeated any number of times within the accepted input-size limit;
- Unicode normalization and lookalike characters;
- leading or trailing whitespace;
- partial field sets and isolated worker identifiers;
- worker fields hidden in keys as well as values;
- reuse across nodes, waves, retries, and evidence entries;
- evidence reshaped after legitimate binding but before completion.

## Key files

- `packages/codex/skills/agentic-loop/scripts/graph_identity.py` — currently decodes a JSON string once; the twice-encoded bypass originates here.
- `packages/codex/skills/agentic-loop/scripts/graph_evidence.py` — binding, stored-reference collection, uniqueness checks, and completion validation.
- `packages/codex/skills/agentic-loop/scripts/graph.py` — graph completion calls evidence validation.
- `packages/tests/codex_graph_evidence_shapes.test.sh` — six known shape regressions; extend it to generated compositions.
- `packages/tests/codex_graph_runtime_adversarial.test.sh` — native transcript and lifecycle evidence tests.
- `packages/tests/provider_graph_parity.test.sh` and sibling adversarial suites — provider contract checks.

## Done so far

- PR #446 added recursive Codex evidence classification and closed the six named single-layer shapes: array wrapper, benign nesting, trailing-space kind, partial shape, Cyrillic lookalike, and one JSON-string encoding.
- Existing focused Codex graph, lifecycle, provider adversarial, and final acceptance suites passed after PR #446.
- A fresh independent end-to-end probe then hid node B's exact worker reference inside node A as twice-encoded JSON.
- The classifier returned no worker shape for that value; uniqueness validation missed it; graph completion and completion-time validation both returned success.
- The cause is that `graph_identity.py` calls `json.loads` only once and does not inspect the string produced by that decode.
- No repository files were changed during the audit.

## Next steps

1. Verify clean current `main`; create a focused Codex-only worktree and branch.
2. Freeze independent task evals before implementation. Include exact-head adversarial-audit acceptance, not only unit-test success.
3. Add the smallest terminating repeated-decode plus recursive-inspection fix in `graph_identity.py`; reuse it everywhere rather than adding another special case.
4. Add deterministic generated tests composing nesting, arrays, Unicode, whitespace, partial fields, keys, and repeated JSON encodings.
5. Test both entry points: initial binding and completion after legitimate evidence is mutated.
6. Test uniqueness across nodes, waves, retries, and multiple evidence entries for all three native identifiers.
7. Keep negative controls: valid canonical evidence succeeds; unrelated nested text and JSON remain accepted when they contain no worker provenance.
8. Run focused Codex evidence/runtime and provider parity/adversarial suites once, recording commands, exact-head SHA, results, and runtimes.
9. Open the PR but do not merge yet.
10. Spawn a fresh source-auditor against the exact PR head. It must not rely on the implementation plan or author tests alone. Ask it to invent new composed shapes and execute them through binding and completion.
11. The pre-merge verdict is PASS only when:
    - every defined threat-family test rejects tampering;
    - valid canonical and benign evidence controls pass;
    - transcript identity and final-success checks still pass;
    - the independent auditor finds no bypass within the documented threat model;
    - no relevant result is `UNSUPPORTED` or unexecuted;
    - all evidence is bound to the exact PR head SHA.
12. If any bypass is found, return to implementation and repeat the focused audit on the new head. Do not merge or claim closure.
13. Post the exact-head review and eval evidence, then stop for explicit merge approval.

## Open questions

- None. “No more tampering holes” means no bypass found across the defined threat families after independent exact-head execution; it is not a claim that no unknown software defect can ever exist.
