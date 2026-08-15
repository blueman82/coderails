---
provider: codex
id: wiki-ingest
source_kind: skill
graph_role: S9-wiki
required_inputs: [PR number or description of the change to record]
output_contract: Wiki pages created or updated in the project's LLM Wiki documenting a merged change.
status: active
---

# wiki-ingest

This is the native Codex implementation for `wiki-ingest`.

## Execution

Apply this capability to the current request and available workspace state. Inspect relevant evidence before making claims, keep scope bounded by the request, and return the declared output contract.

## Inputs

Required: `[PR number or description of the change to record]`.

## Result

Produce: `Wiki pages created or updated in the project's LLM Wiki documenting a merged change.`.
