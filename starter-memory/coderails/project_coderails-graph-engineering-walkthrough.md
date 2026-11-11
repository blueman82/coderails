---
name: Coderails graph-engineering walkthrough
description: Current verified baseline and teaching contract for a complete example-first walkthrough of Claude and Codex graph engineering.
type: project
---

# Coderails Graph-Engineering Walkthrough

> Supersession note (2026-09-21): This is the pre-cutover walkthrough baseline. Absolute checkout paths, shell filenames, and provider roles below are historical. The current implementation uses schema 3 and `work_units` that operate independently. It uses provider-native dispatch with explicit instruction bodies. Python graph adapters use pure semantics that each provider materializes independently. Use current source and skills for runnable examples.

## Goal

Teach the full current Coderails graph-engineering loop until the user can teach it to someone else confidently. Start with working examples. Then teach all applicable code paths, documents, hooks, scripts, nodes, edges, waves, retries, and links to run records. Teach each field in each JSON file that the loop writes or reads.

Use the current merged source for this teaching session. Do no implementation work. Teach one small concept at a time.

## Decisions

- Teach inductively: run or inspect a concrete graph example before introducing theory or names.
- Start with a small graph with parallel nodes, a join, and a retry that succeeds after the first try fails. Use existing repository fixtures and scripts. Do not make a new teaching framework.
- Teach the shared graph concept first. Follow the code for Claude and Codex one provider at a time. Each plugin operates independently.
- Claude uses the root plugin and Bash graph helpers. Codex uses `packages/codex/` and native Python graph helpers plus native `spawn_agent` dispatch.
- Coderails uses manual graph orchestration. The model reads readiness, dispatches work that can start, records outcomes, and moves the graph forward. There is no automatic scheduler.
- Run records can substantiate execution. The orchestrator's trust domain includes local hooks and `progress.json`. These checks cannot prevent tampering by the orchestrator.
- PR #458 adds the agreed Claude check. If someone removes one try's record, the loop cannot finish while subsequent records and retry metadata stay unchanged. The disclosed trust limit applies when an orchestrator changes multiple fields it owns together.
- PR #459 adds Claude and Codex instructions for starting in a folder with no Git repository.
- PR #460 adds advisory Codex Superpowers guidance. `graph.py` stays authoritative for readiness. Native `spawn_agent` dispatches work.
- Use merged `main` at `10b0e42a780fba73dd65306d6aa34aa9a2478f98` as the initial walkthrough baseline. Check HEAD again at the start because the repository can move.

## Learning method

In each lesson

1. Show an example or run a small lab.
2. Have the user write what they saw without notes.
3. Derive the theory and terms from the example.
4. Have the user explain the idea aloud or in writing using plain language.
5. Have the user draw and annotate their own diagram.
6. Give one applied task.
7. Test the user directly.
8. Get a Feynman score:
   - Full: move on.
   - Near: reread and explain again before 24 hours elapse.
   - Gist: use a new example and repeat the lab.
   - `Lost`: teach it again from a different source or angle.

End each session with three sentences spoken from memory. Use recall questions without notes at three-day intervals. Reconstruct the full graph diagram from memory weekly. Mix formats when useful. Each study block must have a result that the teacher can see or hear.

## Constraints

- Teach one concept at a time. Wait for the user's answer before moving on.
- Give the meaning of each term before relying on it.
- Teach all facts across the lessons. Do not skip one permanently.
- Distinguish graph data from native provider transcripts. Show who writes each fact and which checks compare them.
- Local record checks share the orchestrator's trust boundary. A dishonest orchestrator can defeat them.
- Do not invent schemas from memory. Before teaching a JSON field, locate its current writer, reader, gate, and test in source.
- Build a field-to-purpose matrix during the walkthrough. For each field, show its function in operation, diagnosis, audit, or ceremony.
- Prefer focused existing tests as labs. Do not run the full guard suite unless a lesson genuinely needs it.
- Use the project wiki for context, but the wiki was last found stale for PRs #458-#460. Current source and focused tests decide current behaviour.
- Keep the existing untracked `.coderails/` and `.tmp` paths. Do not edit source or make a worktree during teaching. Wait for the user to authorize implementation.
- Distinguish a repository merge from a runtime check of the installed plugin when that affects the lesson.

