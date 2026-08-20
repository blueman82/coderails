---
name: agentic-loop
description: Coordinate autonomous multi-step work with native Codex subagents and a durable, fail-closed execution graph. Use for teams, dependent work units, multi-PR runs, or end-to-end work without routine check-ins.
---

# Agentic Loop

Keep the main Codex session as orchestrator. Workers implement; the orchestrator owns one durable graph and is its only writer. `update_plan` is display only and never decides readiness, resume, or completion.

The graph helper is `scripts/graph.py` beside this skill. It uses only the Python standard library. It calculates and records work but never starts agents, another provider, a nested session, or a scheduler.

## Start or resume

Read the SessionStart bootstrap text first. It reports either the active state path and inspection or the path for a new `progress.json`. Reuse that exact path after compaction or resume.

For a new loop, record the user's authorised outcome, session id, unique loop id, success checks, work-unit nodes, dependency edges, and all-input joins. Write schema version 2 before any worker dispatch:

```json
{
  "schema_version": 2,
  "session_id": "current-session-id",
  "loop_id": "unique-loop-id",
  "revision": 1,
  "status": "in-progress",
  "scope": "authorised outcome",
  "graph": {
    "nodes": {
      "A": {"status":"pending","outcome":"pending","retry":{"attempts":0,"max":5},"evidence":[]}
    },
    "edges": [],
    "joins": {},
    "active_wave": null,
    "hard_stop": null
  }
}
```

An all-input join is a node plus an entry such as `"J":{"mode":"all","inputs":["A","B"],"released":false}`. Downstream edges originate at `J`. Unknown nodes, malformed state, cycles, inconsistent joins, or running nodes outside an active wave fail closed.

Create and grade loop-local `evals.json` beside `progress.json` before build. It must carry this exact `session_id`, `loop_id`, and graph `revision`. The provider-local dispatch hook blocks native worker calls when graph ownership or graded loop evidence is missing or foreign.

Run `python3 "$SKILL_DIR/scripts/graph.py" inspect "$STATE"`. Inspection is the resume source of truth: loop and session identity, revision, active wave, running nodes, ready nodes, and hard-stop reason. Never reconstruct these from chat history.

## Run one wave

Every dispatch wave follows this order:

1. Run `graph.py begin-wave "$STATE"`. This fully validates the graph, refuses an existing active wave, records the complete deterministic ready set as running, increments the revision, and prints the wave id, node list, and `task_names` mapping. Calling `begin-wave` is mandatory before `spawn_agent`. `inspect` repeats the mapping while a wave is active.
2. Call native `spawn_agent` exactly once for each printed node, using its exact printed task name. Each name is `loop_worker_` plus the lowercase UTF-8 hex encoding of the node id, so it satisfies the native task-name grammar and reversibly binds to one node without collisions. Use installed Codex custom agents where appropriate. Give each worker a self-contained prompt containing its node id, exact scope, allowed paths, worktree, exclusions, checks, required artifact, and concise evidence report. Do not use another provider or start a nested Codex session.
3. Use `wait_agent` until every node in the active wave has a terminal report. A quiet worker is not proof of failure: inspect its artifact, then use `send_message` or `followup_task` for one focused correction if needed.
4. Verify each report against the actual diff, test output, PR state, or other current artifact. A worker summary alone is not evidence.
5. Build one result object containing exactly every active-wave node and no other key. Each result is `{"outcome":"done|skipped|failed","evidence":"observed evidence"}`. Record it with:

```bash
python3 "$SKILL_DIR/scripts/graph.py" record-wave "$STATE" \
  '{"wave_id":"wave-N","results":{"A":{"outcome":"done","evidence":"check passed"}}}'
```

Partial, extra, malformed, or wrong-wave results are rejected without changing state. A failed node increments its attempts and preserves evidence. It returns to pending while attempts remain; exhaustion becomes a durable hard-stop. Successful all-input joins release deterministically after every input succeeds. Repeat from `inspect`, then `begin-wave`.

Respect any user concurrency limit; otherwise use at most three workers at once. If a ready wave is larger, do not dispatch an unrecorded subset: define a graph whose wave width respects the limit before starting it.

## Review and release

Keep review provider-local. Use fresh Codex reviewer workers and the Codex workflow skills for review evidence, eval evidence, push, and merge. Review and release may be graph nodes, but never cross-provider joins. Treat every worker result as a claim until checked.

For a confirmed failure, make at most five distinct diagnosed repairs. Repeating the same action is not a new attempt. Stop on exhausted verification, a disproved premise, a material choice outside the authorised scope, or an unauthorised irreversible action. Record the reason in graph evidence and `hard_stop`.

## Complete

Before completion, write beside the state:

- graded `evals.json` for the current session, loop, and revision;
- non-empty `proof.json` for the same session and loop, with every proof carrying a nonblank executable `cmd` and `status: "pass"`;
- `retro.json` for the same session and loop, schema version 1 or newer, with `status: "complete"`.

Then run:

```bash
python3 "$SKILL_DIR/scripts/graph.py" complete "$STATE" \
  --session "$SESSION" --evals "$EVALS" --proof "$PROOF" --retro "$RETRO" \
  --transcript "$TRANSCRIPT_PATH"
```

Completion refuses an active wave, pending/running/hard-stop nodes, a graph hard-stop, unreleased joins, wrong-loop evidence, stale eval revision, missing or ungraded evals, missing proof, or missing retro. It mines this session's Codex JSONL rollout and requires the last exact trimmed execution of every proof command to have completed successfully. This is local redirect-and-audit evidence, not a privilege boundary. Success atomically marks the loop complete and increments its revision. The provider-local Stop hook recomputes the same observed proof result before allowing a completed loop to end. A durable graph hard-stop may end only with a `LOOP-STOP: waiting-on-human|stopped|stall` report-and-wait declaration.
