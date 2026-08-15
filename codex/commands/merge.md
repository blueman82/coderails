---
provider: codex
id: merge
source_kind: command
graph_role: U4b-merge-gate
required_inputs: [pr-number | branch-name | auto]
output_contract: Approved PR merged, switched to main, and pulled latest changes.
status: active
---

# merge

This is the native Codex implementation for `merge`.

## Execution

Perform the requested operation against the supplied context. Validate inputs before changing state, fail closed on missing prerequisites, and return the declared output contract with exact evidence.

## Inputs

Required: `[pr-number | branch-name | auto]`.

## Result

Produce: `Approved PR merged, switched to main, and pulled latest changes.`.
