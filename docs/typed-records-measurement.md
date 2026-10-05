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
