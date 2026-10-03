# recover-wave runbook (Codex graph CLI)

Symptom: a wave is `active` (`graph.py summarize STATE` says `waiting for worker`) but nothing is progressing.

## Query

```bash
python3 packages/codex/skills/agentic-loop/scripts/graph.py recover-wave "$STATE" --session "$SESSION" --report-only
jq -r '[.reason_code, .node_id, .attempt] | @tsv' "$(dirname "$STATE")/recovery-trace.jsonl"
jq -s 'group_by(.reason_code) | map({code: .[0].reason_code, rows: length})' "$(dirname "$STATE")/recovery-trace.jsonl"
```

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
| `mixed_wave` | Some nodes are stalled, others not. All-or-nothing: nothing changes. | Handle the non-stalled nodes first (record, spawn or wait), then rerun. |
| `recovery_budget_exhausted` | A node's respawn generation reached `retry.max`. Fails closed. | A human decides: `hard-stop --node N --reason ...` or fix the cause. |
| `foreign_session` | `--session` does not own the loop. | Use the owning session id. |
| `unreadable_transcript` | A parent or child transcript is missing, empty, foreign or lacks a timestamp. | Repair or locate the transcript; recovery will not guess. |
| `no_active_wave` | There is no wave to recover (already recovered or recorded). | `summarize` and continue from its phase. |
