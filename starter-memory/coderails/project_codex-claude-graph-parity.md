---
name: codex-claude-graph-parity
description: Historical graph-parity baseline; current Python graph semantics and native provider contracts supersede its implementation notes.
type: project
---

# Codex and Claude graph parity

> The current implementation follows `docs/superpowers/plans/2026-09-03-provider-graph-alignment-implementation.md` and `skills/agentic-loop/execution-graph.md`. Each plugin operates independently and uses a byte-for-byte copy of the maintained pure Python core at `packages/graph-semantics/graph_semantics.py`. Each provider owns its dispatch, locks, and native run records. The graph uses only schema 3. Native provider role labels and explicit instruction bodies replace mandatory custom worker names. The shell paths, checkout constraints, and defect inventory below describe the historical baseline only.

## Goal

Give Codex and Claude the same graph data, readiness rules, waves, joins, retries, hard stops, end checks, continuation behavior, and proof tests. The plugins operate independently. Claude dispatches through `Agent`. Codex dispatches through `spawn_agent`. Each provider sends work and reviewer tasks only to its own runtime.

Use two milestones. First prove matching behavior. Then prove that the repairs close the known graph defects for the two providers. Complete each milestone in clean, new provider sessions.

## Decisions

- PR #427 is merged at `97c026eb4ea059e07b563f36cae52eb12e155372`.
- The Claude plugin stays at the repository root. The Codex plugin stays at `packages/codex`.
- Share graph semantics. Keep each provider's own implementation, hooks, skills, agents, and scripts.
- Keep `skills/index.yaml`, shared provider routing, cross-provider inspection, and provider handoffs out of scope. Keep nested `codex exec` and the deleted custom Codex runtime out of scope. Do not add a daemon or an MCP scheduler.
- Use the surviving Claude graph as the baseline for behavior. Do not copy its known defects into Codex.
- Give nodes, edges, and all-input joins the same semantics in the two providers. Align `pending`, `running`, `done`, `skipped`, and `hard-stop`. Align active waves, retry counts, run records, end checks, and teardown.
- Keep native agent dispatch manual in the two providers. The graph code calculates and records work. The active provider session calls its own agents.
- Claude uses Claude reviewers. Codex uses Codex reviewers. Nodes can hold records of reviewer checks and merge. Do not use a cross-provider join for them.
- Keep the user's three-agent concurrency limit unless the user explicitly changes it.

## Constraints

- Start from a clean checkout with merge `97c026e`. Check if local `main` is behind `origin/main` before making a worktree.
- Change the working Claude plugin only to correct a proven graph defect or make the graph contracts match.
- Equal agent names, skill names, or hook counts cannot prove equal behavior. Test how graph data changes and how each provider dispatches work.
- PR #427 resolved plugin discovery, custom-agent installation, and hook trust. Reopen them only if a parity test proves a regression.
- Codex hooks run only after the user trusts them through `/hooks`. Include that step in each new session used for verification.
- This handoff authorises planning and implementation of graph parity only. It
  does not authorise cross-review or a shared provider runtime.

## Schema / Taxonomy

Use the same contract for the two providers

| Area | Behavior for Claude and Codex |
|---|---|
| Loop data | One durable loop record with session and loop ownership, revision, nodes, edges, joins, active wave, decisions, and run records |
| Readiness | Reject unknown or malformed nodes. A node can start only after all required predecessors succeed. |
| Worker dispatch | Resolve a complete wave of nodes that can start. Record it as active and `running`. Use the provider's native agent tool. |
| Recording | Accept the active wave's full set of result keys only. Reject results with missing or unknown keys and keep the graph unchanged. |
| Retry | If a node can retry, set it to `pending` and increment the try count. Keep its records. Set it to `hard-stop` if retries run out. |
| All-input join | Release an all-input join only after all inputs succeed. Use deterministic code for release. |
| Session continuation | A new or compacted session finds the active loop and the wave in flight if there is one. It finds work that can start and the cause of a hard stop. |
| End checks | The loop cannot finish with `pending`, `running`, or `hard-stop` nodes, unreleased joins, or missing proof, run records, or retro. |
| Provider dispatch boundary | Claude uses `Agent`. Codex uses `spawn_agent`. The graph code does not start a second provider session. |

## Known graph gaps to close

Checks against merged commit `97c026e` found these defects

1. Claude sets a retryable node to `running` after an error. Readiness selects only `pending` and `ready`, so a node can drop out of future waves.
2. Claude readiness can accept an unknown node. It does not validate the full graph before answering.
3. Claude does not record a wave in flight. Starting again can duplicate dispatch. It does not check result sets with missing keys against the planned wave.
4. The sequence of Claude's end markers can bypass teardown checks on the turn that ends the graph.
5. Claude checks `work_units` before finishing. It does not check for unfinished graph nodes or joins.
6. A stale loop eval can authorize a subsequent rearmed loop. Its artifact has no unique loop identity.
7. Claude's in-process loop-worker gate accepts missing graph data or data from a different loop.
8. Claude sandboxed workers bypass the in-process loop dispatch gate.
9. Codex has no mechanical graph record, readiness calculator, wave recorder, retry counter, join release, or gate for ending the graph.
10. Codex's current `progress.json` is an optional checkpoint. It does not schedule or enforce work.
11. Codex package tests prove package shape and instruction wording. They do not prove graph behavior.

