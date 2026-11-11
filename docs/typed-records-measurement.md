# Typed record measurement

This document compares hand-written loop records with typed records for decisions, standing instructions, lessons, retrospective data, handoffs, and proof results.
Counts come from source checks and diagnostic log entries. They cannot show that an installed provider used a control.

| Verification | Status |
|---|---|
| Source | The named Python writers and validators exist in the candidate plugin. |
| Local | The named tests check record structure, chains, refusals, and recovery on local fixtures. |
| Installed | Run live tests that accept and refuse operations in each installed provider. |
| Operation | Muninn sync and loop-end counts apply to a named session and its saved records. |

## Decisions (`decisions_absorbed`)

| Measure | Before | After | How measured |
| --- | ---: | ---: | --- |
| Writers of `decisions_absorbed` in code | 0 (instructions told the model to append by hand) | 1 (`scripts/lib/decision_record.py`) | Run `grep -rln "decisions_absorbed" scripts hooks packages`. Remove tests, Markdown, and the TypeScript dashboard reader from the results. Only `decision_record.py` and its mirror remain. |
| Rows with a hash chain | 0 | Each row that `record` appends | `decision_record.verify_chain(rows)` gives `[]`. |
| Rows synced to Muninn | 0 | `muninn.state == "written"` rows | `decisions_absorbed[*].muninn` |
| Silent loss when Muninn is down | n/a | 0: the writer keeps the local row, logs `decision.sync/degraded/<code>`, and exits 3 | `decision_record_test.py` |

The `scripts/lib/memory_counters.py` module counts `decision.record` and `decision.sync` entries in `by_command` and `by_reason_code`.
The `scripts/measure_graph_alignment.py` script includes them in `memory` without changes.
See "Decision recorded locally but Muninn sync degraded" in `docs/RUNBOOK.md`.

## Limits (written, not hidden)

- The chain is a cooperating-agent safeguard. The same user can rewrite the file and calculate all hashes again.
  The chain alone cannot detect removal of the last row.
- Muninn refuses a short approval cite. An agent cannot cite its own text.
  Use a quote from the owner's `authorising_prompt_raw` or a substantive `cite_quote` that the caller supplies.
  An approval prompt such as "yes" gives `cite_too_short`. The degradation stays in the output until the caller gives `flush_pending` a substantive user quote.
- Only the orchestrator session can write. Muninn cannot cite subagent threads.
- The writer uses `confidence=inferred`. Muninn can supply the decision only on a read.

## Standing orders and lessons (`orders.json`)

| Measure | Before | After | How measured |
| --- | ---: | ---: | --- |
| Writers of standing instruction counters in code | 0 (instructions told the model to edit Markdown by hand) | 1 (`scripts/lib/orders.py` uses `orders_ledger.py`) | Run `grep -rln "loops_since_recurrence" scripts hooks packages`. Remove tests and Markdown. Only `orders_ledger.py`, `orders.py`, `lessons.py`, and their Codex copies remain. |
| Entries with a hash chain | 0 | Each entry that `orders.py` writes | `orders_ledger.verify(ledger)` gives `[]`. A hand edit gives `order_chain_broken` and names the entry. |
| Rule for decay | instructions ("K=5") | `orders_ledger.K = 5`. Tests check 4 ticks (active) and 5 (decayed). The decayed entry stays in the ledger. | `scripts/tests/orders_test.py` |
| Graduation condition | The model counted files and read Markdown. | 10 or more different completed source-bound retros, typed recurrence, and decay. | `orders_test.py`, `lessons_test.py`, `orders_lifecycle_test.py` |
| Lessons for dispatch | The model copied from Markdown. | `lessons.py query --format contract`: sorted, verbatim, stable SHA-256. | `lessons_test.py` |
| Unavailable currentness | n/a | Exit 3, previous K-id kept, and no ledger-text fallback. | `orders_test.py`, `orders_repair_test.py`, `lessons_test.py` |
| Lifecycle effect before durable loop end | The instructions applied a tick before loop end. | No effect. Record and prepare hold inputs. Tick applies only after the owned loop data records its end. | `orders_lifecycle_test.py` |
| Recovery of changed prepared inputs | No binding for prepared inputs. | Explicit compare-and-swap with the current hash. The command keeps prepared records without lifecycle effects. | `orders_prepare_test.py` |
| Citation chronology | Cached ledger or prepared data could put earlier claims or IDs back. | Cite reconciles without a write to knowledge. Tick reads current metadata and keeps subsequent known IDs during outages. | `orders_current_test.py` |
| Legacy archive interruption | A source move could put the saved rows and their saved copy in different locations. | The writer publishes an archive with the same bytes before it writes the ledger. The source stays in its directory. A retry with the same full cohort skips a second save. | `orders_import_capture_test.py`, `orders_legacy_test.py` |
| Recovery of a replacement for a completed lesson | Earlier records could acknowledge an unsaved edit for the same loop. | The captured predecessor and sealed authored-source token recover only the accepted row. | `orders_retry_view_test.py` |

