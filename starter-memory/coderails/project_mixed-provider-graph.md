---
name: mixed-provider-graph-policy-superseded
description: Superseded design for mixed-provider review. Independent Claude and Codex plugins replaced it; they do not cross-review.
type: project
---

# Mixed-Provider Graph Policy

> **SUPERSEDED:** Do not implement this design. PR #427 removed mixed-provider
> routing and review. See `project_codex-claude-graph-parity.md` for the
> independent plugin direction. The providers do not hand work to each
> other or cross-review.

## Goal

The old goal was independent Claude and Codex review of selected graph
stages. Each provider would keep its own runtime. A stage would proceed
only after it met the cross-provider review policy.

## Decisions

- The owner approved provider-specific entries in `skills/index.yaml`.
  Neither provider route would win for all tasks.
- Mixed mode is an additional graph policy, not a replacement for provider-specific routing.
- The preferred mixed mode was parallel review. One provider would build
  a stage. Both providers would review its frozen output independently.
- Reviewers would receive the same frozen input. Each would submit a
  verdict and evidence before seeing the other's verdict.
- The proposed release policy required unanimous approval. A disagreement
  would create a durable hard stop for adjudication.
- A fresh neutral session would define the shared contract and freeze
  acceptance tests before implementation.
- Claude and Codex implementations would use separate provider worktrees.
- A fresh session would run mechanical acceptance. A human would resolve
  substantive disagreements.

## Constraints

- Do not merge the provider runtimes. Do not import one runtime from the other.
- Do not let one provider's worker define the shared graph semantics alone.
- A route, fixture, or invocation marker does not prove cross-provider review.
- Dual execution would cost more than dual review. It would need a
  comparison and adjudication stage. It was not the default.

## Schema / Taxonomy

Candidate graph policy values:

- `single`: one configured provider executes/reviews the node.
- `parallel-review`: Both providers review the same frozen stage artifact.
  A join applies the release policy.
- `dual-execution`: Both providers produce outputs independently. A
  comparison and adjudication stage evaluates them.

Candidate route shape:

```yaml
U4b-review:
  mode: parallel-review
  reviewers:
    - provider: claude
      route: agents/spec-reviewer.md
    - provider: codex
      route: codex/agents/spec-reviewer.md
  join:
    policy: unanimous
```

## Key files

- `skills/index.yaml`: provider-specific route declarations and disambiguation contract.
- `codex/runtime/graph.py`: Codex graph node, wave, join, and evidence semantics.
- `skills/agentic-loop/execution-graph.md`: shared graph dispatch and join-release contract.
- `hooks/scripts/lib/graph_dispatch.sh`: Claude-owned dispatch runtime; do not edit from Codex work.
- `codex/runtime/codex_exec.py`: Codex-native invocation boundary.

## Done so far

- PR #413 merged the Codex live graph work at `a4d0067e`. At the time of
  this record, `main` had later advanced to `cbfa64a6`.
- Claude PRs #411 and #412 merged. Claude continued S9/J12 wiring separately.
- The owner approved provider-specific routing and the mixed-provider direction.
- No mixed-provider runtime implementation has started.

## Next steps

1. In a fresh neutral session, inspect the graph and index contracts. Write
   a minimal mixed-mode design and freeze task evals.
2. Define the record shape for reviewer inputs, outputs, joins, disagreement,
   retries, and evidence bound to a run.
3. Use separate Claude and Codex worktrees. Keep provider runtime files
   disjoint.
4. Run an independent verifier against a real mixed-provider path. Require
   evidence from both providers and a passing join.
5. Ask the human owner to resolve substantive disagreements before merge.

## Open questions

- Whether the first implementation should support only `parallel-review` or also `dual-execution`.
- Which graph stages are high-value enough to receive mixed review.
- Whether disagreement is always human-owned or may use a third adjudicator for bounded classes of findings.
