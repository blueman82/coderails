# Graph-alignment measurement notes

[Provider parity measurements](graph-alignment-measurement.md).

## Stale mkdir lock recovery (runbook)

Before this change, a hook that got SIGKILL could leave `progress.json.lock` or `verification-ceiling/*.count.lock` indefinitely.
Subsequent `atomic_progress_update` calls gave `False`. The verification ceiling denied all commands.
The two callers use `hooks/scripts/lib/dir_lock.py` to get the lock.

The lock directory has `owner` = `{pid, host, start, ts}`. The `start` value comes from `ps -o lstart=`.
The lock code takes an owned lock only if it can prove the owner is gone.
This happens if `os.kill(pid, 0)` raises `ProcessLookupError` or if a live PID has a different start time.
The result `PermissionError` means the owner is live and the code keeps the lock with its owner.

An empty, torn, or missing owner file can occur between mkdir and the owner write.
The code takes such a lock only if its mtime is older than `CLAUDE_LOCK_STALE_S` (default 60).
A live owner keeps its lock regardless of age. A future mtime counts as young because clocks can disagree.

The takeover uses `os.rename(lock, lock.stale.<pid>.<uuid>)`. One caller wins the race and the other callers retry `mkdir`.
The code checks the owner in the renamed directory against the owner from the first check.
If the owners are different, it puts the directory back and gives `lock_busy`. Release removes the lock only if the caller owns `owner.pid`.

The code writes advisory entries to `lock-events.jsonl` next to the lock. A write error cannot change the lock result.
The entries use `{ts, event_id, reason, schema:"lock_event", non_authoritative:true, lock, owner_pid, pid}`.
The last three fields give the lock path, the checked owner PID or null, and the acquirer PID.

| Code | Meaning |
| --- | --- |
| `lock_stolen_dead_owner` | The owner PID is gone or has a new owner. The caller takes the lock. |
| `lock_stolen_age` | The owner file is unreadable and the lock age is above the limit. The caller takes the lock. |
| `lock_busy` | The retry budget ran out while the lock was live, young, or ambiguous. |

Run `python3 scripts/measure_graph_alignment.py --root . --json`. The `lock_events` counts use each code.
They deduplicate by `event_id` across all loop data roots.

If a lock does not clear, check that its owner is gone with `cat <lock>/owner; ps -p <pid>`.
Move the directory with `mv <lock> /tmp/trash/`. Do not remove a lock with a live PID.

Two holders can briefly coexist if a new holder gets the lock before the rename and a third caller gets the vacated name before restoration.
For locks that name a different `host`, the code uses age only. This includes shared data directories on NFS or in containers.
It does not check the other host's PID with `kill -0`.
The check cannot detect same-second PID reuse with the same `lstart`.

The Codex hook uses a copy with the same bytes at `packages/codex/hooks/scripts/lib/dir_lock.py`. The `dir_lock_test` checks the copy.
Its entries go to `$PLUGIN_DATA/verification-ceiling/lock-events.jsonl`. This measurement script does not read that log.

**Reproduce.**

```
python3 -m unittest hooks.scripts.tests.dir_lock_test hooks.scripts.tests.lock_recovery_test
python3 packages/tests/test_codex_ceiling_lock.py
python3 -m unittest scripts.tests.measure_graph_alignment_test
```

## Typed stop intent and hook state (measurement note)

The `graph.py stop` command writes a `progress.stops[]` row.
The `loop_stall_guard` hook consumes the newest unconsumed row at the current revision and increments `loop_stop_counts` in one atomic write.
The hook does not read the last reply. If there is no row, it blocks Stop with `stop_row_missing`. It no longer logs `legacy_text_parse`.

Absent-state grace reads only `ordinals.absent_blocked` in `hook_state.json`. It does not use a `discipline.log` fallback.
The hook no longer logs `legacy_log_parse`. The name stays in `FALLBACKS` so the counters include historical entries.

The Claude hook accepts a row only if `graph.py stop` ran after the last user prompt. If it did not, the hook logs `stale_stop_row`.
The Codex guard logs the same `stop_row_missing` code with command `graph_completion_guard`. The ratio covers the two providers.

Counters are in `scripts/graph_alignment_stops.py`. The module `scripts/lib/stop_counters.py` supplies the block codes and counts `convert_ok` and `convert_refused_<code>`.
If `stop_row_missing` is high compared with `stops_consumed` in the first loops, fix the prompt so agents record the stop. The hook applies the strict check.

