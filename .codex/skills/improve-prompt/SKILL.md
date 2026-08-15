---
provider: codex
id: improve-prompt
source_kind: skill
graph_role: S-1
required_inputs: [raw prompt to improve]
output_contract: Rewritten prompt with ambiguities surfaced and gaps filled with reasonable assumptions.
status: active
---

# improve-prompt

This is the native Codex implementation for `improve-prompt`.

## Execution

Apply this capability to the current request and available workspace state. Inspect relevant evidence before making claims, keep scope bounded by the request, and return the declared output contract.

## Inputs

Required: `[raw prompt to improve]`.

## Result

Produce: `Rewritten prompt with ambiguities surfaced and gaps filled with reasonable assumptions.`.
