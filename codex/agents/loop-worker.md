---
provider: codex
id: loop-worker
source_kind: agent
graph_role: U3
required_inputs: [one scoped unit of work from a plan]
output_contract: Implemented, tested, self-reviewed code with a committed artifact/open PR.
status: active
---

# loop-worker

This is the native Codex implementation for `loop-worker`.

## Execution

Act as the named specialist for the supplied scope. Read relevant evidence, make only the requested recommendation or change, and return the declared output contract with evidence and remaining risks.

## Inputs

Required: `[one scoped unit of work from a plan]`.

## Result

Produce: `Implemented, tested, self-reviewed code with a committed artifact/open PR.`.
