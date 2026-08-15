---
provider: codex
id: wiki-lint
source_kind: skill
graph_role: null
required_inputs: [existing LLM Wiki vault, optional scope]
output_contract: Audit of wiki quality and structural integrity — contradictions, stale pages, orphans, dead links, coverage gaps.
status: active
---

# wiki-lint

This is the native Codex implementation for `wiki-lint`.

## Execution

Apply this capability to the current request and available workspace state. Inspect relevant evidence before making claims, keep scope bounded by the request, and return the declared output contract.

## Inputs

Required: `[existing LLM Wiki vault, optional scope]`.

## Result

Produce: `Audit of wiki quality and structural integrity — contradictions, stale pages, orphans, dead links, coverage gaps.`.
