---
provider: codex
id: handoff
source_kind: skill
graph_role: null
required_inputs: [current session context]
output_contract: Structured memory file and continuation prompt for carrying work into a new session.
status: active
---

# handoff

This is the native Codex implementation for `handoff`.

## Execution

Apply this capability to the current request and available workspace state. Inspect relevant evidence before making claims, keep scope bounded by the request, and return the declared output contract.

## Inputs

Required: `[current session context]`.

## Result

Produce: `Structured memory file and continuation prompt for carrying work into a new session.`.
