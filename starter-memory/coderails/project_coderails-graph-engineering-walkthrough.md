---
name: Coderails graph-engineering walkthrough
description: Current verified baseline and teaching contract for a complete example-first walkthrough of Claude and Codex graph engineering.
type: project
---

# Coderails Graph-Engineering Walkthrough

> Supersession note (2026-09-21): This is the pre-cutover walkthrough baseline. Absolute checkout paths, shell filenames, and provider-role assumptions below are historical. The current implementation uses schema 3, independent work_units, provider-native dispatch with explicit instruction bodies, and Python graph adapters over independently materialized pure semantics. Use current source and skills for runnable examples.

## Goal

Teach the user the complete current Coderails graph-engineering loop until they can explain it confidently to another person. Cover the working examples first, then every relevant code path, document, hook, script, node, edge, wave, retry, evidence link, and every field in every JSON file created or consumed by the loop.

This is a teaching session, not an implementation session. Work from the current merged source and move one small concept at a time; never dump the whole architecture at once.

## Decisions

- Teach inductively: run or inspect a concrete graph example before introducing theory or names.
- Start with a small graph containing parallel nodes, a join, and one failed-then-successful retry. Reuse the repository's existing fixtures and scripts; do not create a new teaching framework.
- Teach the shared graph idea first, then trace the Claude and Codex implementations separately. They are independent provider plugins and must not be presented as one mixed implementation.
- Claude uses the root plugin and Bash graph helpers. Codex uses `packages/codex/` and native Python graph helpers plus native `spawn_agent` dispatch.
- Coderails is manually operated graph engineering. The model reads readiness, dispatches ready work, records outcomes, and advances the graph. There is no automatic scheduler, and the walkthrough must not imply one.
- Evidence-backed graph execution is not tamper-proof security. Local hooks and `progress.json` remain in the orchestrator's trust domain.
- PR #458 closes the agreed Claude gap: deleting one retry attempt's evidence while later evidence and retry metadata remain intact now blocks completion. Coordinated changes to several orchestrator-owned fields remain a disclosed trust-boundary limit.
- PR #459 adds Claude and Codex instructions for starting in a folder that is not yet a Git repository.
- PR #460 adds Codex Superpowers guidance. Superpowers guidance is advisory; `graph.py` remains the readiness authority and native `spawn_agent` remains the dispatcher.
- Use current merged `main` at `10b0e42a780fba73dd65306d6aa34aa9a2478f98` as the initial walkthrough baseline. Recheck HEAD at the start because the repository may move.

## Learning method

For every lesson:

1. Show an example or run a small lab.
2. Ask the user to write what they observed without notes.
3. Derive the theory and terms from the example.
4. Have the user explain the idea aloud or in writing using plain language.
5. Have the user draw and annotate their own diagram.
6. Give one applied task.
7. Test the user directly.
8. Ask for a Feynman score:
   - Full: move on.
   - Near: reread and re-explain within 24 hours.
   - Gist: use a new example and repeat the lab.
   - Lost: teach it again from a different source or angle.

End each session with three sentences spoken from memory. Use no-notes recall questions every three days and reconstruct the full graph diagram from memory weekly. Mix formats when useful, but every study block must produce an observable output.

## Constraints

- Explain one concept at a time and wait for the user's answer before moving on.
- Define every term before relying on it.
- No detail may be permanently skipped, but details should be staged across lessons.
- Do not confuse graph state with native provider transcripts. Explain who writes each fact and which checks compare them.
- Do not call local evidence checks a security boundary or claim complete resistance to a dishonest orchestrator.
- Do not invent schemas from memory. Before teaching a JSON field, locate its current writer, reader, gate, and test in source.
- Build a field-to-purpose matrix during the walkthrough so the user can see whether every stored field is operational, diagnostic, audit-only, or currently ceremonial.
- Prefer focused existing tests as labs. Do not run the full guard suite unless a lesson genuinely needs it.
- Use the project wiki for context, but the wiki was last found stale for PRs #458-#460. Current source and focused tests decide current behaviour.
- Preserve the existing untracked `.coderails/` and `.tmp` paths. Do not edit source or create a worktree for this read-only teaching session unless the user later asks for implementation.
- A repository merge is not an installed-plugin runtime check. State that difference whenever it matters.

