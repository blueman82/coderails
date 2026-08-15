---
provider: codex
id: workflow
source_kind: command
graph_role: null
required_inputs: [branch, description]
output_contract: "Full feature workflow orchestrated end-to-end: prep, push, review, merge, wiki-ingest/lint."
status: active
---

# workflow

This is the native Codex implementation for `workflow`.

## Execution

Perform the requested operation against the supplied context. Validate inputs before changing state, fail closed on missing prerequisites, and return the declared output contract with exact evidence.

## Inputs

Required: `[branch, description]`.

## Result

Produce: `"Full feature workflow orchestrated end-to-end: prep, push, review, merge, wiki-ingest/lint."`.