The Stop payload has no turn ID (unverified). The hook accepts a row only if its `at` time is at or after the last user prompt timestamp.
A prompt with no readable timestamp blocks the row. The async `voice_announce` can run after the guard consumes the row. It then says "may have stalled".

**Reproduce.**

```
python3 scripts/graph_alignment_stops.py --json
python3 hooks/scripts/tests/loop_stall_guard_test.py && python3 hooks/scripts/tests/loop_state_guard_test.py
PYTHONPATH=. python3 -m unittest packages/tests/test_provider_stop_record.py scripts/tests/graph_alignment_stops_test.py
```

## Gate counters (measurement note)

Run `python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/receipt_counters.py`.
Read `gate` next to `receipts` and `trust`.
It has `authority_denied`, `approval_requirement_missing`, `max_prs_exceeded`, `action_authority_bad_mode`, `authority_denied_destructive_shell`, `no_receipt`, and `merge_py_receipt_executed`.
The hook, `enforce_pr_workflow`, and `scripts/merge.py` use the same counters. The reader removes `denied_`, `advisory_`, and `merge_py_` prefixes.

There is no baseline from a live loop. The receipt gate and the example and init settings default to `enforce`, with or without a config file.
An explicit `action_authority: advisory` warns without a receipt. An explicit `off` disables this gate.

A count above 0 for `approval_requirement_missing` means a permit verdict did not name its approval condition. The gate refused before it consumed a receipt.
A count above 0 for `authority_denied` or `max_prs_exceeded` means the authority refused an operation. Examine the authority with `authority.py inspect`.

The `no_receipt` outcome can occur in advisory mode. In enforce mode, a high count means merges have no correct receipts.
An incorrect config value blocks an operation with `config_rejected`.
The owner of `measure_graph_alignment.py` can add `gate_summary` to that file. Until then, use the stdin command above.

## Strict typed config and wiki fail-closed (measurement note)

The protected operations read `.coderails/workflow.config.yaml` through `strict_settings` and deny with `config_rejected`.
The diagnostic log entries are `action_authority/denied/config_rejected`, `diff-manifest/refused/config_rejected`, and `wiki_taxonomy_gate/failed_closed/config_rejected`.
If the gate identifies the vault, a missing or incorrect `wiki.schema.json` also causes denial (`wiki_taxonomy_gate/failed_closed/wiki_schema_missing|wiki_schema_invalid`).

The `config.schema.json` settings `sandbox_workers`, `evals.require_signatures`, and `diff_manifest` default to ON.
The diff manifest gate stays off until the config has a policy path. The `action_authority` gate defaults to `enforce`.
For signed approval, use the owner's terminal. The passphrase is optional. The stack ships the receipt CLI for the two providers.

Without a config file, consumers of config other than the receipt gate do nothing.
The `plan()` function calculates `dispatch_mode`, and Phase 3c uses it.
The srt test checks for `npx` and `gh` on PATH. It does not check that the sandbox starts.

**Reproduce.**

```
python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/receipt_counters.py
PYTHONPATH=. python3 -m unittest hooks/scripts/tests/authority_permits_test.py
python3 scripts/lib/config_counters.py
python3 hooks/scripts/tests/config_strict_test.py && python3 hooks/scripts/tests/wiki_taxonomy_gate_test.py
```

## One attestation parser (measurement note)

For operator steps and cause codes, see [Typed records and attestation](typed-state-runbook.md).

The `scripts/lib/integrity_attestation.py` parser replaces two hand-written regex copies in the merge.py path and the PreToolUse merge hook.
Each denial in a session logs `pr_merge_gate/denied/<attest_code>`. The `scripts/lib/state_counters.py` script counts them.
A nonzero `attest_not_bound` count when the GitHub run succeeds can mean that the status description changed.
The parser accepts full `integrity=pass` and `sha=<head>` tokens and permits more fields.

The GitHub workflow does not import the local parser. The description test checks that the formats agree.
The `merge.py` command does not write a diagnostic log entry.

**Reproduce.**

```
python3 scripts/tests/integrity_attestation_test.py
python3 scripts/lib/state_counters.py
```

## Typed hook state, verdicts and readiness (measurement note)

The `hook_state.json` file (hooks/scripts/lib/hook_state.py) replaces `discipline.log` searches for grace and nudge dedupe.
Diagnostic entries include `hook_state_unreadable` (outcome `missing` or `torn`), `nudge_first`, and `nudge_suppressed`.
The `arms[]` array records each block due to missing status data.

