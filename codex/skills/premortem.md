---
provider: codex
id: premortem
source_kind: skill
graph_role: null
required_inputs: "plan, decision, or approach to stress-test"
output_contract: Backwards-reasoned failure modes and causes assuming the plan already failed.
status: active
---

# premortem

This is the native Codex implementation for `premortem`.

## Execution

Apply this capability to the current request and available workspace state. Inspect relevant evidence before making claims, keep scope bounded by the request, and return the declared output contract.

## Inputs

Required: `"plan, decision, or approach to stress-test"`.

## Result

Produce: `Backwards-reasoned failure modes and causes assuming the plan already failed.`.
