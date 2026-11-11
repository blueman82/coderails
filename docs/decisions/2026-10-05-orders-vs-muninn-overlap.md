# Standing orders vs Muninn: where the claim lives and where the counters live

## Decision

Two stores hold different fields of the standing instruction. Each field has one authority.

| Part | Data location | Purpose |
| --- | --- | --- |
| Cited claim: lesson text, K-id, cite, quote, and retraction, expiry, or supersession status. | Muninn holds a repository-scoped `lesson` tagged `order` and `ord-<id>`. | Muninn owns cited knowledge that comes from the user and can be retracted. A second copy would give it a second authority. |
| Counters and decay: `loops_since_recurrence`, `last_recurred`, `status`, `decayed_at`, record list, `scope`, and an append-only hash chain. | The scripts own `orders.json` in the repo-key directory, two directories above `progress.json`. | Muninn has no operation to update or touch a record. Each Muninn write uses a user-substantiated cite, which a loop tick cannot supply. |

Only `scripts/lib/orders.py` writes `orders.json` with `dir_lock`. Only `scripts/lib/lessons.py` joins it with Muninn.
The writer makes `standing-orders.md` and `standing-orders-decayed.md` atomically, with a marker and mode 0444.
The model gets no instruction to edit these views.

## Overlap check (this record clears `blocked_on`)

- The only write is Muninn `know add`. There is no `know update` or `touch`.
  A tick or recurrence in Muninn would write a new cited record for each loop.
  This would need a user quote for each loop and add too many entries to the store. The design rejects it.

- Muninn `know retract`, `valid_until`, and `--supersedes` express "this lesson is no longer current".
  The ledger does not duplicate them. On each call, `lessons` reads the current Muninn status.
  It skips a retracted, expired, or superseded entry without a replacement and logs `lesson.query/excluded/lesson_not_current`.
  A newer current entry with the same `ord-<id>` tag replaces the text.

- If Muninn is down, `lessons` exits 3 with the cause and prints no ledger text.
  The explicit `memory.backend: off` setting gives ledger text and exit 0 in this decision. The ledger cannot act as a silent fallback for Muninn.

- A record without a user quote stays active with `muninn.state=degraded` and `no_user_cite`.
  The `orders.py cite <id> --quote` command adds the cite in this design.
  The importer marks legacy entries `legacy_uncited`. Diagnostics show `cited: false` until they have a cite.
  The dispatch, promotion, and view procedures do not use uncited claims.

## Consequences and limits

- K=5 is the code constant `orders_ledger.K`.

- The native command for loop end prepares standing instructions before it gets the loop lock.
  It checks the same prepared source again with the lock, records loop end, and releases the lock before tick and view writes.
  Run the command again to continue tick and view writes without a second age change.

  The view writer gives its input ledger hash. The caller checks it with the ledger lock before it records `orders_rendered`.
  Claude `mark-complete` uses the same checked path. The two native guards block if the bound teardown has pending work.

- The prepare step checks eligible owned loop data at `<repo-key dir>/<session>/progress.json`.
  It records the resolved directories, owning session, logical loop, revision, and source hash.
  Prospective eligibility permits prepare only. Recurrence and aging apply after the owned loop data records `complete` durably.

  An unsuccessful loop-end write does not age entries. Local apply is idempotent for each session and loop.
  The `orders_ticked` entry follows the ledger write. An error in apply or receipt after loop end keeps teardown pending.
  Retry the same tick.

- The default rejects a changed source.
  Before loop end, use `prepare --refresh-from-sha256 H` only if H equals the canonical current `evidence_sha256`.
  Immutable ownership must agree, the revision cannot go back, and the session and loop must have no applied tick or recurrence.
  The command keeps prepared records and does not apply lifecycle effects.

  If the replacement saves and its receipt write does not succeed, ordinary `prepare` with the same inputs repairs the receipt.
  Do not refresh completed inputs or inputs that the ledger applied before.

- D4 holds `teardown.jsonl.lock` after the ledger lock. It refuses linked artifact and sidecar paths.
  It checks physical LF framing, objects, and finite JSON numbers before it deduplicates against matching entries.
  It atomically publishes the previous bytes and a complete fsynced row.

  A write error before the end does not change the canonical records.
  An ambiguous result after publication permits an ordinary dedupe retry.
  The writer refuses corrupt records or records with no terminal newline without changing them.
  All concurrent writers must use this protocol to keep entries. D6 has open work to use it and has its own latest-step dedupe rule.

- Uncited entries are diagnostic only. The `lessons` command lists them with `cited: false`.
  The `query --format contract` and promotion `predicate` skip them. Candidate text comes from the Muninn claim.
  When Muninn is down, `render` exits 3 without ledger text.

