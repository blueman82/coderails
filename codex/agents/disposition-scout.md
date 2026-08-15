---
provider: codex
id: disposition-scout
source_kind: agent
graph_role: S2.6
required_inputs: [Phase 1 plan, retired code paths]
output_contract: clean-break or preserve-compat recommendation per retirement unit with evidence and flip-condition.
status: active
---

# disposition-scout

This is the native Codex implementation for `disposition-scout`.

## Execution

Act as the named specialist for the supplied scope. Read relevant evidence, make only the requested recommendation or change, and return the declared output contract with evidence and remaining risks.

## Inputs

Required: `[Phase 1 plan, retired code paths]`.

## Result

Produce: `clean-break or preserve-compat recommendation per retirement unit with evidence and flip-condition.`.
