---
provider: codex
id: task-evals
source_kind: skill
graph_role: S2.7c
required_inputs: [task definition, plan]
output_contract: Frozen evals.json (schema_version 1) of independent, game-resistant success evals gating merge/loop completion.
status: active
---

# task-evals

This is the native Codex implementation for `task-evals`.

## Execution

Apply this capability to the current request and available workspace state. Inspect relevant evidence before making claims, keep scope bounded by the request, and return the declared output contract.

## Inputs

Required: `[task definition, plan]`.

## Result

Produce: `Frozen evals.json (schema_version 1) of independent, game-resistant success evals gating merge/loop completion.`.

## Authority boundary

- Committed `docs/evals/*.json` files and local `evals.json` files are working material only; they are never live PR-readiness evidence.
- For PR readiness, fetch the current PR head and require the newest trusted SHA-bound `coderails-eval-summary` PR comment/embed for that exact head.
- Missing, stale, mismatched, rejected, untrusted, or fetch-failed eval evidence is `NO-GO`.
