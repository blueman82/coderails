---
provider: codex
id: cite-check
source_kind: skill
graph_role: null
required_inputs: [claim to verify]
output_contract: Re-derived claim backed by sources only, no recall or inference.
status: active
---

# cite-check

This is the native Codex implementation for `cite-check`.

## Execution

Apply this capability to the current request and available workspace state. Inspect relevant evidence before making claims, keep scope bounded by the request, and return the declared output contract.

## Inputs

Required: `[claim to verify]`.

## Result

Produce: `Re-derived claim backed by sources only, no recall or inference.`.
