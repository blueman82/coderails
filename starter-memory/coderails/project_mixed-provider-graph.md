---
name: mixed-provider-graph-policy-superseded
description: Superseded historical design; replaced by independent Claude and Codex plugins with no cross-provider review.
type: project
---

# Mixed-Provider Graph Policy

> **SUPERSEDED:** Do not implement this design. PR #427 removed mixed-provider
> routing and review. The current direction is recorded in
> `project_codex-claude-graph-parity.md`: independent plugins with matching graph
> behaviour and no provider handoff or cross-review.

## Goal

Extend Coderails so selected graph stages can be reviewed independently by Claude and Codex, while preserving separate provider runtimes. A stage may proceed only after the configured cross-provider review policy is satisfied.

## Decisions

- The owner approved explicit provider-specific entries in `skills/index.yaml`; neither provider route wins globally.
- Mixed mode is an additional graph policy, not a replacement for provider-specific routing.
- The preferred mixed mode is parallel review: one provider may implement a stage, while Claude and Codex independently review the frozen output.
- Reviewers receive the same frozen input/artifact, do not see each other's verdict before submitting, and write separate evidence.
- The default release policy should be unanimous approval; disagreement becomes a durable hard-stop for adjudication.
- A fresh neutral session must design and freeze the shared contract and acceptance tests before provider implementations begin.
- Claude and Codex implementations are separate workstreams in separate provider-owned worktrees.
- Final verification must be independent of both implementers: a fresh verification session runs mechanical acceptance and a human resolves substantive disagreements.

## Constraints

- Do not merge Claude and Codex runtimes into one implementation or import one provider's runtime from the other.
- Do not make the active Claude follow-on worker or the prior Codex session unilaterally define shared graph semantics.
- Do not treat a provider-specific route, a fixture, or a successful invocation marker as proof that cross-provider review happened.
- Dual execution is stronger but more expensive than dual review and requires an explicit comparison/adjudication stage; it is not the default.

## Schema / Taxonomy

Candidate graph policy values:

- `single`: one configured provider executes/reviews the node.
- `parallel-review`: Claude and Codex independently review the same frozen stage artifact; a join applies the release policy.
- `dual-execution`: both providers independently produce outputs; a comparison/adjudication stage evaluates them.

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

- PR #413 Codex live graph work merged to `main` as merge commit `a4d0067e`; current `main` later advanced to `cbfa64a6`.
- Claude PRs #411 and #412 merged; Claude is continuing S9/J12 wiring separately.
- The owner approved provider-specific routing and the mixed-provider direction.
- No mixed-provider runtime implementation has started.

## Next steps

1. In a fresh neutral session, inspect the current graph/index contracts and write a minimal mixed-mode design plus frozen task-evals.
2. Decide the exact shared record shape for reviewer inputs, independent outputs, join policy, disagreement, retries, and run-bound evidence.
3. Split implementation into Claude-owned and Codex-owned worktrees with disjoint provider runtime files.
4. Run a fresh independent verifier against a real mixed Claude+Codex acceptance path; require both provider artifacts and a passing join.
5. Have the human owner adjudicate any substantive provider disagreement before merge.

## Open questions

- Whether the first implementation should support only `parallel-review` or also `dual-execution`.
- Which graph stages are high-value enough to receive mixed review.
- Whether disagreement is always human-owned or may use a third adjudicator for bounded classes of findings.
