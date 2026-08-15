---
provider: codex
id: wiki-query
source_kind: skill
graph_role: null
required_inputs: [question]
output_contract: Answer grounded in wiki content, optionally rendered as slides or charts.
status: active
---

# wiki-query

This is the native Codex implementation for `wiki-query`.

## Execution

Apply this capability to the current request and available workspace state. Inspect relevant evidence before making claims, keep scope bounded by the request, and return the declared output contract.

## Inputs

Required: `[question]`.

## Result

Produce: `Answer grounded in wiki content, optionally rendered as slides or charts.`.
