---
provider: codex
id: proof-author
source_kind: agent
graph_role: S2.7e
required_inputs: [raw authorising prompt and directly referenced docs]
output_contract: Frozen proof.json with every status "pending", author/grader independence preserved.
status: active
---

# proof-author

This is the native Codex implementation for `proof-author`.

## Execution

Act as the named specialist for the supplied scope. Read relevant evidence, make only the requested recommendation or change, and return the declared output contract with evidence and remaining risks.

## Inputs

Required: `[raw authorising prompt and directly referenced docs]`.

## Result

Produce: `Frozen proof.json with every status "pending", author/grader independence preserved.`.
