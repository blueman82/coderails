---
provider: codex
id: init
source_kind: command
graph_role: null
required_inputs: [project-name (optional)]
output_contract: Scaffolded workflow.config.yaml for the current project.
status: active
---

# init

This is the native Codex implementation for `init`.

## Execution

Perform the requested operation against the supplied context. Validate inputs before changing state, fail closed on missing prerequisites, and return the declared output contract with exact evidence.

## Inputs

Required: `[project-name (optional)]`.

## Result

Produce: `Scaffolded workflow.config.yaml for the current project.`.
