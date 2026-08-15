---
provider: codex
id: disconfirm
source_kind: command
graph_role: null
required_inputs: [most recent recommendation]
output_contract: Strongest case against the most recent recommendation.
status: active
---

# disconfirm

This is the native Codex implementation for `disconfirm`.

## Execution

Perform the requested operation against the supplied context. Validate inputs before changing state, fail closed on missing prerequisites, and return the declared output contract with exact evidence.

## Inputs

Required: `[most recent recommendation]`.

## Result

Produce: `Strongest case against the most recent recommendation.`.
