# recover-wave runbook (Codex graph CLI)

Symptom: A wave stays `active` without a new result. `graph.py summarize STATE` reports `waiting for worker`.

## Query

```bash
python3 packages/codex/skills/agentic-loop/scripts/graph.py recover-wave "$STATE" --session "$SESSION" --report-only
jq -r '[.ts, .reason_code, .node_id, .attempt, .node_action, .caller_session] | @tsv' "$(dirname "$STATE")/recovery-trace.jsonl"
jq -s 'unique_by(.event_id) | group_by(.reason_code) | map({code: .[0].reason_code, events: length})' "$(dirname "$STATE")/recovery-trace.jsonl"
```

Refusals also print `[reason_code=<code>]` on stderr. Each row has `ts` (UTC), `node_action`, and `caller_session`.
The values of `node_action` are `dispatch`, `record`, `waiting`, and `stalled`. Refusals use null.

The `caller_session` field identifies the caller. The `session_id` field identifies the owner. Refusals also identify the node and `attempt`.

`recovery-trace.jsonl` is next to `progress.json`. The controller does not use the advisory log to find graph data.
If a log write fails, it cannot block or change a graph update.
For counters, run `python3 scripts/measure_graph_alignment.py --root . --json`. Read `recovery`.

## Reason codes and remediation

| reason_code | Meaning | Remediation |
| --- | --- | --- |
| `recovered` | All spawned workers were silent after the lease expired. One write marks the wave `stale` and asks for a new spawn. | Run `begin-wave`. Then spawn the `_aN` task names it prints. |
| `no_spawn_dispatch` | A node has no native spawn. The command writes nothing. | Spawn it. If the spawn gives a refusal, use the `launch_refused` records. |
| `worker_finished_record` | A worker finished. | Run `record-wave` for the worker. Do not use the recovery command on a finished worker. |
| `worker_waiting` | A worker is in its lease interval. | Wait. Use a shorter `--lease-seconds` only if you know the worker is dead. |
| `stalled_report_only` | All spawned workers stalled. The caller used `--report-only`. | Run the command again without `--report-only`. |
| `mixed_wave` | Some nodes stalled and others did not. Nothing changes. | Read `node_action` in each row to find nodes that did not stall. Record, spawn, or wait for them first. Then run the command again. |
| `recovery_budget_exhausted` | A node's respawn generation reached `retry.max`. The command refuses to continue. | A human can run `hard-stop --node N --reason ...` or correct the cause. |
| `foreign_session` | `--session` does not own the loop. | Use the owning session ID. |
| `unreadable_transcript` | The transcript for the parent or child cannot be found, is empty, has a different session ID, or has no timestamp. | Repair or locate the transcript. The command does not infer missing data. |
| `ambiguous_spawn` | Codex only. A node has more than one silent spawn for one try. The stale check needs one spawn. | Examine the duplicate spawns. Record or hard-stop the node by hand. |
| `no_active_wave` | There is no active wave. The caller used recovery or recorded the wave before this call. | Run `summarize` and continue from the reported phase. |

# legacy task identity runbook (Codex graph CLI)

Symptom: `record-wave`, `recover-wave`, `complete`, or `verify-completion` exits 1 with
`... carries a pre-loop-scoped task name ... [reason_code=legacy_task_identity_refused]`.
A saved ref or stale run has a node-only worker name (`loop_worker_<node-hex>[_aN]`).
The commands accept only loop-scoped names (`loop_worker_<loop-hex>_<node-hex>[_aN]`).

```bash
# Count one refusal for each unique event_id.
jq -s 'map(select(.reason_code=="legacy_task_identity_refused")) | unique_by(.event_id) | map({ts, command, node: .node_id, attempt, caller_session})' "$(dirname "$STATE")/recovery-trace.jsonl"
python3 scripts/measure_graph_alignment.py --root . --json | jq .recovery.legacy_task_refusals
```

The sidecar and row schema are the same as for `recover-wave`.

The diagnostic log is advisory. A refusal does not change `progress.json`.

| reason_code | Meaning | Remediation |
| --- | --- | --- |
| `legacy_task_identity_refused` | The node's spawn for the cited run has a node-only name. No shim reads it again. The `attempt` field in the log identifies the refused run. The `caller_session` field is the `--session` value. It is null for `record-wave`, which uses no such value. | A done node cannot reopen. The `begin-wave` command dispatches only nodes that can run. Start a new `--loop-id` and run the work again. Do not edit verification records or the transcript. The `verify-completion` command used to succeed for **completed** loops with node-only names. The current policy refuses those loops. |

# start / add-unit runbook (both providers)

Symptom: `graph.py start` or `graph.py add-unit` exits 1 and prints `graph: ... [reason_code=<code>]`.

```bash
# A call writes one row for each node. Count unique event_id values.
jq -s 'map(select(.outcome=="refused" and (.command=="start" or .command=="add-unit"))) | unique_by(.event_id) | group_by(.reason_code) | map({code: .[0].reason_code, events: length})' "$(dirname "$STATE")/recovery-trace.jsonl"
jq -r 'select(.command=="start" or .command=="add-unit") | [.ts, .command, .outcome, .reason_code, .node_id] | @tsv' "$(dirname "$STATE")/recovery-trace.jsonl"
```

The sidecar and row schema are the same as for `recover-wave`. The `command` field distinguishes the rows.
The controller writes the advisory diagnostic log after the update. A refusal does not change `progress.json`.
For counters, read `recovery.controller` in `measure_graph_alignment.py` (`starts`, `add_units`, `refusals_by_reason`).

| reason_code | Meaning | Remediation |
| --- | --- | --- |
| `start_created` / `start_rearmed` / `start_noop` | A new loop, rearm of a completed loop, or an idempotent retry with the same loop ID. | None. |
| `start_refused_active_loop` | The caller used a different loop ID while a loop was active. | Continue it with `inspect` or `summarize`. Rearm only a completed loop. |
| `start_refused_loop_complete` | The caller reused the ID of a loop marked `complete`. A no-op would make the guard keep asking for `start`. | Run `start` again with a new `--loop-id`. |
| `start_refused_session` | The session is empty or `?`, or the file belongs to a different session. | Use this session's ID. Do not use a file that a different session owns. |
| `start_refused_path` | The path is different from `<session>/progress.json`, or the file is locked or unreadable. | Use the path helper. Examine or repair the file. Remove by hand a Claude `progress.json.lock` directory that remains after its owner stops. |
| `add_unit_registered` | One write adds the unit, node, edges, and join input. | None. |
| `add_unit_refused_bad_id` | The unit ID does not satisfy `[1-9][0-9]*`. | Use a positive integer without leading zeros. |
| `add_unit_refused_duplicate` | The unit or its `U3[n]` node exists. | Use the next ID. Do not add it again. |
| `add_unit_refused_unknown_dep` | `--depends-on` names a unit that has no registration. | Add the dependency first. |
| `add_unit_refused_cycle` | The kernel found a dependency cycle. | Examine `graph.edges` and the join. Remove the incorrect edge. |
| `add_unit_refused_foreign` | `--session` or `--loop-id` does not own the file. | Use the owning IDs. |
| `add_unit_refused_state` | The loop is not `in-progress`, a wave is active, the join has released, or the controller cannot find or read the file. | Wait for the wave record, repair the loop, or run `start`. |
