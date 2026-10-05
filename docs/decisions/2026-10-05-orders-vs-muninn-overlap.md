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
  `orders.py cite <id> --quote` attaches the cite later. The five orders in the pre-existing hand-written file are
  imported the same way (`legacy_uncited`) and served flagged `cited: false` until cited.

## Consequences and limits

- K=5 is a code constant (`orders_ledger.K`), not config.
- The enforcing caller is advisory on both providers: the record/tick/render sequence is instructed in
  `skills/agentic-loop/teardown.md` and `packages/codex/skills/agentic-loop/SKILL.md`; no hook or completion command
  runs it, and none is added here (no second enforcement route beside the integrity gate).
- `tick --loop` is accepted only for a loop with `<repo-key dir>/<loop>/progress.json`; `record` with an existing id by
  any caller still resets that order's counter, and a recurrence does not update the stored lesson or Muninn claim.
- Uncited orders are diagnostic only: `lessons` lists them `cited: false`, `query --format contract` and the promotion
  `predicate` exclude them, and candidate text is Muninn's claim. `render` exits 3 with Muninn down (no ledger text).
- `orders.json` carries a `head` anchor (count, last hash, ticks hash) so a dropped tail or edited ticks are named, and a
  missing ledger beside a generated view is an error; a same-user agent can still rewrite the file, chain and head.
  `retro_count` counts distinct loop ids in parseable `retro.json` files; it is not authenticated.
- A recurrence revives a decayed order (status back to `active`, record kept), so the predicate's "one decayed order"
  is a snapshot, not a history.
- Muninn holds only the first cite of an order; recurrences add evidence to the ledger, not a new Muninn record.
- The chain is a cooperating-agent safeguard: a same-user agent can rewrite `orders.json` and recompute every hash, and
  `muninn` and `ticked_loops` sit outside the hash.
- A lesson longer than 500 characters is truncated (with an ellipsis) in Muninn, which caps claims at 500.
- `render` omits orders Muninn no longer holds as current; with Muninn unreachable it exits 3 and leaves the existing
  view untouched, so a view can lag a Muninn retraction until the next successful render.
- Import of the old hand-written `standing-orders-decayed.md` is not provided; it was never created in this repo.

Runbook: `docs/RUNBOOK.md` "Standing order stored without a cite, or a lesson missing from dispatch". Measurement:
`docs/typed-records-measurement.md`. Related: `docs/decisions/2026-10-05-memory-authoritative.md`.
