---
provider: codex
id: verify-merged-pr
source_kind: skill
graph_role: G12
required_inputs: [PR number or merge claim to verify]
output_contract: Confirms a PR's changes are actually on origin/main before anything is built on top of the claim.
status: active
---

# verify-merged-pr

This is the native Codex implementation for `verify-merged-pr`.

## Execution

Apply this capability to the current request and available workspace state. Inspect relevant evidence before making claims, keep scope bounded by the request, and return the declared output contract.

## Inputs

Required: `[PR number or merge claim to verify]`.

## Result

Produce: `Confirms a PR's changes are actually on origin/main before anything is built on top of the claim.`.
