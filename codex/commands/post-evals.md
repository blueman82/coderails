---
provider: codex
id: post-evals
source_kind: command
graph_role: U4b-merge-gate
required_inputs: [PR#]
output_contract: Validated, SHA-bound eval-artifact summary posted as a durable PR artifact.
status: active
---

# post-evals

This is the native Codex implementation for `post-evals`.

## Execution

Perform the requested operation against the supplied context. Validate inputs before changing state, fail closed on missing prerequisites, and return the declared output contract with exact evidence.

## Inputs

Required: `[PR#]`.

## Result

Produce: `Validated, SHA-bound eval-artifact summary posted as a durable PR artifact.`.
