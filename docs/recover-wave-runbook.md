# recover-wave runbook (Codex graph CLI)

Symptom: a wave is `active` (`graph.py summarize STATE` says `waiting for worker`) but nothing is progressing.

## Query

```bash
python3 packages/codex/skills/agentic-loop/scripts/graph.py recover-wave "$STATE" --session "$SESSION" --report-only
jq -r '[.ts, .reason_code, .node_id, .attempt, .node_action, .caller_session] | @tsv' "$(dirname "$STATE")/recovery-trace.jsonl"
jq -s 'unique_by(.event_id) | group_by(.reason_code) | map({code: .[0].reason_code, events: length})' "$(dirname "$STATE")/recovery-trace.jsonl"
```

Refusals also print `[reason_code=<code>]` on stderr. Each row carries `ts` (UTC), `node_action` (`dispatch`, `record`,
`waiting`, `stalled`; null on refusals) and `caller_session` (the session that asked; `session_id` is the owner).
Refusal rows name the implicated node and attempt.

`recovery-trace.jsonl` sits beside `progress.json`. It is advisory: it is never read to derive state, and a failed
trace write never fails or changes a transition. Counters: `python3 scripts/measure_graph_alignment.py --root . --json`
(key `recovery`).

## Reason codes and remediation

| reason_code | Meaning | Remediation |
| --- | --- | --- |
| `recovered` | Every spawned worker was silent past the lease; the wave was recorded `stale` and respawn requested in one save. | `begin-wave`, then spawn the `_aN` task names it prints. |
| `no_spawn_dispatch` | A node has no native spawn. Nothing is recorded. | Spawn it now (or, if the spawn is refused, the `launch_refused` evidence applies). |
| `worker_finished_record` | A worker already completed. | `record-wave` it; never recover a finished worker. |
| `worker_waiting` | A worker is inside the lease. | Wait, or rerun with a shorter `--lease-seconds` only if you know it is dead. |
| `stalled_report_only` | Every spawned worker is stalled and `--report-only` was given. | Rerun without `--report-only` to recover. |
| `mixed_wave` | Some nodes are stalled, others not. All-or-nothing: nothing changes. | Read `node_action` per row to find the non-stalled nodes; handle them first (record, spawn or wait), then rerun. |
| `recovery_budget_exhausted` | A node's respawn generation reached `retry.max`. Fails closed. | A human decides: `hard-stop --node N --reason ...` or fix the cause. |
| `foreign_session` | `--session` does not own the loop. | Use the owning session id. |
| `unreadable_transcript` | A parent or child transcript is missing, empty, foreign or lacks a timestamp. | Repair or locate the transcript; recovery will not guess. |
| `ambiguous_spawn` | Codex only: a node has several silent spawns for one attempt; stale evidence needs exactly one. | Inspect the duplicate spawns; record or hard-stop the node by hand. |
| `no_active_wave` | There is no wave to recover (already recovered or recorded). | `summarize` and continue from its phase. |

# start / add-unit runbook (both providers)

Symptom: `graph.py start` or `graph.py add-unit` exits 1 and prints `graph: ... [reason_code=<code>]`.

```bash
# one event writes one row per node: count events (distinct event_id), not rows
jq -s 'map(select(.outcome=="refused" and (.command=="start" or .command=="add-unit"))) | unique_by(.event_id) | group_by(.reason_code) | map({code: .[0].reason_code, events: length})' "$(dirname "$STATE")/recovery-trace.jsonl"
jq -r 'select(.command=="start" or .command=="add-unit") | [.ts, .command, .outcome, .reason_code, .node_id] | @tsv' "$(dirname "$STATE")/recovery-trace.jsonl"
```

Same sidecar and row schema as recover-wave (`command` distinguishes the rows). The trace is advisory and written after
the state commit; a refusal never changes `progress.json`. Counters: `measure_graph_alignment.py` key
`recovery.controller` (`starts`, `add_units`, `refusals_by_reason`).

| reason_code | Meaning | Remediation |
| --- | --- | --- |
| `start_created` / `start_rearmed` / `start_noop` | Created, re-armed over a completed loop, or an idempotent retry of the same loop id. | None. |
| `start_refused_active_loop` | A different loop id over an unfinished loop. | Resume it (`inspect`, `summarize`); only a completed loop can be re-armed. |
| `start_refused_loop_complete` | The same loop id over a loop already `complete` (a noop would leave the guard demanding `start` forever). | Run `start` again with a fresh `--loop-id`. |
| `start_refused_session` | Blank or `?` session, or the file belongs to another session. | Use this session's id; never adopt another session's file. |
| `start_refused_path` | STATE is not `<session>/progress.json`, or the file is locked or unreadable. | Resolve the path with the path helper; inspect or repair the file. A Claude `progress.json.lock` directory left by a killed process must be removed by hand. |
| `add_unit_registered` | Unit, node, edges and join input written in one save. | None. |
| `add_unit_refused_bad_id` | Unit id is not `[1-9][0-9]*`. | Use a positive integer without leading zeros. |
| `add_unit_refused_duplicate` | The unit or its `U3[n]` node already exists. | Pick the next id; do not re-register. |
| `add_unit_refused_unknown_dep` | `--depends-on` names a unit not yet registered. | Register the dependency first. |
| `add_unit_refused_cycle` | The kernel found a dependency cycle. | Inspect `graph.edges` and the join; remove the bad edge. |
| `add_unit_refused_foreign` | `--session` or `--loop-id` does not own the file. | Use the owning ids. |
| `add_unit_refused_state` | Not in-progress, a wave is active, the join is already released, or the file is absent or corrupt. | Wait for the wave to be recorded, or repair or `start` the loop. |