Deliberate limits

- The model controls native agent dispatch for the two providers.
- No automatic background scheduler.
- No shared runtime, provider router, or cross-provider inspection.
- Each provider uses its own multi-step workflow for reviewer checks and merge.

## Key files

Claude source and behaviour:

- `skills/agentic-loop/SKILL.md`: Claude graph operating discipline.
- `skills/agentic-loop/execution-graph.md`: graph shape, waves and joins.
- `skills/agentic-loop/loop-state.md` documents durable graph records and the rules for ending a loop.
- `skills/agentic-loop/retry-until-green.md`: retry semantics.
- `skills/agentic-loop/phases-setup.md` documents how to initialize graph data.
- `skills/agentic-loop/teardown.md` documents the proof, retro, and end sequence.
- `hooks/scripts/lib/graph_readiness.sh` calculates current readiness.
- `hooks/scripts/lib/graph_executor.sh`: locked graph-state updates.
- `hooks/scripts/lib/graph_dispatch.sh`: ready-wave planning, routing and result recording.
- `hooks/scripts/lib/loop_state_common.sh` provides shared functions for graph data and end checks.
- `hooks/scripts/loop_dispatch_guard.sh`: Claude Agent dispatch gate.
- `hooks/scripts/loop_state_guard.sh` checks graph data and evals at Stop.
- `hooks/scripts/loop_stall_guard.sh` guards the end of a loop and checks proof and retro.
- `scripts/sandbox/spawn-sandboxed-worker.sh` is the sandboxed Claude worker path. It must use the same graph and eval decision.

Codex target:

- `packages/codex/skills/agentic-loop/SKILL.md` has instructions only. Operate the matching graph contract around native agent calls.
- `packages/codex/hooks/hooks.json` registers native hooks to continue and end the graph.
- `packages/codex/hooks/scripts/inject_bootstrap.sh` must report active graph status after session start, resume, or compaction.
- Use `packages/codex/hooks/scripts/lib/hook_common.sh` for Codex hook input and output.
- `packages/codex/skills/workflow/SKILL.md` uses a provider-local reviewer wave and nodes for reviewer checks, evals, and merge.
- Use the existing current-head reviewer, eval, and smoke gates in `packages/codex/scripts/merge.sh`.
- `packages/codex/agents/*.toml` holds installed native Codex workers and reviewers.
- In `packages/tests/codex_native_package.test.sh`, keep checks that retired mixed and runtime paths stay removed. Add graph-package assertions.
- In `packages/tests/codex_hooks.test.sh`, replace only the obsolete expectation that no graph hooks exist.

Examine and extend these tests

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
- Add a Codex provider-local graph behavior test in `packages/tests/`.

## Done so far

- PR #427 added and merged the standalone native Codex plugin.
- The Claude root plugin remains provider-owned and functional.
- At this checkpoint the Codex package has 37 skills, 10 custom agents, native hooks, and provider-local workflow scripts.
- The change removed shared routing, cross-provider inspection, and the custom Codex runtime.
- New Codex sessions found `coderails-codex:agentic-loop` before merge.
- Three read-only audits compared pre-PR `dfcd6366` with merged `97c026e`.
- The audits proved Claude retained a manually operated mechanical graph while
  Codex currently has instruction-only dependency orchestration.
- No graph-parity implementation has started.
- The stale `project_mixed-provider-graph.md` memory has been marked superseded.

## Next steps

1. Fetch `origin/main` and check for merge `97c026e`. With a clean checkout, make a worktree and branch for the change.
2. Freeze provider-parity tests before implementation. Test a malformed graph, an unknown node, `A || B -> join -> C`, and strict active-wave matching. Test retry success and exhaustion, starting again, and continuation. Test that the graph cannot finish before all end checks succeed.
3. Correct the proven Claude graph defects with the smallest changes to its shell helpers and hooks. Do not add dispatch automation.
4. Use the same contract in the Codex skill package. Prefer a small deterministic helper in the skill and provider-native hooks. Do not recreate `packages/codex/runtime/` or add manifest fields.
5. Update the Codex skill so graph operations surround `spawn_agent`,
   `wait_agent`, result verification and `close_agent`. Keep `update_plan` as a
   display, not the durable source of truth.
6. Add Codex session-start discovery and a provider-native Stop guard for `active`, `paused`, `hard-stop`, and `complete`.
7. Run provider-local unit and package tests and strict checks for changed files. Use a clean temporary Codex install. Start new Claude and Codex sessions.
8. In each new session, run the harmless graph `A || B -> join -> C`. Prove the same graph changes and blocks on finishing. Record Claude `Agent` and Codex `spawn_agent` invocations.
9. Report matching behavior and hardening results independently. For each known defect, report its repair or explicit approval to keep it.

## Open questions

- Which language and location should the Codex helper use? Copy the Claude shell semantics into a script in the skill or use a small Python helper. Keep behavior the same. Do not make a general runtime package.
- Use one PR for parity and hardening, or two PRs in sequence? The criteria for accepting the work stay the same.
