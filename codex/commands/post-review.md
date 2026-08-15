---
provider: codex
id: post-review
source_kind: command
graph_role: U4b-review
required_inputs: [PR#]
output_contract: Validated, SHA-bound review summary posted as a durable PR artifact.
status: active
---

# post-review

This is the native Codex implementation for `post-review`.

## Execution

Perform the requested operation against the supplied context. Validate inputs before changing state, fail closed on missing prerequisites, and return the declared output contract with exact evidence.

## Inputs

Required: `[PR#]`.

## Result

Produce: `Validated, SHA-bound review summary posted as a durable PR artifact.`.
