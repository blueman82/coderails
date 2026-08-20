---
name: agentic-loop
description: Coordinate autonomous multi-step work with native Codex subagents. Use when the user asks for a team, several independent work units, a multi-PR run, or an end-to-end task without routine check-ins.
---

# Agentic Loop

Keep the main session as the orchestrator. Delegate implementation and focused investigation, maintain one visible plan, verify results from current-session evidence, and finish the authorised scope without routine hand-backs.

## Read the authorisation envelope

Before dispatching work, record:

- the exact outcome the user authorised;
- actions inside and outside that scope;
- irreversible or externally visible actions that still require approval;
- concrete success checks.

Do not ask again about routine steps already covered by the envelope. Stop for a missing material decision, an unauthorised destructive action, or a verification failure that remains after bounded repair attempts.

## Plan the work

Use `update_plan` as the live todo list. Split work into independently verifiable units and name dependencies in each item. Keep at most one plan item `in_progress` unless independent units are actively running together.

For long work, optionally keep a small `progress.json` in a task-specific scratch directory outside the repository:

```json
{
  "status": "in_progress",
  "scope": "authorised outcome",
  "units": [
    {"id": "unit-1", "status": "pending", "depends_on": []}
  ],
  "decisions": [],
  "evidence": []
}
```

The orchestrator is the only writer. Re-read it after compaction or when resuming. It is a simple checkpoint, not a scheduler or enforcement mechanism.

## Choose workers

Use an installed Coderails custom agent when its purpose matches the unit:

| Custom agent | Use |
|---|---|
| `preflight-scout` | Read-only intake, conflicts, and risk discovery |
| `design-scout` | A real design choice that must be resolved before building |
| `disposition-scout` | Decide whether replaced code should be removed or temporarily retained |
| `source-auditor` | Verify a reported symptom or factual claim before a fix |
| `loop-worker` | Implement and verify a scoped unit |
| `spec-reviewer` | Independently compare the result with the requested outcome |
| `deploy-safety-reviewer` | Review rollback, blast radius, and production safety |
| `docs-auditor` | Check documentation affected by the completed work |
| `wiki-writer` | Record an approved completed change in the project wiki |
| `proof-author` | Define observable checks before implementation when independence matters |

Use the normal Codex worker when no custom agent is a better fit. Do not invent a provider handoff.

## Dispatch with native Codex tools

For each ready unit:

1. Call `spawn_agent` with a self-contained prompt.
2. Save the returned id and add the unit to `update_plan`.
3. Collect the result with `wait_agent`.
4. Use `send_input` only for a specific correction or missing check.
5. Call `close_agent` when the worker is complete, failed, or abandoned.

Respect a user-set concurrency limit. Otherwise run no more than three independent workers at once. Never dispatch a unit whose dependency is unfinished.

Each worker prompt must include:

- the exact task and allowed paths;
- the checkout or worktree path;
- relevant facts already verified in this session;
- the expected files or external artifacts;
- the checks the worker must run;
- explicit exclusions and permission limits;
- the required terminal result and concise report format.

Require the worker to report the files changed, commands run, observed results, and anything not verified. A task list entry is not a substitute for this prompt.

## Keep ownership clear

Give each unit one owner. When reports cross in flight or a worker goes quiet, inspect the actual artifact before redispatching. An idle or missing message is not proof that the work failed.

If the artifact is missing, send one focused follow-up with `send_input`. If it still cannot continue, close it and spawn a replacement with a distinct unit name. Do not keep dead workers open.

## Verify before fixing

For a reported bug or stale-state claim, first spawn `source-auditor` with read-only instructions to reproduce the symptom from the source of truth. Start implementation only when the symptom is observed. If it is disproven, report that evidence and stop the fix.

For a confirmed failure, allow up to five distinct diagnosed repair attempts. Repeating the same action is not a new attempt. Stop and report after the bound is exhausted.

## Review and release

After implementation, spawn a fresh Codex reviewer such as `spec-reviewer`. Give it the user request, success criteria, and current diff or artifact, but not the implementer's conclusions. Add `deploy-safety-reviewer` only when the change has a production or release surface.

Treat worker reports as claims. Before releasing a dependent unit or reporting completion, re-check the relevant artifact in the current session: repository status, diff, test result, PR state, deployment record, or log entry. Use the repository's Codex workflow skills for push, review evidence, eval evidence, and merge when those steps are in scope.

## Finish

Before the final response:

1. Wait for or close every active worker.
2. Re-run the smallest complete set of success checks in the current session.
3. Mark every plan item completed or state why it was dropped.
4. Report the produced artifacts, verification evidence, and remaining limits.

For long work, write a minimal `retro.json` beside `progress.json`:

```json
{
  "status": "complete",
  "scope": "authorised outcome",
  "artifacts": [],
  "verification": [],
  "unverified": [],
  "decisions": []
}
```

Do not claim completion from worker summaries alone. The final claim must rest on evidence observed in the current session.
