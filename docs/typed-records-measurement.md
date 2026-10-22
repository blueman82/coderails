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
| Graduation predicate | model counted files and read Markdown | >=10 distinct completed source-bound retros, typed recurrence and decay | `orders_test.py`, `lessons_test.py`, `orders_lifecycle_test.py` |
| Lessons given to a dispatch | model copied from Markdown | `lessons.py query --format contract`: sorted, verbatim, stable sha256 | `lessons_test.py` |
| Unavailable currentness | n/a | explicit exit 3, prior K-id retained, no ledger-text fallback | `orders_test.py`, `orders_repair_test.py`, `lessons_test.py` |
| Lifecycle effect before durable completion | prose ticked before completion | none: record/prepare stage inputs, tick applies only saved owned completion | `orders_lifecycle_test.py` |
| Changed preparation recovery | no separately bound preparation | explicit current-hash compare-and-swap; staged records preserved without effects | `orders_prepare_test.py` |
| Citation chronology | cached ledger/preparation could restore older claims or ids | cite reconciles without authoring; tick reads fresh metadata, preserving later known ids during outages | `orders_current_test.py` |
| Legacy move interruption | saved imported rows made ordinary retry collide | full parsed-cohort equality resumes only the source move, without another ledger save | `orders_legacy_test.py` |
| Completed lesson replacement recovery | existing evidence could acknowledge an unsaved same-loop edit | captured predecessor and sealed authored-source token recover only the accepted row | `orders_retry_view_test.py` |

Counters: `order.record|prepare|tick|render|import|cite` and `lesson.query|predicate` trace rows are counted by
`scripts/lib/memory_counters.py` (`by_command`, `by_reason_code`), which `scripts/measure_graph_alignment.py` already embeds
under the `memory` key; no edit to that script is needed. Runbook entry: `docs/RUNBOOK.md` "Standing order stored without
a cite, or a lesson missing from dispatch". Decision: `docs/decisions/2026-10-05-orders-vs-muninn-overlap.md`.

Limits: the instructed prepare/native-complete/apply caller is advisory at this checkpoint; automatic provider wiring
remains pending. `orders_ticked` is a post-save observation, and a failed apply/receipt after completion means pending
teardown. The one same-user lock covers currentness, reconciliation, bounded sync and atomic ledger save, with no
exactly-once network claim. New completed recurrences revive tombstones; replay cannot reset counters. Current live,
verified owner-cited lesson text is legitimate typed memory; transcript advisory observations remain metadata only.
Uncited claims are diagnostic and excluded from dispatch, promotion and views. Claims over 500 collapsed characters
are refused, never truncated. Schema3 history needs the matching `retro_check` validator; absence is unknown/refused.
The chain and source hashes are cooperating-agent safeguards. Legacy fixture imports preserve all five entries,
counters, full text and first-seen provenance; a live hand-written-file migration was not verified.
Legacy retry equivalence covers every parsed row except seal fields, not a whole-source/preamble hash or own-attempt
identity. Current reads exclude nonfinite expiries; scope labels remain opaque as supplied by Muninn's cwd-filtered
repository list. Receipt parsing requires physical LF records and finite JSON numbers; Unicode inside a legitimate
JSON string remains supported. Linked preparation/receipt/sidecar paths refuse before content read/open/create.

For an explicit replacement with existing session/loop evidence, prepared `replaces_source` captures the canonical
`lesson_source` (including an explicit null when none existed). The canonical token hashes owned binding and authored
row fields, excluding mutable Muninn observations, and is saved with its lesson under the existing chain. Tick applies
only a missing observation or a replacement whose predecessor still matches; equal published source is already applied.
A different later authored source is preserved, with exit 3/pending unless exact validated success evidence already
acknowledges this preparation. An unbound pure `record` update clears the old token. Older absent predecessor data is
not retroactively invented. Captured null cannot authorize a delayed replacement without its own published source or
exact validated acknowledgement; even an unchanged null-source predecessor cannot prove authorship. Direct completed
explicit record remains available. Publication followed by a lost receipt and then another authored replacement can remain
honestly pending: the latest source and predecessor do not establish that historical application.

## Proof results (`proof_results.jsonl`)

| Measure | Before | After | How measured |
| --- | ---: | ---: | --- |
| Who executes a frozen proof cmd | the model, as its own Bash call; the gate string-matched the transcript | the controller: `proof.py run` via `/bin/bash -c`, verbatim | `scripts/tests/proof_run_test.py` (verbatim nested-quote cmd gives exit 3, the same `cmd_sha256`) |
| Evidence the gate reads | a transcript tool pair (Claude) or an exec result frame plus `status == pass` (Codex) | hash-chained run rows on both providers | `proof_run_test.py` (a perfectly matching transcript no longer satisfies a proof) |
| `expect` | prose, never evaluated | `{exit_code, stdout_contains, stdout_not_contains}`, evaluated | `proof_run_test.py` expect tests; skipping the evaluation fails them |
| Tamper detection | none | edited proof.json, wrong cmd hash and deleted row each block (`proof_stale_cmd`, `proof_chain_broken`) | `proof_run_test.py` mutation controls |
| Codex loop with no executable surface | could not complete | completes with `none: <reason>` or the typed disposition | `packages/tests/test_codex_completion.py` |

Counters: `proof.freeze|run|gate` trace rows are counted by `scripts/lib/memory_counters.py` (prefix `proof.`), embedded under
the `memory` key of `scripts/measure_graph_alignment.py`; no edit to that script. Runbook entry: `docs/RUNBOOK.md`
"Proof gate blocked a `complete` declaration".

Limits (written, not hidden): a same-user agent can forge rows and recompute the chain (cooperating-agent safeguard);
the gate checks the frozen command ran and matched `expect`, not that it is a good proof; the freeze hashes the canonical
JSON, so a re-freeze after an edit is the sanctioned (and traced) way to change a proof; `graph.py complete --transcript`
is accepted and ignored; schema 1 proofs are refused at freeze (they ignore structured `expect`); the destructive
classifier is literal-pattern, not a sandbox; run rows are not bound to HEAD; the gate has no off-switch by design.
