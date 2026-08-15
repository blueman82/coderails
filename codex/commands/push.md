---
provider: codex
id: push
source_kind: command
graph_role: U6
required_inputs: [commit message (optional), working tree changes]
output_contract: Changes added, committed, pushed, and a PR created.
status: active
---

# push

This is the native Codex implementation for `push`.

## Execution

Perform the requested operation against the supplied context. Validate inputs before changing state, fail closed on missing prerequisites, and return the declared output contract with exact evidence.

## Inputs

Required: `[commit message (optional), working tree changes]`.

## Result

Produce: `Changes added, committed, pushed, and a PR created.`.
