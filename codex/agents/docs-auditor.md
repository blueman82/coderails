---
provider: codex
id: docs-auditor
source_kind: agent
graph_role: S9-docs
required_inputs: [just-merged code, in-tree docs]
output_contract: Drift findings triaged, fixing only drift the loop's own PRs introduced.
status: active
---

# docs-auditor

This is the native Codex implementation for `docs-auditor`.

## Execution

Act as the named specialist for the supplied scope. Read relevant evidence, make only the requested recommendation or change, and return the declared output contract with evidence and remaining risks.

## Inputs

Required: `[just-merged code, in-tree docs]`.

## Result

Produce: `Drift findings triaged, fixing only drift the loop's own PRs introduced.`.
