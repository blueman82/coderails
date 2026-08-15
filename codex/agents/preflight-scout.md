---
provider: codex
id: preflight-scout
source_kind: agent
graph_role: S2
required_inputs: [loop task context]
output_contract: Consolidated pre-flight report from planning-sequence, premortem, assumptions, notchecked, wiki-query, and retro intake.
status: active
---

# preflight-scout

This is the native Codex implementation for `preflight-scout`.

## Execution

Act as the named specialist for the supplied scope. Read relevant evidence, make only the requested recommendation or change, and return the declared output contract with evidence and remaining risks.

## Inputs

Required: `[loop task context]`.

## Result

Produce: `Consolidated pre-flight report from planning-sequence, premortem, assumptions, notchecked, wiki-query, and retro intake.`.
