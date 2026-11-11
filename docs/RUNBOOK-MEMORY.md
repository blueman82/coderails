# Memory and standing instructions

[Runbook](RUNBOOK.md).

## Current request and citation boundary

Run decision, standing instruction, lesson, and handoff commands from the mapped project repository.
The graph key directory and the plugin checkout are different paths. Current reads do not use `--all-projects`.

A local saved result must have its R-id, source window, project, and a receipt for the same task call.
It must also have one current K-id and revision with the expected type, task, and content.
A task that the caller sends or Muninn accepts has no saved Note until the write is complete.

The reader keeps the Note body, cause, conditions, expiry, and full mapping of selected sources.
It checks each mandatory E-id, ref, hash, and selection through public `open` and `quote-check` calls.
Use only primary, unflagged, unredacted user prompts directly from the owner as sources.
A missing selection, a changed source, incorrect scope or authority, or an empty quote causes explicit degradation.

Current Muninn has no `normal` or `restricted` class. The field `privacy_classification: unknown` records that limit.
The scope, source, redaction, and authority checks cannot show the semantic privacy class.
The standalone legacy adapter uses its own normal-only schema-v2 boundary.

A change to local lesson text cannot make it safe to send an unknown task again.
If the task and source session are the same, the earlier unknown observation and claim hash stay the same.
The result adds `reconciliation_reason: learning_request_unknown`. It does not infer a window or task call from text.
A new authored task or a different source session can record its own marker before it sends the task.

The reader can keep and display a conditional Note with its conditions. It does not infer that a free-text condition holds.
The dispatch, promotion, and view procedures of standing instructions give `learning_conditional_use_unsupported` until the consumer can keep and apply the conditions.
A Guide gives `learning_form_unsupported`.

Handoff reads saved local task calls first.
For more decisions for the same task, it can read completed RequestView metadata through `learn list --state completed`.
It selects the project and task before it reads the task records. The public API has no project or task selector or pagination for that list.
The reader does not log or show metadata for a different project or task.

Only a receipt with the same K-id and revision selects a task. Ambiguous joins cause a refusal.
Each decoded reply has a 2 MiB limit. Each scan has limits of 100 task calls, 100 current records, and 100 sources.

Reads of current tasks and other records have a 30-second budget for external calls. Each call has a 10-second limit.
A limit gives `learning_read_limit` and cannot give a success with no results. Handoff does not enqueue or retry tasks.

Source checks do not close the initial I qualification for native, live, installed, or release operation.
Codex live qualification has its own checks. Claude live qualification has open work.

## Decision recorded locally but Muninn sync degraded

- Symptom: The `graph.py record-decision` command gives `"exit_code": 3` and `muninn.reason_code`.
  The command appends the decision to `decisions_absorbed` in `progress.json` before it tries to sync.
  For `unknown` or `syncing`, examine the two stores before recovery. The Muninn store can contain a copy.
  If the loop started again during sync, the row can be gone.
  Log entries are `decision.record/recorded/ok` and then `decision.sync/<written|degraded|disabled>/<reason_code>`.

- Query: Run `python3 -c "import json;[print(r['seq'],r['muninn']) for r in json.load(open('progress.json'))['decisions_absorbed']]"`.
  Or run `grep '"command": "decision\.' <agentic-loop dir>/<session_id>/trace.jsonl`.
  For a chain check, run `python3 -c "import json,sys;sys.path.insert(0,'.');from scripts.lib import decision_record as d;print(d.verify_chain(json.load(open('progress.json'))['decisions_absorbed']))"`.

- Remediation: Use the saved `request_id` with `muninn learn show R_ID` from the mapped project repository.
  A pending task stays pending until its own committed receipt identifies one current Note for the same task and content.
  The `flush-decisions` command examines the saved R-id, source window, and project.
  It cannot send an unknown task again automatically without that binding. A caller quote cannot replace selected sources.

- Limits: The chain is a cooperating-agent safeguard. An agent with the same user ID can edit the file and chain.
  Only the head anchor in the file can find removal of the last row. The same agent can also edit that anchor.
  See `docs/typed-records-measurement.md`.

## Standing order stored without a cite, or a lesson missing from dispatch

