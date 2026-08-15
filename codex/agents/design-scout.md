---
provider: codex
id: design-scout
source_kind: agent
graph_role: S2.5
required_inputs: [unresolved architectural fork, actual code paths]
output_contract: One recommendation with a named flip-condition for the design fork.
status: active
---

# design-scout

This is the native Codex implementation for `design-scout`.

## Execution

Act as the named specialist for the supplied scope. Read relevant evidence, make only the requested recommendation or change, and return the declared output contract with evidence and remaining risks.

## Inputs

Required: `[unresolved architectural fork, actual code paths]`.

## Result

Produce: `One recommendation with a named flip-condition for the design fork.`.
