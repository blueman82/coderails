---
name: agentic-loop
description: Coordinate autonomous multi-step work with native Codex subagents and a durable, fail-closed execution graph. Use for teams, dependent work units, multi-PR runs, or end-to-end work without routine check-ins.
---

# Agentic Loop

Keep the main Codex session as orchestrator. Workers implement; the orchestrator owns one durable graph and is its only writer. `update_plan` is display only and never decides readiness, resume, or completion.

Set `SKILL_DIR` to the absolute directory containing this `SKILL.md`. The graph helper is `scripts/graph.py` beside this skill. It uses only the Python standard library. It calculates and records work but never starts agents, another provider, a nested session, or a scheduler.

## Start or resume

Read the SessionStart bootstrap text first. It reports either the active state path and inspection or the path for a new `progress.json`. Reuse that exact path after compaction or resume.

For a new loop, put the user's authorised outcome verbatim in a file. Before any worker dispatch, run `python3 "$SKILL_DIR/scripts/graph.py" start "$STATE" --session "$SESSION" --loop-id "<unique loop id>" --prompt-file "$PROMPT_FILE"`. The command writes schema-v3 state atomically: `in-progress`, revision 1, with an empty graph. A repeat of the same loop id is a no-op. A completed loop is re-armed. If an unfinished loop owns the session, the command refuses with a `[reason_code=...]`; resume that loop instead. `$STATE` must end `<session>/progress.json`.

Register each work unit with `python3 "$SKILL_DIR/scripts/graph.py" add-unit "$STATE" --session "$SESSION" --loop-id "<same id>" --unit N [--depends-on M ...] [--join] [--manifest GLOB ...]`. One locked save writes the work unit, its `U3[N]` node, the dependency edges, and the `J12-all-units` input. Never edit `progress.json` by hand for these steps.

Nodes other than `U3[N]` and `J12-all-units` use registered node IDs and their exact registered labels; every node carries `respawn: {"generation":0,"intent":null}`. An all-input join has an entry in `graph.joins` with `id` equal to the join key, `mode: "all"`, its registered input node IDs, and `released: false`. Downstream edges originate at that join. Active waves use `wave_id`. Unknown nodes, malformed state, cycles, inconsistent joins, or running nodes outside an active wave fail closed.

Keep the top-level `work_units` roster independent of `graph.nodes`: graph nodes record dispatch and control steps, while work units record the authorized deliverables. Completion requires every registered work unit to be `done` or `dropped` with a nonblank `dropped_reason`; never infer unit completion solely from graph-node status.

Create and freeze an ungraded loop-local `evals.json` beside `progress.json` before build. The frozen suite needs a nonblank `frozen_sha`, a positive verification level, at least one P0, valid eval modes, scripted command/negative-control fields, and null `result`/`grading`. Grade actual outcomes at completion; do not fabricate a pre-build GO. The suite must carry this exact `session_id` and `loop_id`. Those stable fields authorize dispatch across waves, so `begin-wave` does not invalidate the loop's eval authority. Keep the revision field at the revision used for freeze or grading. The provider-local dispatch hook accepts valid frozen, ungraded evidence before build or genuinely graded evidence. It blocks if graph ownership or loop evidence is missing or foreign.

For a graph with three or more work units, or any cross-unit dependency, apply the design-quality discipline in `superpowers:brainstorming` without its interactive human-approval gate. Write or reuse `spec.md` beside `progress.json`. Then invoke `superpowers:writing-plans` to write durable `plan.md` beside it, outside the code repository. `plan.md` records scope and decomposition. `progress.json` records the current position and outcomes. Derive node scope from the plan. Reread `spec.md` and `plan.md` on resume. Do not create them for one or two self-contained units.

Before dispatching a writing node, invoke `superpowers:using-git-worktrees`. Use Coderails `prep` to perform the resulting worktree setup; it creates the worktree and, for a non-Git folder, the local `main` repository and initial commit it needs. Do not add a remote.

Before ending a turn on a hard-stopped graph, record the stop: `python3 "$SKILL_DIR/scripts/graph.py" stop "$STATE" --session "$SESSION" --category hard-stop --reason-code node_hard_stop --reason "<reason>"`. The Stop guard consumes that recorded row once; the final `LOOP-STOP: waiting-on-human` line is the legacy fallback. Run `python3 "$SKILL_DIR/scripts/graph.py" inspect "$STATE"`. Inspection is the resume source of truth: loop and session identity, revision, active wave, running nodes, ready nodes, and hard-stop reason. Never reconstruct these from chat history.