## Schema / Taxonomy

Use current source to derive the fields, formats, and readers for all these records:

- `progress.json` records loop identity, status, revision, work roster, graph nodes, edges, readiness, and the active wave. It also records wave history, node outcomes, retry data, and worker records.
- `evals.json`: frozen success checks, scope, SHA binding, commands, negative controls, grading, result, and verification level.
- `proof.json` records frozen proofs, execution status, transcript observations, withdrawals, and how each proof counts when the loop ends.
- `retro.json`: schema, lessons, model use, cost data, and teardown result.
- Native provider transcripts and dispatch and end envelopes substantiate execution. Distinguish these sources from loop-owned JSON.
- `standing-orders.md` and learned error patterns are durable learning inputs. They do not control the graph through JSON.

For each field, record who owns and writes it, who reads it, and the validation rule. Record its effect on readiness or the end of the loop. Record test coverage. Show the effects of a missing, malformed, stale, or changed field.

## Key files

### Repository contract

- `/Users/garyharr/Github/coderails/AGENTS.md` describes the providers, hook map, graph runtime, trust boundaries, and workflow rules.
- `/Users/garyharr/Github/coderails/.coderails/workflow.config.yaml` is the canonical project config if the project has one. Teach it apart from graph data.

### Claude graph implementation

- `/Users/garyharr/Github/coderails/skills/agentic-loop/SKILL.md` — complete Claude loop phases and orchestration contract.
- `/Users/garyharr/Github/coderails/skills/agentic-loop/execution-graph.md` — graph concepts and execution rules.
- `/Users/garyharr/Github/coderails/skills/agentic-loop/loop-state.md` defines the durable graph record contract.
- `/Users/garyharr/Github/coderails/skills/agentic-loop/phases-setup.md` documents setup and the local-repository bootstrap in PR #459.
- `/Users/garyharr/Github/coderails/skills/agentic-loop/retry-until-green.md` — retry lifecycle.
- `/Users/garyharr/Github/coderails/skills/agentic-loop/phase-4b-review.md` documents reviewer checks and the handoff of their records.
- `/Users/garyharr/Github/coderails/skills/agentic-loop/finishing-out.md` and `teardown.md` document how to finish, run proof, record the retro, and clean up.
- `/Users/garyharr/Github/coderails/hooks/scripts/lib/graph_readiness.sh` — node readiness.
- `/Users/garyharr/Github/coderails/hooks/scripts/lib/graph_dispatch.sh` — wave begin/record and durable wave history.
- `/Users/garyharr/Github/coderails/hooks/scripts/lib/graph_executor.sh` — execution helper flow.
- `/Users/garyharr/Github/coderails/hooks/scripts/lib/graph_evidence.sh` provides shared operations on worker records.
- `/Users/garyharr/Github/coderails/hooks/scripts/lib/graph_evidence_bind.sh` connects native Claude transcript records to nodes in the graph.
- `/Users/garyharr/Github/coderails/hooks/scripts/lib/graph_evidence_revalidate.sh` checks worker records again before the loop ends. It has the PR #458 retry-sequence check.
- `/Users/garyharr/Github/coderails/hooks/scripts/loop_dispatch_guard.sh`, `loop_state_guard.sh`, and `loop_stall_guard.sh` — dispatch and stop-time enforcement.
- `/Users/garyharr/Github/coderails/hooks/hooks.json` — lifecycle registration for the Claude plugin.

### Codex graph implementation