## Schema / Taxonomy

The walkthrough must re-derive the exact current shapes and consumers for at least:

- `progress.json`: loop identity, status, revision, work roster, graph nodes, edges, readiness, active wave, wave history, node outcomes, retry state, and worker evidence.
- `evals.json`: frozen success checks, scope, SHA binding, commands, negative controls, grading, result, and verification level.
- `proof.json`: frozen proofs, execution status, transcript observations, withdrawals, and completion disposition.
- `retro.json`: schema, lessons, model use, cost data, and teardown result.
- Native provider transcript records and dispatch/completion envelopes used as evidence. These are evidence sources, not interchangeable with loop-owned JSON.
- `standing-orders.md` and learned failure modes. They are durable learning inputs but are not graph-control JSON.

For every field, record: owner/writer, reader, validation rule, effect on readiness or completion, test coverage, and what happens if absent, malformed, stale, or changed.

## Key files

### Repository contract

- `/Users/garyharr/Github/coderails/AGENTS.md` — provider split, hook map, graph runtime description, trust boundaries, and workflow rules.
- `/Users/garyharr/Github/coderails/.coderails/workflow.config.yaml` — canonical project workflow configuration if present; explain configuration separately from graph state.

### Claude graph implementation

- `/Users/garyharr/Github/coderails/skills/agentic-loop/SKILL.md` — complete Claude loop phases and orchestration contract.
- `/Users/garyharr/Github/coderails/skills/agentic-loop/execution-graph.md` — graph concepts and execution rules.
- `/Users/garyharr/Github/coderails/skills/agentic-loop/loop-state.md` — durable state contract.
- `/Users/garyharr/Github/coderails/skills/agentic-loop/phases-setup.md` — setup, including PR #459 local-repository bootstrap.
- `/Users/garyharr/Github/coderails/skills/agentic-loop/retry-until-green.md` — retry lifecycle.
- `/Users/garyharr/Github/coderails/skills/agentic-loop/phase-4b-review.md` — review phase and evidence handoff.
- `/Users/garyharr/Github/coderails/skills/agentic-loop/finishing-out.md` and `teardown.md` — completion, proof, retro, and cleanup.
- `/Users/garyharr/Github/coderails/hooks/scripts/lib/graph_readiness.sh` — node readiness.
- `/Users/garyharr/Github/coderails/hooks/scripts/lib/graph_dispatch.sh` — wave begin/record and durable wave history.
- `/Users/garyharr/Github/coderails/hooks/scripts/lib/graph_executor.sh` — execution helper flow.
- `/Users/garyharr/Github/coderails/hooks/scripts/lib/graph_evidence.sh` — shared evidence operations.
- `/Users/garyharr/Github/coderails/hooks/scripts/lib/graph_evidence_bind.sh` — binding native Claude transcript evidence to graph nodes.
- `/Users/garyharr/Github/coderails/hooks/scripts/lib/graph_evidence_revalidate.sh` — completion-time evidence revalidation and PR #458 retry-sequence check.
- `/Users/garyharr/Github/coderails/hooks/scripts/loop_dispatch_guard.sh`, `loop_state_guard.sh`, and `loop_stall_guard.sh` — dispatch and stop-time enforcement.
- `/Users/garyharr/Github/coderails/hooks/hooks.json` — lifecycle registration for the Claude plugin.

### Codex graph implementation