## Run one wave

Every dispatch wave follows this order:

When composing each worker prompt, place the printed one-word `job_name` and `lane_code` after its machine ownership marker as a human-readable line with the stable node ID (for example, `Builder · A-1 [U3[1]]`). This display is descriptive only; use the stable node ID for task identity, authorization, and evidence.

1. Run `graph.py begin-wave "$STATE"` before `spawn_agent`. Calling `begin-wave` validates the graph and refuses an existing active wave. It records the complete deterministic ready set as running, increments the revision, and prints the wave id, node list, and `task_names` mapping. While a wave is active, `inspect` repeats that mapping.
2. If a ready wave has two or more independent nodes, invoke `superpowers:dispatching-parallel-agents` for guidance on parallel dispatch. `graph.py` still determines readiness. Native `spawn_agent` remains the sole dispatcher.
3. Call native `spawn_agent` exactly once for each printed node.
   - Use the provider-native `task_name` from the printed mapping when supported. If this runtime exposes `agent_type`, select an available native role. A custom `loop-worker` role is optional. Omit an unavailable role parameter.
   - Start the message with `CODERAILS_GRAPH_TASK=<exact printed task name>` on its own line. The canonical task name encodes the loop and node IDs as lowercase UTF-8 hex separated by `_`. Retries and stale respawns append `_aN`, where N is failed retries plus respawn generation plus one. This keeps each attempt unique and reversible.
   - Read `../../agents/loop-worker.toml` relative to this skill. Put its `developer_instructions` text after the graph marker. Then add the task brief and current user restrictions. A native role label does not load those instructions by itself.
   - Give the worker its node ID, scope, allowed paths, worktree, exclusions, checks, required artifact, and evidence report. Require scoped implementation, tests first for testable changes, actual verification results, self-review, and an honest report. User restrictions on commits, remote writes, or tests take precedence.
   - For testable code, require `superpowers:test-driven-development`. Require `superpowers:subagent-driven-development` for worker construction and `superpowers:verification-before-completion` before the report. Do not use another provider or start a nested Codex session.
4. Use the exposed native wait tool (`wait_agent` in the collaboration surface) until every node in the active wave has a terminal report. A wakeup or mailbox notification alone is not a terminal result; `record-wave` resolves each task marker through either older `CollabAgentToolCall` spawn evidence or the native `spawn_agent` function call joined to its one `SubAgentActivity`, then child `source.subagent.thread_spawn` metadata and successful `task_complete`. Only loop-scoped task names (`task_names` from `begin-wave`) are accepted; a node-only pre-loop-scoped name is refused with `legacy_task_identity_refused`; a done node cannot be reopened, so such a loop is restarted under a fresh `--loop-id` (completed legacy loops also fail `verify-completion`). A quiet worker is not proof of failure: inspect its artifact, then use the exposed native message/follow-up tool for one focused correction if needed (`send_message` for a running worker, or `followup_task` to resume an idle worker on the collaboration surface).
5. Check each report against the actual diff, test output, PR state, or another current artifact. A worker summary alone is not evidence. A worker that must stop for a human returns one typed status: `NEEDS_DECISION`, `OUTSIDE_SCOPE`, or `IRREVERSIBLE_ACTION` (schema in `scripts/worker_status.py`). Only the orchestrator asks the human, after `validate()` and `to_decision_request()`. These statuses are not `record-wave` outcomes.
6. Build one result object with every active-wave node and no other key. Each result is `{"outcome":"done|skipped|failed","evidence":"observed evidence"}`. Record it with:

```bash
python3 "$SKILL_DIR/scripts/graph.py" record-wave "$STATE" \
  '{"wave_id":"wave-N","results":{"U3[1]":{"outcome":"done","evidence":"check passed"}}}'
```

