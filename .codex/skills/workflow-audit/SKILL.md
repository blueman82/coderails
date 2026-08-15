---
provider: codex
id: workflow-audit
source_kind: skill
graph_role: null
required_inputs: [recent session records]
output_contract: List of repeated tasks worth turning into skills.
status: active
---

# workflow-audit

This is the native Codex implementation for `workflow-audit`.

## Execution

Apply this capability to the current request and available workspace state. Inspect relevant evidence before making claims, keep scope bounded by the request, and return the declared output contract.

## Inputs

Required: `[recent session records]`.

## Result

Produce: `List of repeated tasks worth turning into skills.`.