The `scripts/lib/memory_counters.py` module counts `order.record|prepare|tick|render|import|cite` and `lesson.query|predicate` in `by_command` and `by_reason_code`.
The `scripts/measure_graph_alignment.py` script includes them in `memory` without changes.
See "Standing order stored without a cite, or a lesson missing from dispatch" in `docs/RUNBOOK.md`.
The decision is in `docs/decisions/2026-10-05-orders-vs-muninn-overlap.md`.

Claude and Codex native loop end must prepare, check the graph write, tick, and write views.
The two Stop checks refuse missing or stale D4 receipts and views.
A previous completed graph can use source-bound admission after explicit inspection. Admission does not change loop data or age standing instructions.
The admission check compares the full file hash. Subsequent bookkeeping for loop end does not revoke it.

The `orders_ticked` entry records work after the ledger write. If local apply or receipt write fails after loop end, teardown stays pending.
One same-user lock covers currentness, reconciliation, bounded sync, the ledger write, and the two view writes.
The receipt checks the ledger and the two view hashes with the lock. It cannot guarantee that a network operation happens only one time.

New completed recurrences revive tombstones. Replay cannot set the counters again.
Current live lesson text with a checked owner cite can be typed memory. Transcript advisory observations stay metadata.

Uncited claims are diagnostic. The dispatch, promotion, and view writers do not use them.
The writer refuses claims with more than 500 collapsed characters. It does not truncate them.

Schema 3 history uses the matching `retro_check` validator. Without it, the result is unknown or refused.
The chain and source hashes act as cooperating-agent safeguards.
Legacy fixture imports keep all five entries, counters, full text, and first-seen provenance. The tests did not check a live migration of a hand-written file.

Each imported row seals the SHA-256 of the full raw source with its preamble. A retry checks that hash and each saved row.
The archive is a different copy, so the source stays in its directory.
After a write error, a correct import must have a canonical ledger equal to the expected sealed rows.
If it does not, the command refuses and keeps the archive. It does not publish the archive and ledger atomically together.

Current reads skip nonfinite expiries. Scope labels stay as Muninn gives them in the repo list selected by cwd.
Receipt parsing checks physical LF records and finite JSON numbers. It accepts Unicode in a correct JSON string.
The reader refuses linked prepared data, receipt, and sidecar paths before a read, open, or create.

For an explicit replacement with saved session and loop records, prepared `replaces_source` records the canonical `lesson_source`.
It records null explicitly if there was no source. The token hashes the owned binding and authored fields, without mutable Muninn observations.
The writer saves the token with the lesson in the chain.

Tick applies only if there is no observation or if the replacement has the same predecessor.
An equal published source means the update took effect. Tick keeps a different subsequent authored source.
Without a checked success record for the same prepared inputs, it gives exit 3 and stays pending.

An unbound pure `record` update clears the previous token. The writer does not invent missing predecessor data for previous records.
A captured null cannot authorize a subsequent replacement without its own published source or a checked acknowledgement for that replacement.
An unchanged null predecessor cannot prove authorship.

Explicit record remains available for a completed loop. Publication, loss of a receipt, and a replacement can keep the operation pending.
The latest source and predecessor cannot prove that the previous write took effect.

## Retro and handoff (`retro.json` schema 3, `teardown.jsonl`, `handoff_derive.py`)

This part gives the lane D measurements for the retrospective and handoff.

| Measure | Before | After | How measured |
| --- | ---: | ---: | --- |
| Writers of `retro.json` | The model used a prose table and wrote it by hand. | 1 (`scripts/lib/retro.py assemble`) | In `scripts/tests/retro_test.py`, the two providers refuse a hand-written v2 or hash-less v3 retro with `retro_not_assembled`. |
| Hash checks on source copies in the retro | 0 (Codex and Claude read only `schema_version >= 1`) | 7 source hashes and 3 verbatim copies. See below. | `retro_check.source_hashes` and `retro_test.py`. A change of one decision byte gives `retro_source_mismatch` for `progress.decisions_absorbed`. Codex gate checks use `packages/tests/test_codex_completion.py`. |
| Decision chain check at loop end | no | yes, `retro_decisions_chain_broken` gives the seq | `retro_test.py`, `test_codex_completion.py` |
| Verification that teardown steps ran | none (prose "run these five steps in order") | `teardown.jsonl` must have `proof_run`, `decisions_flushed`, `orders_prepared`, and `retro_assembled` in that sequence. The `orders_ticked` step records apply after loop end. The `lessons_written` step is optional. A missing step gives `retro_steps_missing`. | The `retro_test.py` sequence test and its control with the check removed. |
| Source for proof verdict | Same-string check on transcript text before the proof-results unit | The controller uses hash-chained run rows. The retro also records a hash for `proof_results.jsonl`. | `proof_run_test.py`, `retro_test.py` |
| Handoff Goal/Decisions/Done/Next | The model used conversation memory. | The `handoff_derive.py` JSON skeleton uses graph `summarize` and `inspect`, loop data, Muninn decisions with K-ids and cites, lessons, and proof status. An unreachable source gets a code in `degraded[]` and exit 3. | `scripts/tests/handoff_derive_test.py` |
| Silent loss when Muninn is down | n/a | 0: the gate permits loop end to prevent deadlock. It prints `Memory degraded: N decision(s) not in Muninn (<reason>: n)`. The handoff gives the cause. | `retro_test.py` degradation test, `loop_stall_guard_test.py` |