The graph marker correlates a node and attempt; it does not attest a custom agent role. Native task paths, child/thread IDs, and any actual requested role are bound to provider transcript evidence. A supplied native role must match both child role fields; role-less dispatch is accepted only for the recognized `collaboration` function-call/activity shape with an explicit null nested spawn role; the top-level role may be absent or null, and any populated top-level path must agree. Parent/session, depth, unique dispatch, terminal completion for completed attempts, cursor, and reuse checks remain mandatory. A checked stale result verifies its unique native spawn and child ownership without inventing a successful terminal; subsequent completion rechecks every abandoned attempt from native transcripts. `loop_dispatch_guard.py` routes graph tasks through state, session, active-wave, and eval authorization before dispatch; an ambiguous marker is denied.

If every worker in the active wave has been silent past a lease, run:

```bash
python3 "$SKILL_DIR/scripts/graph.py" recover-wave "$STATE" --session "$SESSION" [--lease-seconds N] [--report-only]
```

The command reports each node with one stable `reason_code` and one status:

- `dispatch`: the node was never spawned. Spawn it now; no attempt was
  recorded.
- `record`: the worker finished or its launch was refused. Record that
  result.
- `waiting` or `stalled`: use the reported reason to decide whether to
  wait or recover.

Only when every node is `stalled` does the command record them as `stale`
and request a respawn. It saves this change under one lock. It does not count
an attempt without a stored worker reference. Once a node reaches
`retry.max`, the command refuses with `recovery_budget_exhausted`. A human
then decides. Each outcome adds a non-authoritative row to
`recovery-trace.jsonl` beside the graph state. See
`docs/recover-wave-runbook.md`.

Run `graph.py summarize "$STATE"` for plain-language status. Run
`graph.py collection <state-root>` to list graph states and node names.
The optional `collection.json` can link graphs explicitly:

```json
{"schema_version":1,"graphs":[{"key":"build","path":"build/progress.json","loop_id":"build-loop","links":["verify"]},{"key":"verify","path":"verify/progress.json","loop_id":"verify-loop","links":[]}]}
```

Paths and loop IDs must match discovered schema-3 graph states. Links name
graph keys. Unknown or ambiguous targets fail closed. Without this index,
the command lists graphs as disconnected. It reads graph state and returns
links plus `unresolved_targets`. A valid index has an empty
`unresolved_targets` list. Malformed states make the command fail.

When a blocked Stop finds a silent wave, the Stop hook runs this recovery.
It tries at most once per 900-second lease for each graph state and has a
four-second budget. A live but silent worker can be spawned twice. The
`retry.max` limit bounds this case. A timed-out attempt has an unknown
outcome.

The collection command adds `key` and `links` to each graph record; an unlinked record has `"links": []`. Each node keeps its stable `id` and reports its one-word `name`, optional `lane_code`, and current `status` (for example: `{"id":"U3[15]","name":"Builder","lane_code":"C-3","status":"pending"}`). A missing or malformed target makes the command fail with a `graph:` error.

Partial, extra, malformed, wrong-wave, stale, failed, duplicate, foreign-session, or reused worker evidence is rejected without changing state. `record-wave` atomically adds compact transcript references to the existing node evidence array. Workers never write graph state. A failed node increments its attempts and keeps a separate reference for that attempt.

If `spawn_agent` refuses a call, such as with "agent thread limit reached", retry with the same printed `task_name` until it succeeds. If refusals continue, report that node as `failed`. `record-wave` then binds the latest refused call as that attempt's reference. This call must have an error output and no `SubAgentActivity`. A refused call never satisfies `done`, `skipped`, or `stale`.

A later `followup_task` turn does not invalidate a recorded child's earlier completion. The child's latest turn must still complete successfully. The node returns to pending while attempts remain; exhaustion becomes a durable hard-stop. Successful all-input joins release deterministically after every input succeeds. Repeat from `inspect`, then `begin-wave`.

**Scout spawn refusal fails closed.** If the design scout (or any independent reviewer) cannot be spawned (`agent thread limit reached` or any other capacity refusal), do not silently downgrade to the orchestrator's or a worker's own read. Retry the spawn with the same `task_name`; if it keeps being refused, record the node `failed` through `graph.py record-wave`, which binds the refused call as that attempt's reference (a refused call never satisfies `done`, and `record-wave` rejects it as success on Codex), then halt. A `not_found` on a `task_name` carried over from a previous session or resumed loop is not a capacity refusal: retry with a FRESH `task_name`, never the same one. Without an independent scout the loop HALTS for the human: do not continue past the refusal. A `non_independent` fallback requires explicit human approval. Only after the human approves, record `S2.5` as `skipped` with evidence beginning `non_independent: human approved` and append a `decisions_absorbed` entry `{phase: "<current phase>", decision: "scout refused: <error text>, adopted non_independent"}`. That `skipped` record is the only exit that lets `J2` release without an independent scout; a `non_independent` read never counts as an independent review or as `done`. Hooks cannot spawn agents and no gate reads `non_independent`, so this is an orchestrator rule, not a hook-enforced one.