- Symptom: The `orders.py record` command exits 3 with `muninn.reason_code`: `learning_pending`, `learning_request_unknown`, or `muninn_absent`.
  Or `lessons.py query` or `orders.py lessons` exits 3 with `{"degraded": ...}`. Or the list does not show an entry that you recorded.

  Before loop end, `record` prepares bound inputs and syncs the cited claim without changing lifecycle data.
  After the owned `progress.json` records `complete` durably, local apply records recurrence and aging in `orders.json`.
  Degradation keeps the previous K-id if there is one. The `lessons` command does not print ledger text when Muninn is down.
  The explicit switch is `memory.backend: off`. Log entries are `order.record|prepare|tick|render|import|cite` and `lesson.query|predicate`.

- Query: Run `python3 scripts/lib/lessons.py --dir <repo-key dir> --session <known native caller id> query --format contract` to read current cited lessons.
  The diagnostic `orders.py ... lessons` command also gives an `excluded` list. It lists retracted, expired, or superseded entries with `lesson_not_current`.
  For log entries, run `grep -E '"command": "(order|lesson)\.' <agentic-loop dir>/<session_id>/trace.jsonl`.
  A hand edit of `orders.json` causes `order_chain_broken`. The message names the entry.

- Remediation: Run `orders.py --dir <repo-key dir> --session <native session> cite <id>` from the mapped project repository.
  This examines the saved task call. The deprecated `--quote` input has no effect. The command reports `quote_ignored`.
  A timeout without a saved R-id remains unknown if the caller starts again. Do not send the task again.
  Legacy imports remain uncited local diagnostics and do not make a binding to a current task call.

- Apply contract: Use `--dir <repo-key dir> --session <provider session>` with logical `--loop` from `<repo-key dir>/<session>/progress.json`.
  Prepare the `record` inputs before loop end.
  The native `graph.py complete` command prepares standing instructions before it gets the loop lock.
  It checks the prepared source again with that lock. Then it records the end of the loop, releases the lock, ticks, and writes the views.

  Claude `mark-complete` uses the same path and also sets the invocation marker. The prepare step does not age entries.
  The tick holds the ledger lock and logs `orders_ticked` after the ledger write. An unsuccessful save of loop end does not age entries.
  To continue a pending tick or view write without a second age change, run the native command for loop end again.
  Do not edit `progress.json`.

  The view writer holds the ledger lock for the two views. The receipt checks the ledger and the two view hashes with the same lock.
  If the hashes differ, loop end stays pending. Run the native command for loop end again to write the views.
  The Claude Stop guard and Codex `verify-completion` block if the tick or bound views have unfinished work.
  If the installed Muninn API gives an error, the pending result and subsequent verifier give its actual code.

  Source code for the current task API cannot qualify native dispatch, installed operation, or a live memory write and read.
  Those checks must run independently. Use only the current cited claim for dispatch.

- Pre-D4 completed loop: Examine its saved verification records before admission by the same hash.
  The receipt follows only bookkeeping for loop end. Other graph changes continue to block. See `docs/decisions/2026-10-05-orders-vs-muninn-overlap.md`.

- Text replacement after loop end: Check if the observation for this session and loop is available. If so, explicit `record` captures `replaces_source` in the prepared row.
  The canonical `lesson_source` hashes the owned binding, authored fields, and predecessor. It skips mutable store observations.
  The command seals and saves it with the lesson.

  An ordinary tick recovers only the accepted row and keeps counters and verification records. Replay does not occur for an equal published token.
  The command keeps a subsequent authored source. Without a checked success receipt for this prepared row, a retry with different data stays pending.
  It does not write an incorrect receipt for loop end.

  The code does not add missing predecessor fields to historical records.
  A captured null has a different meaning. It cannot authorize subsequent replacement without its own published source or a matching checked acknowledgement.
  This applies without a subsequent edit. Explicit `record` remains available for a completed loop.

  Publication, loss of the receipt, and then a replacement can keep the operation pending.
  The saved facts cannot prove that the earlier write applied. Unbound updates to the pure model clear a previous source token.

- Recovery of prepared data: The default rejects changed sources.
  Before loop end, use `prepare --loop <logical loop> --refresh-from-sha256 <CURRENT evidence_sha256>` only with the canonical hash from the current prepare result.
  The check compares with the same ledger lock. Resolved directories, session, and logical loop must agree.
  The revision cannot go back. There must be no matching local tick or recurrence.

  Prepared records stay the same without lifecycle changes.
  Incorrect or stale hashes, incorrect sources, sources from a different owner, completed sources, and prior application cause a refusal with no change.
  If the replacement saves durably and the receipt write fails, the loop remains unfinished.
  Run ordinary `prepare` with the same data to repair the receipt without a new replacement or duplicate observation.

  After durable loop end, retry only `tick`. Flush and read pending source updates again before the last prepare or refresh.

