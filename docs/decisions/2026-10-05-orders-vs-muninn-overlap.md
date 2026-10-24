# Standing orders vs Muninn: where the claim lives and where the counters live

## Decision

Standing orders are typed records split across two stores, with no duplicated authority:

| Part | Lives in | Why |
| --- | --- | --- |
| The cited claim (the lesson text, its K-id, its cite and quote, its retraction/expiry/supersession status) | Muninn, as a `lesson` record tagged `order` and `ord-<id>`, repository-scoped | Muninn already owns cited, user-anchored, retractable knowledge; a second copy of that would be a second authority |
| Counters and decay (`loops_since_recurrence`, `last_recurred`, `status`, `decayed_at`, evidence list, `scope`) plus an append-only hash chain | `orders.json` at the repo-key dir (the grandparent of `progress.json`, as before), scripts-owned | Muninn has no update or touch primitive and every write needs a user-substantiated cite, which a per-loop tick cannot have |

`scripts/lib/orders.py` is the only writer of `orders.json` (under `dir_lock`); `scripts/lib/lessons.py` is the only reader
that joins it with Muninn. `standing-orders.md` and `standing-orders-decayed.md` are generated (marker-stamped, mode
0444, atomic write); nothing instructs a model to edit them.

## Overlap check (this record clears `blocked_on`)

- Muninn `know add` is the only write; there is no `know update`/`touch`. A tick or recurrence therefore cannot live in
  Muninn without writing a new cited record per loop. Rejected: it would need a user quote every loop and would flood the
  store.
- Muninn `know retract`, `valid_until` and `--supersedes` already express "this lesson is no longer current". The ledger
  does not shadow them: `lessons` re-reads Muninn's CURRENT status on every call and excludes (and traces
  `lesson.query/excluded/lesson_not_current`) any order whose entry is retracted, expired or superseded without a
  replacement. A newer current entry carrying the same `ord-<id>` tag replaces the text.
- With Muninn down, `lessons` exits 3 with the reason and prints no ledger text (`memory.backend: off` is the explicit
  switch and serves ledger text, exit 0). The ledger never silently stands in for Muninn.
- An order recorded without a user quote is kept active with `muninn.state=degraded`, reason `no_user_cite`, and
  `orders.py cite <id> --quote` attaches the cite later. Legacy entries are imported as `legacy_uncited` and served
  diagnostically with `cited: false` until cited. Dispatch, promotion and generated views exclude uncited claims.

## Consequences and limits

- K=5 is a code constant (`orders_ledger.K`), not config.
- The native completion command now prepares orders before it takes the progress lock. It validates the exact prepared
  source again under that lock, saves completion, then releases the lock before it ticks and renders. A repeat of the
  same completion command resumes the tick and render without a second age change. Claude `mark-complete` uses the
  same validated path. The Claude Stop guard and Codex completion verifier block when bound teardown is pending.
- Preparation validates genuine eligible progress at `<repo-key dir>/<session>/progress.json` and binds the resolved
  directories, owning session, separate logical loop, revision and source hash. Prospective eligibility permits
  preparation only. Actual recurrence/aging requires that owned progress be durably saved complete. Failed completion
  saves age nothing; local apply is idempotent per session+loop, and `orders_ticked` follows the ledger save. Failed
  postcompletion apply or receipt means pending teardown and retrying the same tick.
- A changed source is refused by default. Before completion, `prepare --refresh-from-sha256 H` may replace the current
  preparation only when H equals its canonical current `evidence_sha256`, immutable ownership matches, revision does
  not roll back, and that session+loop has no applied tick or recurrence. Staged records are preserved, with no effects.
  After a saved replacement whose receipt failed, ordinary unchanged `prepare` repairs the receipt. Never refresh
  completed or already applied inputs.
- D4 receipts use the persistent `teardown.jsonl.lock` after the orders lock, reject linked artifact/sidecar paths,
  and validate physical LF framing, objects and finite JSON numbers
  before any-matching dedupe, and atomically publish prior bytes plus a complete fsynced row. Partial failed writes
  leave canonical evidence untouched; an ambiguous post-publication error permits ordinary dedupe retry. Existing
  corrupt or newline-less evidence refuses untouched. Concurrent preservation requires every publisher to share this
  protocol; D6 adoption is pending and retains its separate latest-step dedupe semantics.