If `EvalVerdict` blocks loop end, the hook writes `eval_verdict_<status>`.
The graph check writes `predecessor_pending`, `node_unknown`, `node_not_pending`, `graph_blocked`, or `join_not_dispatchable`.
Run `python3 scripts/lib/state_counters.py` to count these entries.
The counter has its own module because `scripts/measure_graph_alignment.py` is at its line limit. Integration into that script is a handoff.

A nonzero `hook_state_unreadable` with `torn` means a write did not succeed. Grace cannot release in that condition.
It is usual for `nudge_suppressed` to be much greater than `nudge_first` because there is one nudge for each session.
The hooks do not log GO verdicts or readiness outcome `state_unreadable`. The first Stop for each unregistered loop session gives `missing`.

**Reproduce.**

```
python3 scripts/lib/state_counters.py
python3 hooks/scripts/tests/hook_state_test.py && python3 hooks/scripts/tests/graph_readiness_test.py
```

## Stop text retired, shared vocabulary, versioned conversion (measurement note)

The two providers do not read the last reply. The `loop_stall_guard` and Codex `graph_completion_guard` release only on a recorded `stops[]` row.
The async `voice_announce` uses the same row for its category. If the guard consumes the row first, it says "may have stalled".

The single enum source is `packages/graph-semantics/graph_vocab.py`.
The installer in `scripts/installer/files.py` copies the same bytes into the two script directories next to `graph_semantics.py` and `graph_convert.py`.
It uses a list of source and target pairs that subsequent units use again.

The `graph.py convert` command logs `convert_ok` or `convert_refused_<code>` to `recovery-trace.jsonl`.
The `stop_row_missing` and `stale_stop_row` entries go to `trace.jsonl`.
Run `python3 scripts/lib/stop_counters.py` to count them.
The counter has its own module because `scripts/measure_graph_alignment.py` is at its line limit. Integration into that script is a handoff.

If `convert_refused_active_wave_ambiguous` occurs, an upgrade ran during an active wave. Finish or recover the wave first.
A sustained `stop_row_missing` count means the prompt does not teach `graph.py stop`.

The Stop payload has no turn ID (unverified). The hook compares the row timestamp with the latest user prompt timestamp.
If the prompt has no timestamp, the hook refuses the row. The `convert` command refuses if it cannot resolve an in-flight wave from a pre-history file.
Use manual recovery for that wave.

**Reproduce.**

```
python3 scripts/lib/stop_counters.py
python3 hooks/scripts/tests/graph_convert_test.py && python3 hooks/scripts/tests/loop_stall_guard_test.py
PYTHONPATH=. python3 -m unittest packages.tests.test_provider_stop_record packages.tests.test_provider_graph_lifecycle
```

## Machine-readable graph spec and policy (measurement note)

The node table comes from data files. The `packages/graph-semantics/graph-spec.yaml` file gives nodes, requirements, phases, instruction sources, and machine skip conditions.
The `policy.yaml` file gives thresholds, retry limits, and the default policy level.
The shared `graph_spec.py` module uses `json.loads` for the JSON-syntax YAML, then validates and expands the files.
The installer in `scripts/installer/files.py` copies the same bytes into the two script directories.

The providers refuse a load if the graph has two nodes but has no mandatory spec edge between them (`spec_edge_missing`).
The `graph.py instantiate` command writes `graph.spec_sha256`. For stamped graphs, the loader also refuses unknown nodes, missing spec nodes, and changed specs.
The `add-unit` and `plan` commands get wiring, instruction sources, and skip thresholds from the spec.
The previous `TARGETS` table and `before_freeze` regex are gone.

The `scripts/gen_graph_docs.py --check` command checks that the execution-graph table, its Mermaid diagram, and the threshold block come from the same files.
The `recovery-trace.jsonl` entries include `load/refused/spec_*`, `instantiate/<status>/instantiate_ok|instantiate_noop|instantiate_refused_*`, and `plan/reported/skip_when_met`.
Run `python3 scripts/lib/spec_counters.py` to count them.
The counter has its own module because `scripts/measure_graph_alignment.py` is at its line limit. Integration into that script is a handoff.

A sustained `spec_edge_missing` count after the first week means the loader got hand-built graphs or graphs from a different source.
The `spec_hash_mismatch` outcome means someone edited the spec while a stamped loop was active.
Compare `skip_when_met` with skipped nodes to check if the machine condition agrees with the orchestrators' records.