- `/Users/garyharr/Github/coderails/packages/codex/skills/agentic-loop/SKILL.md` — native Codex phases, dispatch rules, and PR #460 Superpowers guidance.
- `/Users/garyharr/Github/coderails/packages/codex/skills/agentic-loop/scripts/graph.py` has commands for graph data, readiness, planning, waves, retries, and recording.
- `/Users/garyharr/Github/coderails/packages/codex/skills/agentic-loop/scripts/graph_evidence.py` connects worker records to nodes and checks them again before the loop ends.
- `/Users/garyharr/Github/coderails/packages/codex/skills/agentic-loop/scripts/graph_identity.py` handles canonical worker-record identity and shape.
- `/Users/garyharr/Github/coderails/packages/codex/hooks/hooks.json` — Codex lifecycle registration.
- `/Users/garyharr/Github/coderails/packages/codex/hooks/scripts/graph_completion_guard.sh` and `loop_dispatch_guard.sh` gate the end of native execution and native dispatch.

### Best existing labs and checks

- `/Users/garyharr/Github/coderails/hooks/scripts/tests/graph_two_unit_fanout.test.sh` — simple fan-out example.
- `/Users/garyharr/Github/coderails/hooks/scripts/tests/graph_dispatch_acceptance.test.sh` tests the full dispatch and recording flow.
- `/Users/garyharr/Github/coderails/hooks/scripts/tests/graph_dispatch_j12_s9.test.sh` — larger join/sequence shape.
- `/Users/garyharr/Github/coderails/hooks/scripts/tests/graph_dispatch_complete.test.sh` checks worker records again at the end. It tests wave history and required retry records.
- `/Users/garyharr/Github/coderails/hooks/scripts/tests/graph_readiness.test.sh` — readiness examples.
- `/Users/garyharr/Github/coderails/hooks/scripts/tests/graph_evidence.test.sh` and `graph_evidence_forgery.test.sh` test worker identity records and rejected shapes.
- `/Users/garyharr/Github/coderails/packages/tests/codex_native_package.test.sh` tests the Codex package and instruction contract, with PR #460 guidance.

## Done so far

- The handoff records the user's learning method for this walkthrough.
- PR #458 merged at `3fdf4827`. The merged source passed the targeted Claude retry record test. If the two tries have records, the loop finishes. If someone removes the first record, the loop cannot finish.
- The hand-written `graded_at` timestamp for PR #458 could not occur and its test count was stale. Claude reported a public correction and creation of SO-108. The code repair did not change.
- PR #459 merged at `7a9b57b3`. Its local-repository bootstrap instructions are on `main`.
- PR #460 merged at `10b0e42a`. The audit independently found equal SHAs for local `HEAD` and `origin/main`. The PR does not change Claude retry record code.
- The tracked worktree was clean at handoff. The `.coderails/` and `.tmp` paths were untracked and untouched.

## Next steps

1. Check local `HEAD`, `origin/main`, and tracked worktree status again. Do not pull or edit unless necessary.
2. Use `wiki-query` for project context. The wiki omits PRs #458-#460. Check the current source for facts about them.
3. Start Lesson 1 immediately. Do not give a large curriculum first.
4. In the Lesson 1 lab, show a small graph with two parallel workers that join into one last node. Use an existing targeted fixture. Show its input and resulting `progress.json`. Have the user draw and label the nodes, edges, nodes that can start, active wave, and join.
5. Get written recall, a Feynman explanation, one change to the example, and a direct test. Get a score of Full, Near, Gist, or `Lost`.
6. Teach setup, planning, readiness, waves, native dispatch, result recording, retries, and joins in sequence. Continue with transcript records, end checks, evals, proofs, retros, `standing-orders.md`, hooks, and cleanup.
7. Follow the same concepts first in Claude Bash and then in Codex Python. Build a table of similarities and differences after examples from the two implementations.
8. Add each generated JSON field to the field-to-purpose matrix as you teach it.
9. Finish with a full explanation without notes, a reconstructed graph diagram, and a practical debugging exercise. Finish the walkthrough when the user and teacher agree that the user can teach Coderails graph engineering confidently.

## Open questions

No blocking questions. Use the example-first sequence above by default. Adapt the next lesson to the user's Feynman score.
