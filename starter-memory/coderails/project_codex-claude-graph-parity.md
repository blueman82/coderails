---
name: codex-claude-graph-parity
description: Historical graph-parity baseline; current Python graph semantics and native provider contracts supersede its implementation notes.
type: project
---

# Codex and Claude graph parity

> Historical baseline. The current implementation follows
> `docs/superpowers/plans/2026-09-03-provider-graph-alignment-implementation.md`
> and `skills/agentic-loop/execution-graph.md`: one maintained pure Python
> semantic core at `packages/graph-semantics/graph_semantics.py`, exact copies
> inside each independent plugin, and provider-local dispatch, locks and native
> evidence. Stored progress uses schema 3 only. Native provider role labels and
> explicit instruction delivery replace mandatory custom worker names. The
> shell paths, initial checkout constraints and defect inventory below record
> the earlier baseline; they are not current runtime instructions.

## Goal

Make the independent Codex plugin perform the same graph engineering as the
independent Claude plugin: the same graph state, readiness rules, waves, joins,
retries, hard stops, completion checks, resume behaviour and proof tests. Keep
provider dispatch native and separate: Claude uses `Agent`; Codex uses
`spawn_agent`. Neither provider calls, routes to, or reviews through the other.

Parity alone is not enough if it copies known Claude defects. Treat the work as
two explicit acceptance milestones: first prove matching behaviour, then prove
the known graph gaps are closed for both providers. Completion means both
milestones pass in clean, fresh provider sessions.

## Decisions

- PR #427 is merged at `97c026eb4ea059e07b563f36cae52eb12e155372`.
- The Claude plugin remains at the repository root. The Codex plugin remains at
  `packages/codex`.
- The providers must share graph semantics, not a runtime. Keep two independent
  implementations and provider-local hooks, skills, agents and scripts.
- Do not restore `skills/index.yaml`, shared provider routing, mixed-provider
  review, provider handoffs, nested `codex exec`, the deleted custom Codex
  runtime, a daemon or an MCP scheduler.
- Use the surviving Claude graph as the behavioural source, but do not copy its
  verified defects into Codex.
- Both providers must use the same state meanings: nodes, edges, all-input
  joins, pending/running/done/skipped/hard-stop states, an active wave, retry
  attempts, evidence, completion and teardown.
- Both providers remain manually operated at the native-agent boundary. Graph
  code calculates and records work; the active provider session performs its
  own native agent calls.
- Keep review provider-local. Claude uses Claude reviewers. Codex uses Codex
  reviewers. Review and merge evidence may be graph nodes, but never a
  cross-provider join.
- Preserve the user's three-agent concurrency limit unless explicitly changed.

## Constraints

- Start from a clean checkout containing merge `97c026e`. The current local
  `main` may still be behind `origin/main`; verify before creating a worktree.
- Do not alter the working Claude plugin merely to make packaging symmetrical.
  Claude changes must fix a proved graph defect or establish the matching graph
  contract.
- Do not infer equal behaviour from matching agent names, skill names or hook
  counts. Prove state transitions and provider-native dispatch in tests.
- Plugin discovery, custom-agent installation and hook trust are already solved
  by PR #427. Do not reopen them unless a parity test proves a regression.
- Codex hooks run only after the user trusts them through `/hooks`; fresh-session
  verification must include that step.
- This handoff authorises planning and implementation of graph parity only. It
  does not authorise cross-review or a shared provider runtime.

## Schema / Taxonomy

The matching behavioural contract must cover:

| Area | Required behaviour in both providers |
|---|---|
| State | One durable loop record with session/loop ownership, revision, nodes, edges, joins, active wave, decisions and evidence |
| Readiness | Unknown or malformed nodes fail closed; a node is ready only when every required predecessor has succeeded |
| Dispatch | Resolve one complete ready wave, record it as active/running, then use the provider's native agent tool |
| Recording | Accept exactly the active wave's result keys; reject partial or extra results without changing state |
| Retry | A retryable failure returns to pending, increments attempts and preserves evidence; exhaustion becomes hard-stop |
| Join | All-input joins release only after every input succeeds; release must be deterministic, not forgotten prose |
| Resume | A fresh or compacted session discovers the active loop, running wave, ready work and hard-stop reason |
| Completion | Cannot finish with pending/running/hard-stop nodes, unreleased joins, missing proof/evidence or missing retro |
| Dispatch boundary | Claude calls `Agent`; Codex calls `spawn_agent`; graph code never starts another provider session |

## Known graph gaps to close

Verified against merged commit `97c026e`:

1. Claude retryable failures become `running`, but readiness only selects
   `pending`/`ready`, so failed nodes can disappear from future waves.
2. Claude readiness can approve an unknown node and does not fully validate the
   graph before answering.
3. Claude does not record an in-flight wave; a restart can duplicate dispatch,
   and partial result sets are not checked against the planned wave.
4. Claude's completion-marker order can bypass teardown checks on the completion
   turn.
5. Claude completion checks `work_units` but not unfinished graph nodes or joins.
6. A stale loop evaluation can approve a later re-armed loop because artifacts
   lack a unique loop identity.
7. Claude's in-process loop-worker gate allows missing or foreign loop state.
8. Claude sandboxed workers bypass the in-process loop dispatch gate.
9. Codex has no mechanical graph state, readiness calculator, active-wave
   recorder, retry counter, join release or graph completion gate.
10. Codex's current `progress.json` is optional and explicitly described as a
    checkpoint, not a scheduler or enforcement system.
11. Codex package tests prove package shape and instruction wording, not graph
    behaviour.

Deliberate limits, not gaps:

- Native agent dispatch remains model-driven for both providers.
- No automatic background scheduler.
- No shared runtime, provider router or cross-provider review.
- Provider-local review and merge workflows remain multi-step boundaries.