The default policy level is `full`. Set `units-only` to skip the prep and lifecycle nodes.
The loader checks join inputs only for stamped graphs (`spec_join_inputs`). A stamp below the policy level gives `spec_profile_downgrade`.
Unstamped graphs and graphs with removed stamps use the weaker check. The `CODERAILS_GRAPH_SPEC=off` setting disables the check.

Skip rules that use judgment stay in the instructions. The user can edit the spec files.
The check can find unintended changes and cannot prove that no one edited them.

**Reproduce.**

```
python3 scripts/lib/spec_counters.py
python3 scripts/gen_graph_docs.py --check && python3 scripts/tests/gen_graph_docs_test.py
PYTHONPATH=. python3 -m unittest packages.tests.test_graph_spec
```

## Structured dispatch envelope and role assertion (measurement note)

See [dispatch envelope measurements](graph-dispatch-measurement.md).

## Disposition, compat findings and typed worker statuses (measurement note)

Row 7 adds a code reader for the retirement fields.
The command `graph.py add-unit --disposition clean-break|preserve-compat [--named-blocker X --removal-ticket Y]` validates them in one function in `packages/graph-semantics/graph_vocab.py`.
For `preserve-compat`, the two fields must have values. For `clean-break`, the two fields must be empty.
The command writes `work_units[u].disposition`, which the dispatch contract had before this change.
The `disposition-audit` command and the two loop end gates check the data again for hand edits.

The inspection artifact gets a second typed line from `post_review.py compat-line`:
`<!-- coderails-compat-findings v1 pr=N head_sha=S count=K disposition=D -->`.
The `merge.py` command refuses `clean-break` with `K > 0` (`compat_findings_nonzero`).
It refuses a malformed line (`compat_findings_malformed`) or a missing line for the current head (`compat_findings_missing`).
The v1 marker line for the root-owned daemon has the same bytes as before.

Row 22 uses `worker_status.prepare()` before the unchanged core in the two `record_wave` paths.
If a result has `status`, the reader checks it. It refuses the full report on error (`worker_status_<code>`).
For a correct result, it writes `worker_statuses[]`, spends one retry, and writes one typed stop row.
If a dispatch has `final_report_required`, a `done` result must have a correct `final_report` (`final_report_invalid`).

Run `python3 scripts/lib/worker_counters.py`. It counts refusals `worker_status_<reason>` and `final_report_invalid` in `recovery-trace.jsonl`.
It counts accepted outcomes `worker_status_<status>` and `final_report_recorded` from the same log. It counts `pending_statuses` from `progress.json`.

The `decision_recorded` count uses `decision.record/recorded/ok` entries in the session's `trace.jsonl`.
This includes local records if a subsequent Muninn sync degraded.
The retirement check logs refusals as `add-unit/refused/add_unit_refused_disposition`.

A refusal count above zero can mean a worker gives a result with an incorrect structure. Correct the worker prompt.
If `pending_statuses` does not fall, the prompt asked about typed stops but the worker did not log them with `record-decision --worker-status-seq`.
The `decision_recorded` count gives local decisions. The `record_decision_refused_*` refusals appear as `record-decision/refused` entries.

Three typed stops on one node use all its retries. A high `worker_status_*` count for one node means the unit must get a human decision first.
Negative controls remove the `prepare()` call from `record_wave`, skip the keep-compatibility pair check, or ignore the compat line in `merge.py`.
Other controls drop the `final_report_required` branch or change `graph_semantics.py`.
Each control makes its test fail in `packages/tests/test_provider_disposition.py`, `packages/tests/test_provider_worker_status.py`, `scripts/tests/compat_findings_test.py`, or `hooks/scripts/tests/worker_status_test.py`.

The compat count and retirement selection use reviewer judgment.
The status spends a retry because the core has no outcome for work that needs a human.
The reader checks `final_report` structure and cannot tell if the report is correct.
The `merge.py` command has no loop session, so it does not log merge refusals.
The `measure_graph_alignment.py` script does not use `worker_counters` (handoff H1).

**Reproduce.**

```
python3 scripts/lib/worker_counters.py
python3 hooks/scripts/tests/worker_status_test.py
PYTHONPATH=. python3 -m unittest packages.tests.test_provider_disposition packages.tests.test_provider_worker_status packages.tests.test_provider_record_decision scripts.tests.compat_findings_test
```
