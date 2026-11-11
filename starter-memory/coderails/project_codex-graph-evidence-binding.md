---
name: Codex graph evidence binding
description: Implement the approved Codex-only plan that binds native worker transcript events to orchestrator-owned progress.json graph state.
type: project
---

# Codex graph evidence binding

> Supersession note (2026-09-21): This is a historical handoff for linking native worker records. The current graph uses only schema 3. It uses provider-native dispatch with explicit agent instruction bodies. Worker labels alone cannot prove execution. The shell test paths below document the historical baseline. Read the current native agentic-loop skill and graph record modules before editing.

## Goal

Make Codex graph execution mechanically auditable without an automatic scheduler. Codex runs graphs with manual orchestration. Connect each try at a graph node to the native worker records in the Codex session transcript.

After implementation, test the full agreed manual graph contract live. Check durable graph data, dependency readiness, waves, native workers, strict result binding, joins, and retries. Check continuation, hard stops, ownership, transcript links, and the gates that permit a graph to finish.

## Decisions

- Change only Codex in `packages/codex/`. Do not change the root Claude plugin.
- Use the native transcript in `~/.codex/sessions` as the authoritative record of execution.
- Do not add `execution.jsonl`, a second log, a daemon, a new verifier component, dashboard coupling, or a scheduler.
- Use the existing node `evidence` array. Do not add a second store for graph data.
- Record only the compact identifiers. Include the try number, wave ID, spawn call ID, child agent thread ID, and child `task_complete` turn ID.
- Top-level `session_id`, `loop_id`, revision, node ID, and the existing graph data identify the context. Do not duplicate them in each object.
- The orchestrator owns `progress.json`. Subagents send results. They do not write graph data.
- `record-wave` resolves and atomically records native agent metadata from the owning transcript. It uses no hook recorder.
- `record-wave` rejects a result unless the same session transcript proves that the matching native agent finished its work.
- Before the graph can end, check the transcript link again for each node try that succeeded.
- Give each retry its own object in `evidence`. Keep earlier records unchanged.
- Native `wait_agent` reports only timeout or end status. A correct graph requires the child's `task_complete` to succeed. The wait payload cannot establish that.
- Codex CLI v0.149 has no `close_agent`. The graph operates correctly without it.

## Constraints

- Keep the change small. Edit only the existing runtime, transcript reader, skill, and targeted tests.
- Do not change Claude, Claude sandboxing, or dashboards. Do not add provider-neutral refactors, cross-provider inspection, or an automatic scheduler.
- Do not copy encrypted prompts, worker reports, wait outputs, or transcript text into `progress.json`.
- Do not let a worker certify itself.
- Keep strict active-wave result matching and revision checks. Keep retries, joins, hard stops, proof, eval and retro gates, and provider independence.
- Start from a clean, current `main` in an isolated worktree.
- Freeze task evals before implementation.
- Run the repository tests. Finish with a live test through the native provider path.

## Schema / Taxonomy

Use one structured object in the existing node `evidence` array each time a native worker tries a node:

```json
{
  "kind": "codex_agent",
  "attempt": 1,
  "wave_id": "wave-2",
  "spawn_call_id": "call_...",
  "agent_thread_id": "01a...",
  "task_complete_turn_id": "01a..."
}
```

Field names can follow local naming. Keep the information and fail-closed behavior unchanged. The transcript is authoritative for the full tool input, tool response, worker result, and record sequence.

## Key files

- `packages/codex/skills/agentic-loop/scripts/graph.py` validates the graph and starts waves. It applies strict result checks and controls retries, joins, ownership, and end checks.
- `packages/codex/skills/agentic-loop/scripts/graph_evidence.py` finds Codex transcripts and correlates proof commands. Extend it without a new verifier.
- `packages/codex/skills/agentic-loop/SKILL.md` — orchestrator workflow and native `spawn_agent`/`wait_agent` instructions.
- `packages/tests/codex_graph_runtime_adversarial.test.sh` — focused native graph runtime adversarial coverage.
- `packages/tests/codex_hooks.test.sh` — focused Codex hook registration and behavior coverage.
- `packages/tests/provider_graph_parity.test.sh` and sibling provider graph adversarial tests cover the existing parity contract. Run them without changing Claude behavior.
- Run records: `/Users/garyharr/.codex/plugins/data/coderails-codex-coderails/agentic-loop/-Users-garyharr-Github-SREAssistant-.git/01a0206e-9150-7440-aa7d-a3c62f51f398`.
- Find the native transcript in `/Users/garyharr/.codex/sessions` by `session_meta.payload.id = 01a0206e-9150-7440-aa7d-a3c62f51f398`.

## Done so far

- PRs 428-430 are merged on current `origin/main`. The graph parity and adversarial suites passed during the research session.
- The Codex graph runtime validates graphs, checks readiness, and builds deterministic waves. It applies strict active-wave result checks and manages all-input joins, retries, and continuation data. It also manages hard stops, session and loop ownership, proofs, evals, retro, and end checks.
- The SREAssistant transcript showed a live graph run with manual orchestration. It recorded readiness, two waves, two native workers, waits, results, and dependency release. It recorded proof and a negative control, eval grading, and two tries to finish. The first did not succeed. The second succeeded.
- The run showed that `progress.json` omits the native worker invocation that made each node result.
- Current hooks authorize `spawn_agent` before dispatch. Connect worker records without adding a post-tool hook.
- This checkpoint has no implementation, worktree, branch, tests, commit, or PR for the change.

## Next steps

1. Check that the primary checkout is clean and current. Make a worktree and branch for this change.
2. Invoke task-evals and freeze success criteria before code changes.
3. Resolve the owning parent transcript from `progress.json.session_id`. Use the native spawn result and `SubAgentActivity` to connect each current-wave task name to the child agent thread.
4. Check that child `task_complete` succeeded. Atomically add compact identifiers for each try during `record-wave`.
5. Reject missing, duplicate, foreign-session, wrong-wave, wrong-node, stale, or reused records. Reject records for native agents that did not succeed.
6. Check all recorded transcript links again before the graph ends.
7. Update the Codex agentic-loop skill. Workers only send results. The orchestrator alone owns the graph data.
8. Add targeted tests for correct and missing records, forged IDs, and mismatched sessions, waves, and nodes. Test duplicate agents, stale records, terminal errors, retries, and reuse.
10. Run focused Codex graph and hook tests, provider parity/adversarial tests, and `scripts/quality/check.sh --strict --changed`.
11. Install the Codex plugin in a clean temporary location and test live native operation.
    - `A || B -> all-input join -> C`.
     - One node that fails, followed by a retry and continuation.
12. Check that the graph finished using `progress.json` and the matching native transcript. Commit, push, and open a PR. Merge requires new user approval.

## Open questions

- None. The native run showed the transcript contract. The design uses no PostToolUse payloads or `close_agent`.
