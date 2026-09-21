---
name: Codex graph evidence binding
description: Implement the approved Codex-only plan that binds native worker transcript events to orchestrator-owned progress.json graph state.
type: project
---

# Codex graph evidence binding

## Goal

Make Codex graph execution mechanically auditable without adding an automatic scheduler. Codex already performs real manually operated graph engineering; this change binds each graph node attempt to the native worker events already stored in the Codex session transcript.

After implementation and live acceptance, Codex must satisfy the complete agreed manual graph contract: durable state, dependency readiness, waves, native workers, exact result binding, joins, retries, resume, hard stops, ownership, transcript-backed evidence, and completion gates.

## Decisions

- Scope is Codex only under `packages/codex/`. Do not modify the root Claude plugin.
- The native transcript under `~/.codex/sessions` is the execution source of truth.
- Do not add `execution.jsonl`, another log, a daemon, a new verifier component, dashboard coupling, or a scheduler.
- Reuse the existing node `evidence` array. Do not add a second graph-state store.
- Record compact references, not duplicate content: attempt, wave ID, spawn call ID, child agent thread ID, and child `task_complete` turn ID.
- Top-level `session_id`, `loop_id`, revision, node ID, and existing graph state provide the surrounding identity; do not repeat them unnecessarily in every evidence object.
- The orchestrator owns `progress.json`. Subagents return results and never write graph state.
- `record-wave` resolves and atomically records native agent metadata from the owning transcript; no hook recorder is needed.
- `record-wave` must reject a result unless a matching completed native agent attempt is verifiable in the same session transcript.
- Completion must recheck the transcript link for every successful node attempt.
- Preserve separate evidence objects for retries; never overwrite an earlier attempt.
- Native `wait_agent` exposes only timeout/completion state. Graph correctness depends on the child's successful `task_complete`, not wait payload details.
- Codex CLI v0.149 has no `close_agent`; graph correctness does not require it.

## Constraints

- Ponytail-minimal: modify the existing runtime, evidence reader, skill, and focused tests only.
- No Claude work, Claude sandbox work, provider-neutral refactor, mixed-provider review, dashboard work, or automatic scheduler.
- Do not copy encrypted prompts, worker reports, wait outputs, or transcript text into `progress.json`.
- Do not let a worker certify itself.
- Preserve exact active-wave result matching, revision checks, retries, joins, hard stops, proof/eval/retro gates, and provider independence.
- Start from a clean, current `main` in an isolated worktree.
- Freeze task evals before implementation.
- Repository tests are necessary but not sufficient; finish with native live acceptance.

## Schema / Taxonomy

Use one structured object in the existing node `evidence` array for each native worker attempt:

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

The exact field names may follow existing local naming, but the information and fail-closed behavior are fixed. The transcript remains authoritative for the full tool input, tool response, worker result, and event ordering.

## Key files

- `packages/codex/skills/agentic-loop/scripts/graph.py` — graph validation, wave start, exact result recording, retries, joins, ownership, and completion.
- `packages/codex/skills/agentic-loop/scripts/graph_evidence.py` — existing Codex transcript discovery and proof-command correlation; extend it instead of adding a verifier.
- `packages/codex/skills/agentic-loop/SKILL.md` — orchestrator workflow and native `spawn_agent`/`wait_agent` instructions.
- `packages/tests/codex_graph_runtime_adversarial.test.sh` — focused native graph runtime adversarial coverage.
- `packages/tests/codex_hooks.test.sh` — focused Codex hook registration and behavior coverage.
- `packages/tests/provider_graph_parity.test.sh` and sibling provider graph adversarial tests — existing parity contract; run but do not modify Claude behavior.
- Run evidence: `/Users/garyharr/.codex/plugins/data/coderails-codex-coderails/agentic-loop/-Users-garyharr-Github-SREAssistant-.git/01a0206e-9150-7440-aa7d-a3c62f51f398`.
- Native transcript: locate under `/Users/garyharr/.codex/sessions` by `session_meta.payload.id = 01a0206e-9150-7440-aa7d-a3c62f51f398`.

## Done so far

- PRs 428-430 are merged on current `origin/main`; repository graph parity and adversarial suites passed during the research session.
- Codex graph runtime implements validation, readiness, deterministic waves, exact active-wave result sets, all-input joins, retries, resume state, hard stops, session/loop ownership, proofs, evals, retro, and completion.
- The SREAssistant transcript proved a real manually operated Codex graph run: readiness, two waves, two native workers, waits, result recording, dependency release, proof and negative control, eval grading, a failed first completion attempt, and a successful final completion.
- The run also exposed the gap: `progress.json` does not identify the native worker invocation that produced each node result.
- Current hooks authorize `spawn_agent` before dispatch. No post-tool hook is needed for evidence binding.
- No implementation, worktree, branch, tests, commit, or PR for this evidence-binding change exists yet.

## Next steps

1. Verify the primary checkout is completely clean and current, then create a focused worktree and branch.
2. Invoke task-evals and freeze success criteria before code changes.
3. Resolve the owning parent transcript from `progress.json.session_id`, then bind each current-wave task name through its native spawn result and `SubAgentActivity` to the child agent thread.
4. Require a successful child `task_complete`, and atomically add compact per-attempt references during `record-wave`.
5. Reject missing, duplicate, foreign-session, wrong-wave, wrong-node, stale, failed, or reused native agent evidence.
6. Recheck all stored references during completion.
7. Update the Codex agentic-loop skill: workers only return results and the orchestrator alone owns graph state.
8. Add focused tests for valid evidence, missing evidence, forged IDs, wrong session/wave/node, duplicate agents, stale events, terminal failure, retries, and reuse.
10. Run focused Codex graph and hook tests, provider parity/adversarial tests, and `scripts/quality/check.sh --strict --changed`.
11. Install the Codex plugin into a clean temporary location and run native live acceptance:
    - `A || B -> all-input join -> C`.
    - One failed node followed by retry and resume.
12. Verify completion from `progress.json` plus the matching native transcript, then commit, push, and open a PR. Do not merge without a separate request.

## Open questions

- None. The native transcript contract is confirmed; PostToolUse payloads and `close_agent` are not required.