- Uncited orders are diagnostic only: `lessons` lists them `cited: false`, `query --format contract` and the promotion
  `predicate` exclude them, and candidate text is Muninn's claim. `render` exits 3 with Muninn down (no ledger text).
- `orders.json` carries a `head` anchor (count, last hash, ticks hash) so a dropped tail or edited ticks are named, and a
  missing ledger beside a generated view is an error; a same-user agent can still rewrite the file, chain and head.
  `retro_count` requires distinct completed logical loops, valid owned progress and complete source-bound retros.
  Schema2 uses complete typed fields and the saved progress hash. Schema3 delegates to the matching `retro_check`;
  absence of that validator is an explicit refusal, never a known zero count. The same user can rewrite these sources.
- The installed Muninn service on the current machine uses a newer request-bound API. The D4 adapter still requires
  the earlier schema-2 CLI. Its currentness check degrades explicitly on that installation. No ledger-text fallback
  or implicit store upgrade is part of this completion change; live activation remains unaccepted.
- A recurrence revives a decayed order (status back to `active`, record kept), so the predicate's "one decayed order"
  is a snapshot, not a history.
- Current tagged claims are reconciled even for degraded/pending local rows before another add. A failed currentness
  lookup retains a prior K-id and degrades explicitly. Only explicit `record` may supersede claim text; `cite`
  reconciles an existing current claim without reauthoring older ledger text, or validates a genuinely uncited first
  attachment. Different claims simultaneously current under one order tag refuse as `lesson_not_current`.
  Tick reads current cited metadata without writing knowledge, preserving saved provenance over stale preparations
  during an outage. An already-ticked retry may refresh that metadata without lifecycle effects. Promotion joins
  current cited claims to active/agnostic lifecycle eligibility, independent of cached pending/degraded state.
  The orders lock covers lookup, reconciliation, bounded
  sync and direct atomic ledger save. Network exactly-once behavior is not claimed; sync stays outside progress locks.
- The chain is a cooperating-agent safeguard: a same-user agent can rewrite `orders.json` and recompute every hash, and
  `muninn` sits outside the row hash; the head anchors the tick set. Replay of one completed observation cannot reset
  counters or revive a tombstone. Only a new completed session+loop recurrence can do so.
- A lesson over 500 collapsed characters is refused before storage, never silently truncated. Explicit ids must be
  canonical; generated ids retain a hash suffix for ambiguous text. An id binds failure mode and scope across the
  ledger and valid retained preparations before record/cite sync or application. Historical preparations constrain
  identity after progress advances, without asserting present eligibility/currentness/citations or lifecycle effects.
- Known caller sessions propagate through lesson query/predicate/render reads and underlying degraded adapter traces.
  Both Claude and Codex environment identifiers are supported; explicit `--session` wins. Installed environment
  presence is not established by source or private fixtures.
- `render` omits orders Muninn no longer holds as current; with Muninn unreachable it exits 3 and leaves the existing
  view untouched, so a view can lag a Muninn retraction until the next successful render.
- Import of the old hand-written `standing-orders-decayed.md` is not provided; it was never created in this repo.
- Legacy import preserves titles, counters including decay, full source text and first-seen provenance. Duplicate,
  incomplete, malformed or colliding entries and foreign paths are refused without moving the source. The original
  remains in a local backup. A retry after ledger save but failed source move resumes only when the entire parsed
  cohort equals every saved typed row, excluding only seal fields, at one common saved creation timestamp. It skips
  ledger save and moves intact source to an unused backup. This is parsed-row equivalence, not whole-source/preamble
  hash identity or atomicity across the ledger and source move; no live migration is claimed by fixture tests.

Runbook: `docs/RUNBOOK.md` "Standing order stored without a cite, or a lesson missing from dispatch". Measurement:
`docs/typed-records-measurement.md`. Related: `docs/decisions/2026-10-05-memory-authoritative.md`.