## Key files

Claude source and behaviour:

- `skills/agentic-loop/SKILL.md`: Claude graph operating discipline.
- `skills/agentic-loop/execution-graph.md`: graph shape, waves and joins.
- `skills/agentic-loop/loop-state.md`: durable state and completion contract.
- `skills/agentic-loop/retry-until-green.md`: retry semantics.
- `skills/agentic-loop/phases-setup.md`: initial graph state creation.
- `skills/agentic-loop/teardown.md`: proof, retro and completion sequence.
- `hooks/scripts/lib/graph_readiness.sh`: current readiness calculation.
- `hooks/scripts/lib/graph_executor.sh`: locked graph-state updates.
- `hooks/scripts/lib/graph_dispatch.sh`: ready-wave planning, routing and result recording.
- `hooks/scripts/lib/loop_state_common.sh`: shared loop-state and completion functions.
- `hooks/scripts/loop_dispatch_guard.sh`: Claude Agent dispatch gate.
- `hooks/scripts/loop_state_guard.sh`: state/eval Stop guard.
- `hooks/scripts/loop_stall_guard.sh`: completion, proof and retro guard.
- `scripts/sandbox/spawn-sandboxed-worker.sh`: separate Claude worker path that
  must use the same graph/eval decision.

Codex target:

- `packages/codex/skills/agentic-loop/SKILL.md`: currently instruction-only;
  must operate the matching graph contract around native agent calls.
- `packages/codex/hooks/hooks.json`: provider-native registration point for
  resume/completion graph hooks.
- `packages/codex/hooks/scripts/inject_bootstrap.sh`: report active graph state
  after session start, resume or compaction.
- `packages/codex/hooks/scripts/lib/hook_common.sh`: reuse for Codex hook input
  and output handling.
- `packages/codex/skills/workflow/SKILL.md`: provider-local review wave and
  review/eval/merge nodes.
- `packages/codex/scripts/merge.sh`: current-head review/eval/smoke merge gates;
  reuse, do not rebuild.
- `packages/codex/agents/*.toml`: native Codex workers/reviewers; already installed.
- `packages/tests/codex_native_package.test.sh`: preserve removal of unsupported
  mixed/runtime paths while adding graph-package assertions.
- `packages/tests/codex_hooks.test.sh`: replace only the obsolete expectation
  that all graph hooks are absent.

Tests to inspect and extend:

- `hooks/scripts/tests/graph_readiness.test.sh`
- `hooks/scripts/tests/graph_dispatch.test.sh`
- `hooks/scripts/tests/graph_dispatch_acceptance.test.sh`
- `hooks/scripts/tests/graph_dispatch_j12_s9.test.sh`
- `hooks/scripts/tests/graph_executor.test.sh`
- `hooks/scripts/tests/graph_executor_concurrency.test.sh`
- `hooks/scripts/tests/graph_executor_stale_check.test.sh`
- `hooks/scripts/tests/loop_dispatch_guard.test.sh`
- `hooks/scripts/tests/loop_stall_guard.test.sh`
- `hooks/scripts/tests/loop_state_guard_evals.test.sh`
- `scripts/sandbox/tests/spawn_sandboxed_worker.test.sh`
- New Codex provider-local graph behaviour test under `packages/tests/`.

## Done so far

- PR #427 created and merged the separate native Codex plugin.
- The Claude root plugin remains provider-owned and functional.
- The Codex package now has 37 skills, 10 custom agents, native hooks and
  provider-local workflow scripts.
- Shared routing, mixed review and the custom Codex runtime were removed.
- Fresh Codex sessions discovered `coderails-codex:agentic-loop` before merge.
- Three read-only audits compared pre-PR `dfcd6366` with merged `97c026e`.
- The audits proved Claude retained a manually operated mechanical graph while
  Codex currently has instruction-only dependency orchestration.
- No graph-parity implementation has started.
- The stale `project_mixed-provider-graph.md` memory has been marked superseded.

## Next steps

1. Fetch `origin/main`, verify merge `97c026e` is present, require a completely
   clean checkout, then create a dedicated feature worktree and branch.
2. Freeze provider-parity success tests before implementation. Use the same
   behavioural cases for both providers: malformed graph, unknown node,
   `A || B -> join -> C`, active-wave exactness, retry success/exhaustion,
   restart/resume and blocked early completion.
3. Fix the verified Claude graph defects with the smallest changes to the
   existing shell helpers and hooks. Do not add dispatch automation.
4. Implement the same contract inside the Codex skill package. Prefer a small
   deterministic skill-local helper and provider-native hooks; do not recreate
   `packages/codex/runtime/` or add manifest fields.
5. Update the Codex skill so graph operations surround `spawn_agent`,
   `wait_agent`, result verification and `close_agent`. Keep `update_plan` as a
   display, not the durable source of truth.
6. Add Codex session-start discovery and a provider-native Stop guard for active,
   paused, hard-stop and complete states.
7. Run provider-local unit and package tests, strict changed-file quality, a
   clean temporary Codex install, and fresh Claude and Codex sessions.
8. In each fresh session run the harmless graph `A || B -> join -> C`. Prove the
   same state transitions and completion blocks, while observing Claude `Agent`
   calls and Codex `spawn_agent` calls.
9. Report parity separately from hardening: matching current behaviour is not
   enough unless every known gap above is either fixed or explicitly accepted.

## Open questions

- Implementation language/location for the Codex helper: port the existing
  Claude shell semantics into a skill-local script, or use a small Python helper.
  Behaviour must match either way; do not create a general runtime package.
- Whether to ship parity and graph hardening in one PR or two ordered PRs. The
  final acceptance target is the same.
