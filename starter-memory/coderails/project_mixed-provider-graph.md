---
name: mixed-provider-graph-policy-superseded
description: Superseded historical design; replaced by independent Claude and Codex plugins with no cross-provider review.
type: project
---

# Mixed-Provider Graph Policy

> **SUPERSEDED:** Do not build this design. PR #427 removed mixed-provider routing and inspection. The current direction is in `project_codex-claude-graph-parity.md`. Each plugin operates independently with the same graph behavior. There is no provider handoff or cross-review.

## Goal

Extend Coderails so Claude and Codex can independently examine the output of selected graph steps. Keep each provider's own runtime. A step can continue only when it satisfies the configured policy for cross-provider inspection.

## Decisions

- The owner approved explicit provider-specific entries in `skills/index.yaml`. Each provider uses its own routing.
- Mixed mode is one more graph policy, not a replacement for provider-specific routing.
- The preferred mixed mode is parallel inspection. One provider can do the work for a step. Claude and Codex then examine the frozen output independently.
- Reviewers get the same frozen input or artifact. Each submits its verdict without seeing the other verdict. Each writes its own record.
- By default, release requires unanimous approval. If the providers disagree, record a durable hard stop for adjudication.
- In a new neutral session, write and freeze the shared contract and the tests for accepting it. Then start provider implementation.
- Do the Claude and Codex work independently. Each provider owns its worktree.
- Run the last checks independently of the two implementers. In a new verification session, run the mechanical tests. A human resolves substantive disagreements.

## Constraints

- Do not merge Claude and Codex runtimes into one implementation or import one provider's runtime from the other.
- Do not make the active Claude follow-on worker or the prior Codex session unilaterally define shared graph semantics.
- Provider-specific routing, a fixture, and a marker for a completed invocation do not prove that cross-provider inspection occurred.
- Dual execution gives stronger assurance than inspection by the two providers but costs more. Add an explicit step to compare results and adjudicate. The default uses a different mode.

## Schema / Taxonomy

Candidate graph policy values:

- `single` uses one configured provider to do the work or examine the node.
- `parallel-review` lets Claude and Codex independently examine the same frozen artifact for a step. A join applies the release policy.
- `dual-execution` lets the two providers make outputs independently. A step compares the outputs and adjudicates disagreements.

Candidate routing record

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

- `skills/index.yaml` gives provider-specific routing entries and rules for resolving ambiguity.
- `codex/runtime/graph.py` defines Codex graph node, wave, join, and run record semantics.
- `skills/agentic-loop/execution-graph.md`: shared graph dispatch and join-release contract.
- `hooks/scripts/lib/graph_dispatch.sh`: Claude-owned dispatch runtime. Do not edit from Codex work.
- `codex/runtime/codex_exec.py`: Codex-native invocation boundary.

## Done so far

- PR #413 Codex live graph work merged to `main` as merge commit `a4d0067e`. At this checkpoint `main` was at `cbfa64a6`.
- Claude PRs #411 and #412 merged. The Claude S9/J12 wiring continues on its own.
- The owner approved provider-specific routing and the mixed-provider direction.
- No mixed-provider runtime implementation has started.

## Next steps

1. In a new neutral session, examine the current graph and index contracts. Write a minimal mixed-mode design and freeze the task evals.
2. Specify shared record fields for reviewer inputs, each provider's outputs, join policy, disagreement, and retries. Include records bound to each run.
3. Use Claude-owned and Codex-owned worktrees for implementation. The sets of runtime files must have no overlap.
4. Have a new verifier independently test a live mixed Claude and Codex run. Check for artifacts from the two providers and a passing join.
5. Before merge, have the human owner adjudicate all substantive provider disagreements.

## Open questions

- Which modes can the first implementation use: `parallel-review` only, or `parallel-review` and `dual-execution`?
- Which graph steps warrant inspection by the two providers?
- Can a third party adjudicate bounded classes of results, or must a human own all disagreements?
