---
provider: codex
id: docs-sync
source_kind: skill
graph_role: S9-docs
required_inputs: [git-tracked docs, current codebase state]
output_contract: Scheduled nightly drift audit that edits, pushes, reviews, and self-merges a fix when drift is found.
status: active
---

# docs-sync

This is the native Codex implementation for `docs-sync`.

## Execution

Apply this capability to the current request and available workspace state. Inspect relevant evidence before making claims, keep scope bounded by the request, and return the declared output contract.

## Inputs

Required: `[git-tracked docs, current codebase state]`.

## Result

Produce: `Scheduled nightly drift audit that edits, pushes, reviews, and self-merges a fix when drift is found.`.