- `/Users/garyharr/Github/coderails/packages/codex/skills/agentic-loop/SKILL.md` — native Codex phases, dispatch rules, and PR #460 Superpowers guidance.
- `/Users/garyharr/Github/coderails/packages/codex/skills/agentic-loop/scripts/graph.py` — graph state, readiness, planning, wave, retry, and record commands.
- `/Users/garyharr/Github/coderails/packages/codex/skills/agentic-loop/scripts/graph_evidence.py` — worker evidence binding and completion-time revalidation.
- `/Users/garyharr/Github/coderails/packages/codex/skills/agentic-loop/scripts/graph_identity.py` — canonical evidence identity and shape handling.
- `/Users/garyharr/Github/coderails/packages/codex/hooks/hooks.json` — Codex lifecycle registration.
- `/Users/garyharr/Github/coderails/packages/codex/hooks/scripts/graph_completion_guard.sh` and `loop_dispatch_guard.sh` — native completion and dispatch gates.

### Best existing labs and checks

- `/Users/garyharr/Github/coderails/hooks/scripts/tests/graph_two_unit_fanout.test.sh` — simple fan-out example.
- `/Users/garyharr/Github/coderails/hooks/scripts/tests/graph_dispatch_acceptance.test.sh` — dispatch/record acceptance flow.
- `/Users/garyharr/Github/coderails/hooks/scripts/tests/graph_dispatch_j12_s9.test.sh` — larger join/sequence shape.
- `/Users/garyharr/Github/coderails/hooks/scripts/tests/graph_dispatch_complete.test.sh` — completion revalidation, wave history, and retry-evidence closure.
- `/Users/garyharr/Github/coderails/hooks/scripts/tests/graph_readiness.test.sh` — readiness examples.
- `/Users/garyharr/Github/coderails/hooks/scripts/tests/graph_evidence.test.sh` and `graph_evidence_forgery.test.sh` — evidence identity and rejected shapes.
- `/Users/garyharr/Github/coderails/packages/tests/codex_native_package.test.sh` — Codex package and instruction contract, including PR #460 guidance.

## Done so far

- The user's learning method was saved for this walkthrough.
- PR #458 merged at `3fdf4827`; its exact merged source passed the focused Claude retry-evidence test. The test proves intact two-attempt evidence completes and deletion of attempt-one evidence blocks.
- PR #458's impossible hand-written `graded_at` timestamp and stale test count were identified. Claude reported posting a public correction and creating SO-108; the code fix itself was unaffected.
- PR #459 merged at `7a9b57b3`; its local-repository bootstrap instructions are on `main`.
- PR #460 merged at `10b0e42a`; local `HEAD` and `origin/main` were independently confirmed equal, and it does not touch Claude retry-evidence code.
- The tracked worktree was clean at handoff time. Existing `.coderails/` and `.tmp` paths were untracked and untouched.

## Next steps

1. Recheck local `HEAD`, `origin/main`, and tracked cleanliness. Do not pull or edit unless needed.
2. Use `wiki-query` for project context, but verify current details from source because the wiki lacks PRs #458-#460.
3. Start Lesson 1 immediately; do not present a giant curriculum first.
4. Lesson 1 lab: show a tiny graph with two parallel workers joining into one final node. Use an existing focused fixture, show its input and resulting `progress.json`, and have the user draw and label nodes, edges, ready nodes, active wave, and join.
5. Ask for written recall, Feynman explanation, one applied change to the example, a direct test, and a Full/Near/Gist/Lost score.
6. Continue lesson by lesson through setup, planning, readiness, waves, native dispatch, result recording, retries, joins, transcript evidence, completion revalidation, evals, proofs, retros, standing orders, hooks, and cleanup.
7. Trace the same concepts separately through Claude Bash and Codex Python. Build a precise similarity/difference table only after both implementations have been learned through examples.
8. Build the field-to-purpose matrix for every generated JSON field as the lessons progress.
9. Finish with a no-notes complete explanation, a reconstructed graph diagram, and a practical debugging exercise. The walkthrough is complete only when both user and teacher agree the user can explain Coderails graph engineering confidently.

## Open questions

No blocking questions. Default to the example-first teaching order above and adapt each next lesson from the user's Feynman score.
