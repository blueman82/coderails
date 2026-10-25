---
name: codex-claude-graph-parity
description: Historical Claude and Codex graph-parity baseline. Current Python graph semantics and native provider contracts supersede its implementation notes.
type: project
---

# Codex and Claude graph parity

> Historical baseline. The current implementation follows
> `docs/superpowers/plans/2026-09-03-provider-graph-alignment-implementation.md`
> and `skills/agentic-loop/execution-graph.md`. The current design has one
> maintained Python semantic core at
> `packages/graph-semantics/graph_semantics.py`. Each independent plugin has
> an exact copy. Dispatch, locks, and native evidence remain provider-local.
> Stored progress uses schema 3 only. Native role labels and explicit
> instructions replace mandatory custom worker names. The shell paths,
> checkout limits, and defects below describe the earlier baseline. They
> are not current runtime instructions.

## Goal

The historical goal was matching graph behavior in the independent plugins.
It covered graph state, readiness, waves, joins, retries, hard stops,
completion, resume, and proofs. Claude would dispatch with `Agent`.
Codex would dispatch with `spawn_agent`. Neither provider would call or
review through the other.

The old plan had two acceptance milestones. First, prove matching behavior.
Second, close known graph gaps in both providers. Both milestones required
fresh, clean provider sessions.

## Decisions

- PR #427 is merged at `97c026eb4ea059e07b563f36cae52eb12e155372`.
- The Claude plugin remains at the repository root. The Codex plugin remains at
  `packages/codex`.
- Share graph semantics but keep two independent runtimes. Keep hooks,
  skills, agents, and scripts provider-local.
- Do not restore `skills/index.yaml`, shared provider routing, mixed-provider
  review, provider handoffs, nested `codex exec`, the deleted custom Codex
  runtime, a daemon or an MCP scheduler.
- Use the surviving Claude graph as the behavioural source, but do not copy its
  verified defects into Codex.
- Use the same meanings for nodes, edges, all-input joins, active waves,
  retry attempts, evidence, completion, and teardown. State names include
  pending, running, done, skipped, and hard-stop.
- Operate native dispatch manually. Graph code calculates and records work.
  The active provider session calls its own native agent tool.
- Keep review provider-local. Claude uses Claude reviewers. Codex uses
  Codex reviewers. Review and merge evidence may be graph nodes. They
  never form a cross-provider join.
- Preserve the user's three-agent concurrency limit unless explicitly changed.

## Constraints

- The planned checkout needed merge `97c026e` and a clean tree. Its local
  `main` might have been behind `origin/main`; verification was required
  before worktree creation.
- Do not change Claude only for packaging symmetry. A Claude change must
  fix a proved graph defect or establish the matching graph contract.
- Matching agent names, skill names, or hook counts do not prove parity.
  Test state transitions and native dispatch.
- PR #427 had solved plugin discovery, agent installation, and hook trust.
  Reopen them only if a parity test finds a regression.
- Codex hooks required user trust through `/hooks`. The planned fresh
  session check included that step.
- This handoff authorized graph-parity planning and implementation only.
  It did not authorize cross-review or a shared runtime.

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

1. Fetch `origin/main`. Verify merge `97c026e` and a clean checkout. Then
   create a feature worktree and branch.
2. Freeze parity tests before implementation. Use the same cases in both
   providers: malformed graph, unknown node, `A || B -> join -> C`, exact
   active-wave results, retry success and exhaustion, restart, resume, and
   blocked early completion.
3. Fix proved Claude graph defects in the existing shell helpers and hooks.
   Do not add dispatch automation.
4. Implement the same contract in the Codex skill package. Prefer a small
   deterministic helper and native hooks. Do not recreate
   `packages/codex/runtime/` or add manifest fields.
5. Place Codex graph operations around `spawn_agent`, `wait_agent`, and
   verification. Keep `update_plan` as a display. It is not durable state.
   The old plan named `close_agent`. It was absent from the observed
   2026-10-24 collaboration surface.
6. Add Codex session-start discovery. Add a native Stop guard for active,
   paused, hard-stop, and complete states.
7. Run provider unit and package tests and strict changed-file quality.
   Check a clean temporary Codex install and fresh provider sessions.
8. In each fresh session, run `A || B -> join -> C`. Verify matching state
   transitions and completion blocks. Observe Claude `Agent` calls and
   Codex `spawn_agent` calls.
9. Report parity separately from hardening. Fix or explicitly accept each
   known gap before claiming both milestones.

## Open questions

- Implementation language/location for the Codex helper: port the existing
  Claude shell semantics into a skill-local script, or use a small Python helper.
  Behaviour must match either way; do not create a general runtime package.
- Whether to ship parity and graph hardening in one PR or two ordered PRs. The
  final acceptance target is the same.
