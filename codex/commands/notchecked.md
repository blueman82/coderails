---
provider: codex
id: notchecked
source_kind: command
graph_role: null
required_inputs: [claims made in session]
output_contract: List of claims made but not actually verified.
status: active
---

# notchecked

This is the native Codex implementation for `notchecked`.

## Execution

Perform the requested operation against the supplied context. Validate inputs before changing state, fail closed on missing prerequisites, and return the declared output contract with exact evidence.

## Inputs

Required: `[claims made in session]`.

## Result

Produce: `List of claims made but not actually verified.`.