**Thread-limit boundary.** Spawned agent threads can continue to count after
they finish or become idle. Before a scout spawn, use a provider close tool
only if that tool is present. Codex CLI 0.164.0's collaboration surface has
no `close_agent` tool. `interrupt_agent` stops a turn but does not retire the
thread. Do not treat CLI session archive or delete as a close operation for
this active team. If capacity remains exhausted, record the refusal and
halt. Do not claim that a slot was freed.

After independently verifying a deliverable and recording its wave, decide its registered work unit through `python3 "$SKILL_DIR/scripts/graph.py" record-unit "$STATE" --session "$SESSION" --unit "<id>" --status done --evidence "<observed check>"`. If the authorized deliverable is withdrawn, use `--status dropped --reason "<reason>"`. The command requires a pending unit and no active wave and records the decision atomically. The graph revision remains unchanged so stored wave evidence stays valid. A completed graph node never changes a work unit by itself. Grade final evals against the current graph revision.

Respect any user concurrency limit. Otherwise, use at most three workers at once. If a ready wave is larger, define a graph whose wave width respects the limit before starting it. Do not dispatch an unrecorded subset.

## Review and release

Keep review provider-local. Use fresh Codex reviewer workers and the Codex workflow skills for review evidence, eval evidence, push, and merge. Review and release may be graph nodes, but never cross-provider joins. Treat every worker result as a claim until checked.

For a confirmed failure, make at most five distinct diagnosed repairs. When the cause is not obvious, invoke `superpowers:systematic-debugging` before another repair. Repeating the same action is not a new attempt. Stop on exhausted verification, a disproved premise, a material choice outside the authorised scope, or an unauthorised irreversible action. Record the reason in graph evidence and `hard_stop`. After a merged work-unit PR, use `superpowers:finishing-a-development-branch` for its worktree cleanup.

## Complete

Before completion, update and regrade `evals.json` against the graph's exact current revision, then write beside the state:

- graded `evals.json` for the current session, loop, and revision;
- non-empty `proof.json` for the same session and loop, with every proof carrying a nonblank executable `cmd` and `status: "pass"`;
- `retro.json` for the same session and loop, schema version 1 or newer, with `status: "complete"`.

Apply `superpowers:verification-before-completion` to the orchestrator's completion claim. Then run:

```bash
python3 "$SKILL_DIR/scripts/graph.py" complete "$STATE" \
  --session "$SESSION" --evals "$EVALS" --proof "$PROOF" --retro "$RETRO" \
  --transcript "$TRANSCRIPT_PATH"
```

Run each proof command through `functions.exec` using this canonical nested-result output; replace the placeholder with the proof's exact command so transcript matching remains exact:

```javascript
const result = await tools.exec_command({cmd: "<exact proof command>"});
text(JSON.stringify({loop_id: "<current loop id>", exit_code: result.exit_code, output: result.output}));
```

Completion refuses an active wave; pending, running, or hard-stop nodes; a graph hard-stop; unreleased joins; missing or invalid native worker transcript references; wrong-loop evidence; stale eval revision; missing or ungraded evals; missing proof; or missing retro. It rechecks each stored worker reference against the owning parent and child transcripts. It then reads this session's Codex JSONL rollout. For each proof command in the current loop, the last exact trimmed execution must contain a nested integer `exit_code` of zero. Canonical results must also carry the current `loop_id`. A command recorded under an earlier loop's turn context cannot replay.

The outer `functions.exec` text `Script completed` does not prove that the inner command succeeded. This is local redirect-and-audit evidence, not a privilege boundary. Success atomically marks the loop complete and increments its revision. The provider-local Stop hook recomputes the observed proof result before a completed loop can end. A durable graph hard-stop can end only when the final nonblank report line is exactly `LOOP-STOP: waiting-on-human`, `LOOP-STOP: stopped`, or `LOOP-STOP: stall`.
