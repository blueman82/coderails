---
provider: codex
id: prep
source_kind: command
graph_role: null
required_inputs: [branch name, optional type/summary/description]
output_contract: Safety branch, new feature/bug branch, and Jira ticket created.
status: active
---

# prep

This is the native Codex implementation for `prep`.

## Execution

Perform the requested operation against the supplied context. Validate inputs before changing state, fail closed on missing prerequisites, and return the declared output contract with exact evidence.

## Inputs

Required: `[branch name, optional type/summary/description]`.

## Result

Produce: `Safety branch, new feature/bug branch, and Jira ticket created.`.
