---
provider: codex
id: assumptions
source_kind: command
graph_role: null
required_inputs: [current working context]
output_contract: Every current assumption listed, marked verified or inferred.
status: active
---

# assumptions

This is the native Codex implementation for `assumptions`.

## Execution

Perform the requested operation against the supplied context. Validate inputs before changing state, fail closed on missing prerequisites, and return the declared output contract with exact evidence.

## Inputs

Required: `[current working context]`.

## Result

Produce: `Every current assumption listed, marked verified or inferred.`.
