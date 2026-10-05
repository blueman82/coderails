# Typed-records measurement (lane D, started by the record-decision unit)

Before/after numbers for turning hand-written loop records into typed, hash-chained, Muninn-synced records. One section
per unit; this file starts with decisions. Counts come from code and trace rows, not from recollection.

## Decisions (`decisions_absorbed`)

| Measure | Before | After | How measured |
| --- | ---: | ---: | --- |
| Writers of `decisions_absorbed` in code | 0 (prose told the model to hand-append) | 1 (`scripts/lib/decision_record.py`) | `grep -rln "decisions_absorbed" scripts hooks packages` minus tests, Markdown and the TypeScript dashboard reader lists only `decision_record.py` and its mirror |
| Rows carrying a hash chain | 0 | every row appended by `record` | `decision_record.verify_chain(rows)` returns `[]` |
| Rows synced to Muninn | 0 | `muninn.state == "written"` rows | `decisions_absorbed[*].muninn` |
| Silent loss when Muninn is down | n/a | 0: local row kept, `decision.sync/degraded/<code>`, exit 3 | `decision_record_test.py` |

Counters: `decision.record` and `decision.sync` trace rows are counted by `scripts/lib/memory_counters.py`
(`by_command`, `by_reason_code`), which `scripts/measure_graph_alignment.py` already embeds under the `memory` key; no
edit to that script is needed. Runbook entry: `docs/RUNBOOK.md` "Decision recorded locally but Muninn sync degraded".

## Limits (written, not hidden)

- The chain is a cooperating-agent safeguard: a same-user agent can rewrite the file and recompute every hash. Deleting
  the last row is undetectable by the chain alone.
- Muninn refuses a short approval citation and an agent cannot cite itself, so the cite is a quote of the owner's
  `authorising_prompt_raw` (or a caller-supplied substantive `cite_quote`). An authorising prompt such as "yes" degrades
  (`cite_too_short`) and stays visible until `flush_pending` is given a substantive user quote.
- Only the orchestrator session can write (subagent threads are not citable by Muninn).
- Decisions are stored with `confidence=inferred`, so Muninn treats them as pull-only, not injected.

## Standing orders and lessons (`orders.json`)

| Measure | Before | After | How measured |
| --- | ---: | ---: | --- |
| Writers of standing-order counters in code | 0 (prose told the model to hand-edit Markdown) | 1 (`scripts/lib/orders.py` over `orders_ledger.py`) | `grep -rln "loops_since_recurrence" scripts hooks packages` minus tests and Markdown lists only `orders_ledger.py`, `orders.py`, `lessons.py` and their Codex mirrors |
| Orders carrying a hash chain | 0 | every order written by `orders.py` | `orders_ledger.verify(ledger)` returns `[]`; a hand edit is refused as `order_chain_broken` naming the order |
| Decay rule | prose ("K=5") | `orders_ledger.K = 5`, tested at 4 ticks (active) and 5 (decayed, never deleted) | `scripts/tests/orders_test.py` |
| Graduation predicate | model counted files and read Markdown | `lessons.py predicate` / `orders.py predicate` JSON | `orders_test.py`, `lessons_test.py` |
| Lessons given to a dispatch | model copied from Markdown | `lessons.py query --format contract`: sorted, verbatim, stable sha256 | `lessons_test.py` |
| Silent loss when Muninn is down | n/a | 0: ledger kept (`muninn.state=degraded`), exit 3, reason printed; `lessons` prints no ledger text | `orders_test.py` |

Counters: `order.record|tick|render|import|cite` and `lesson.query|predicate` trace rows are counted by
`scripts/lib/memory_counters.py` (`by_command`, `by_reason_code`), which `scripts/measure_graph_alignment.py` already embeds
under the `memory` key; no edit to that script is needed. Runbook entry: `docs/RUNBOOK.md` "Standing order stored without
a cite, or a lesson missing from dispatch". Decision: `docs/decisions/2026-10-05-orders-vs-muninn-overlap.md`.

Limits (written, not hidden): the chain is a cooperating-agent safeguard; Muninn holds only an order's first cite;
a recurrence revives a decayed order; claims over 500 characters are truncated in Muninn; orders without a user quote stay
`cited: false` until `orders.py cite`. The hand-written file was imported once (5 entries, all `legacy_uncited`).