- The `orders.json` file has a `head` anchor with count, last hash, and ticks hash. It identifies a removed tail or edited ticks.
  A missing ledger for a view that the writer made is an error. An agent with the same user ID can rewrite the file, chain, and head.

  The `retro_count` check uses different completed logical loops, correct owned loop data, and complete source-bound retros.
  Schema 2 uses all typed fields and the saved loop-data hash. Schema 3 uses the matching `retro_check`.
  If there is no validator, the result is a refusal and does not give a known zero count. The same user can rewrite these sources.

- The installed Muninn service on the measured machine uses a newer API with task bindings.
  The D4 adapter uses the earlier schema-2 CLI. Its currentness check reports degradation on that installation.
  This change supplies no ledger-text fallback or implicit store upgrade. No live activation check has accepted this change.

- A recurrence changes a decayed entry back to `active` and keeps its record. The predicate's "one decayed order" is a snapshot.

- The reader reconciles current tagged claims for degraded or pending local rows before it adds a record.
  If currentness lookup does not succeed, it keeps a previous K-id and reports degradation.
  Only explicit `record` can supersede claim text.

  The `cite` command reconciles the current claim without reauthoring earlier ledger text.
  For a new uncited entry, it checks the first cite.
  Different claims that are current at the same time with the same tag give `lesson_not_current`.

  Tick reads current cited metadata without writing knowledge. It keeps saved provenance before stale prepared metadata during outages.
  A retry after tick can refresh metadata without lifecycle effects.
  Promotion joins current cited claims with active or agnostic lifecycle eligibility. It does not use cached pending or degraded status.

  The ledger lock covers lookup, reconciliation, bounded sync, and the direct atomic ledger write.
  It cannot guarantee one and only one network update. Sync does not hold the loop lock.

- The chain is a cooperating-agent safeguard. The same user can rewrite `orders.json` and calculate all hashes again.
  The row hash does not include `muninn`. The head anchors the tick set.
  Replaying a completed observation cannot reset counters or revive a tombstone. Only a new completed session and loop recurrence can do so.

- The writer refuses a lesson with more than 500 collapsed characters before it writes and does not truncate it.
  Explicit IDs must be canonical. IDs that the writer makes have a hash suffix for ambiguous text.
  The ID binds the problem and scope across the ledger and correct saved prepared inputs before record, cite, or apply.

  Historical prepared inputs constrain identity after loop data changes.
  They do not prove current eligibility, currentness, citation, or lifecycle effects.

- The known caller session passes through lesson query, predicate, and view reads to adapter degradation logs.
  Claude and Codex environment identifiers can supply it. Explicit `--session` wins.
  Source and private fixtures cannot prove that an installed session exports the setting.

- The `render` command skips entries that Muninn no longer holds as current.
  If Muninn is unreachable, it exits 3 and keeps the view unchanged. A view can show a retracted entry until the next write succeeds.

- The importer cannot import a historical hand-written `standing-orders-decayed.md`. This repo had no such file.

- Pre-D4 completed schema-3 loops have no D4 prepared data or tick and view receipt.
  The new guards keep them pending until an operator examines the saved graph, eval, proof, retro, and transcript records.
  For an eligible historical loop, read the full hash with `shasum -a 256 <repo-key dir>/<session>/progress.json`.
  Then run `python3 scripts/lib/orders_completion.py admit-legacy --dir <repo-key dir> --session <session> --loop <loop> --progress-sha256 <hash> --reason "<reviewed historical evidence>"`.

  The command writes a receipt for the session and loop after it checks the same file hash.
  The receipt also identifies the substantive graph source. It does not edit loop data, import a lesson, tick a loop, or age a standing instruction.
  Native retry and Stop can update `completed_marker` and the complete Stop count. These bookkeeping changes do not revoke admission.

  Admission fails if the graph source changes or if a D4 prepared record, observation, or ledger effect exists.
  The same-user receipt records an inspection. It cannot prove owner approval for a new lesson.
  New loops must use the full D4 loop-end lifecycle.

- Legacy import keeps titles, counters with decay, full source text, and first-seen provenance.
  It refuses entries with missing data, format errors, or collisions, and paths from a different source, without changing the initial file.
  It publishes an archive with the same bytes before it writes the ledger and keeps the initial file.
  Each imported row seals the source SHA-256.

  A full-cohort retry uses equal rows, one saved creation timestamp, and the same source hash.
  It skips the ledger write and uses only an archive with the same bytes.
  Archive publication and the ledger write are different operations. An unsuccessful or uncertain write keeps the archive for inspection.
  Fixture tests do not show a live migration.

Runbook: "Standing order stored without a cite, or a lesson missing from dispatch" in `docs/RUNBOOK.md`.
Measurement: `docs/typed-records-measurement.md`. Related decision: `docs/decisions/2026-10-05-memory-authoritative.md`.