The seven sources are `progress.decisions_absorbed`, `progress.loop_stop_counts`, `progress.authorising_prompt_raw`, `evals.json`, `proof.json`, `proof_results.jsonl`, and `teardown.jsonl`.
The three copies are `decisions_absorbed`, `envelope`, and `loop_stop_counts`.

The `scripts/lib/memory_counters.py` module counts `retro.assemble`, `teardown.step`, and `handoff.derive` using prefixes `retro.`, `teardown.`, and `handoff.`.
Run `python3 scripts/measure_graph_alignment.py --root . --json` and read `memory` fields `rows`, `by_command`, and `by_reason_code`.
Examples of command counts are `teardown.step`, `retro.assemble`, and `handoff.derive`. Cause codes include `ok`, `memory_degraded`, and `muninn_absent`.
The measurement script stays the same.

A healthy loop has one `retro.assemble/assembled/ok` row and four or more `teardown.step` rows.
A `retro.assemble/degraded/memory_degraded` row means Muninn was unreachable during flush.
The gate logs refusals as `retro_gate=<code>` in the discipline log (`hook=loop_stall_guard`).
Its codes are `retro_not_assembled`, `retro_source_mismatch`, `retro_decisions_chain_broken`, and `retro_steps_missing`.
See "Retro rejected at completion, or a handoff printed `degraded`" in `docs/RUNBOOK.md`.

The hashes and chains are a cooperating-agent safeguard. The same user can edit the sources and assemble again.
The source hash skips loop-end counters because the hook increments the counter when it consumes the declaration.
The prepare check removes a capitalized `Complete` counter that was added after prepare only if the remaining data reproduces the bound hash.

The `free` section has no hash. An artifact or inspection theme there is only as reliable as its check.
The Codex retro has empty `cost` and `hook_blocks`. The package has no miners for them.

If Muninn rows reach `written` after assembly, the decisions hash changes. Assemble again after a subsequent flush.
The handoff skeleton gives the contents of recorded data. It does not prove that the contents are correct.
The matrix owner updates rows 13 and `gap5` after merge.

## Proof results (`proof_results.jsonl`)

| Measure | Before | After | How measured |
| --- | ---: | ---: | --- |
| Executor for a frozen proof cmd | The model used Bash and the gate checked transcript text. | The controller runs the same command in pinned sandbox-runtime 0.0.65. | `proof_sandbox_test.py` tests the two providers, a compound command, blocked host writes, and a blocked loopback connection. |
| Record that the gate reads | A transcript tool pair in Claude, or an exec result frame and `status == pass` in Codex. | Hash-chained run rows for the two providers. | In `proof_run_test.py`, a transcript that agrees cannot satisfy the proof. |
| `expect` | The instructions had prose that the gate did not check. | The gate checks `{exit_code, stdout_contains, stdout_not_contains}`. | The `proof_run_test.py` expect tests report an error if the check is removed. |
| Tamper detection | none | An edit to `proof.json`, an incorrect command hash, or removal of a row before the last row blocks (`proof_stale_cmd`, `proof_chain_broken`). The gate cannot find removal of a tail if the prefix is correct. | The `proof_run_test.py` mutation controls and inspection of the current head. |
| Codex loop with no executable surface | The loop could not end. | The loop can end with `none: <reason>` or a typed decision about proof execution. | `packages/tests/test_codex_completion.py` |

The `scripts/lib/memory_counters.py` module counts `proof.freeze|run|gate` with prefix `proof.`.
The `scripts/measure_graph_alignment.py` script includes them in `memory` without changes.
See "Proof gate blocked a `complete` declaration" in `docs/RUNBOOK.md`.

The same user can forge rows and calculate the chain again. This is a cooperating-agent safeguard.
The gate checks if the frozen command ran and met `expect`. It cannot assess proof quality.

The freeze hashes canonical JSON. To change a proof, freeze again after the edit. The command logs that freeze.

The command accepts and ignores `graph.py complete --transcript`. Freeze refuses schema 1 proofs because they ignore structured `expect`.
The destructive classifier uses literal patterns. The sandbox is a different control.

Each run row records HEAD. The gate refuses a stale HEAD. The gate has no off-switch.