- Receipt publication: D4 refuses linked prepare, receipt, and durable sidecar paths before a read, open, or create.
  It holds `orders.lock` and then `teardown.jsonl.lock`. It checks each previous physical LF JSONL object, finite JSON number, and terminal newline before deduplication.
  It keeps the previous bytes and atomically publishes a full fsynced sibling file.

  A short write continues until it is complete. If a write reports no bytes or stops on error before the end, the canonical records stay the same.
  If the result after replacement is ambiguous, retry ordinary prepare or tick. The retry does not duplicate lifecycle changes.
  The code refuses malformed records or records with no terminal newline without changing them.

  Put back the actual records. Do not truncate or skip the tail.

  Other teardown writers must use the same sidecar, framing, and atomic publication contract to keep concurrent entries.
  D6 does not use this contract. It has its own rule to deduplicate the latest step.

- Shared identity: The ID identifies the problem and scope before record, cite, or local apply. The ledger and each correct set of saved inputs use that ID.
  Historical prepared inputs continue to constrain identity after the loop data changes.
  They do not prove current eligibility, currentness, citation, or lifecycle effects.

  The same identity in a different session can count as a recurrence.
  A binding with different identity, one with a different owner, or one with a format error causes a refusal before it supersedes a store claim.

- Current citation: Only an explicit `record` can replace lesson text.
  The `cite` command reconciles the current tagged claim without a knowledge write. This also applies if the ledger has earlier text.
  An ID with an earlier cite but no current replacement causes a refusal. A first cite for a new uncited ID checks the owner's quote.
  Different current claims at the same time give `lesson_not_current`.

  Tick reads current data without a knowledge write. If Muninn is unavailable, it uses saved K-ids before stale prepared metadata and reports degradation.
  An idempotent tick retry can refresh metadata without repeating lifecycle changes. Promotion uses the current cited join without the cached write status.

- Limits: One same-user ledger lock covers currentness, reconciliation, bounded sync, and the atomic ledger write.
  It cannot guarantee one and only one update across the network. Current tagged claims reconcile for degraded and pending local records.

  Only a new completed session and loop recurrence resets a counter or revives a tombstone.
  Replay of the same observation cannot reset it. Current lesson consumers check project, task, revision, live sources, owner authority, redaction status, and selected user quotes.

  The checks cannot establish the semantic privacy class. Current Notes give `privacy_classification: unknown`.
  The standalone legacy schema-v2 CLI keeps its own normal-only boundary. For I, the initial graph metadata and native integration have no qualification.

  The diagnostic `orders.py lessons` command can show `cited: false` rows. Contract queries, promotion, and views exclude them.
  Owner-cited lesson text can be typed memory. Advisory transcript observations stay metadata.
  Read errors exit 3 without a ledger-text fallback. A new cited claim can supersede previous text.

  Legacy import keeps the full source text, first-seen provenance, and decayed counters.
  It refuses entries with missing data or collisions or an external source path. It does not change the initial file.

- Legacy retry: Each row seals the SHA-256 of the source bytes. The `import-legacy` command skips a full cohort only when saved rows, timestamp, and source hash agree.
  It uses the same archive again only if the bytes agree. If the bytes are different, it publishes a new copy without replacing an occupied name.
  It refuses mixed or divergent rows.

  The command publishes the archive before it writes the ledger. An unsuccessful or uncertain save keeps the source and archive.
  Success requires a canonical ledger that agrees with the expected sealed rows.

- Graduation: Use 10 or more different completed source-bound retros, recurrence, and decay.
  Schema 2 records must have all typed fields and the hash of their actual completed `progress.json`.
  Schema 3 uses `retro_check.check`. If there is no validator, the result is `order_retro_validator_unavailable`. It does not give a known zero count.

  The ledger and source hashes are a cooperating-agent safeguard. The same user can edit the files and calculate the hashes again.
  See `docs/typed-records-measurement.md` and `docs/decisions/2026-10-05-orders-vs-muninn-overlap.md`.

- Lesson attribution: Give the known native caller ID with `--session`.
  The CLI also checks `CLAUDE_SESSION_ID`, `CLAUDE_CODE_SESSION_ID`, `CODEX_THREAD_ID`, and `CODEX_SESSION_ID` in that sequence.
  Explicit input wins. The reads for a join pass the ID through query, predicate, diagnostic lessons, and the view writer to the adapter's degradation logs.
  Source code and private fixtures do not prove that an installed provider session exports the setting.
