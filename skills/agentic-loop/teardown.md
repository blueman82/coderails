# Teardown write contract — `retro.json` and standing-orders

Detail-carrier for Phase 13's teardown. The main skill keeps the imperative (run the five steps in
order, before the `complete` declaration); this file is the field spec and the mechanics you
consult **while writing the retro**.

`loop_stall_guard` blocks a `complete` declaration when `retro.json` is absent, malformed, or
below `schema_version` 1 (the hook accepts `schema_version >= 1`, forward-compatible with the cost
fields added at 2) — so the retro must be written before the declaration. It separately blocks
when a sibling `proof.json` exists but any of its frozen proofs is unexecuted-in-transcript or
last-failed — so every proof cmd must be run, in the foreground, in the orchestrator's own
session, before the declaration too (Step 1 below).

**Graph dispatch boundary.** `S13-proof`, `S13-retro`, and `S13-complete` deliberately have no
entry in the Claude role map. The native graph CLI `plan` command reports
them as `unresolved:true`. The orchestrator performs these actions. Record
them in the phase and artifact record. Do not create worker-completed graph
nodes for them. A graph dispatch needs a resolved instruction source and
native worker evidence.

## Contents

- [The Phase 13 self-audit report](#the-phase-13-self-audit-report)
- [Step 1 — Run every `proof.json` cmd](#step-1--run-every-proofjson-cmd)
- [Step 2 — Assemble `retro.json`](#step-2--assemble-retrojson)
- [Cost-mining sub-step](#cost-mining-sub-step)
- [Pricing is computed once and frozen](#pricing-is-computed-once-and-frozen)
- [Step 3 — Update `standing-orders.md`](#step-3--update-standing-ordersmd)
- [Steps 4 and 5](#steps-4-and-5)

## The Phase 13 self-audit report

The orchestrator audits its own autonomy from the `progress.json` counters and reports raw,
unscored facts — no numeric pass/fail scorecard, no "target: approaching zero" framing. The human
is the only party positioned to judge "should I have been asked about that?"; hand them the raw
list rather than have the process pre-grade itself. A clean-looking scorecard is more dangerous
than an honest unscored list because it is more likely to be trusted uncritically.

**The two core facts:**

- **`LOOP-STOP` counts by category.** Report the `hard-stop`,
  `approval-gate`, `awaiting-input`, and `complete` counts in
  `progress.json.loop_stop_counts`. `loop_stall_guard` owns this field. It
  increments a count for each consumed stop, from a `stops[]` row or a
  legacy text declaration. `stops[]` records the model's intent; the count
  records what the hook consumed. Read the counts as stored. Do not
  calculate or edit them. Report them without a verdict. A high
  `awaiting-input` count can draw the human's attention.
- **Decisions absorbed.** Copy `progress.json.decisions_absorbed` verbatim
  in oldest-first order. Report what was decided and the phase or work unit.
  Include in-scope choices made without asking, such as Phase 2.5 design,
  Phase 2.6 disposition, Phase 2.8 model routing, Phase 5 disconfirm skips,
  and Phase 6 actions. Give no self-justification or automated score.
  Do not rebuild the list from conversation memory.

**Also report, unscored:**

- **Artifacts produced** — PRs merged, deploys done, each with the verifying check (Phase 12), not the agent's claim.
- **Loop cost.** Report the token and dated USD totals by model from
  `retro.json.cost`. Include "prices as of `<cost.prices_as_of>`, N days
  old". `loop_stall_guard` also prints `retro.cost` through
  `systemMessage` on each `complete` declaration. That output does not
  replace this report. The reporter is silent for an old retro without
  cost data and does not block if mining fails. The orchestrator still
  writes the field. `hooks/scripts/lib/model_prices.json` is maintained by
  hand. No pricing API updates it. After `ALS_PRICE_STALE_DAYS` (14) days,
  the reporter asks a human to check the rates. It checks age only; an old
  date does not prove the rates are wrong.
- **Disposition violations.** Compare each `clean-break` decision in
  `progress.json` with the merged code. Report any shipped shim or
  compatibility path. Phase 4b or the human can find it. Distinguish
  **"0 violations"** from **"no disposition record found"**. A missing
  record is an audit failure. Also list each `preserve-compat` unit whose
  `removal_ticket` remains open at loop end.
- **Loop eval result.** Run `post_evals.py grade-loop` to compute the final
  `evals.json.result`. Do not write it by hand. Report `GO`, `NO-GO`, or a
  justified level-0 exemption without a score. Include recorded
  `amendments` and their reasons. An amendment after a grader verdict needs
  a fresh `regraded_by` value; `grade-loop` rejects its absence. A status
  written by the orchestrator to reverse a verdict is an audit failure.
  For a loop with at least one work unit, a missing `evals.json` is also an
  audit failure. Do not report it as a passing result.

## Step 1 — Run every `proof.json` cmd

If a `proof.json` was frozen at Phase 2.7e, run every one of its `cmd`s VERBATIM as its own single
Bash command, in the FOREGROUND (never `run_in_background`), in THIS (the orchestrator's) own
session — before assembling the retro. Confirm each exits 0. A proof run inside a dispatched
worker's session never appears in the orchestrator's own transcript and cannot satisfy the
`loop_stall_guard` proof gate, whatever its actual outcome. If a proof still fails, fix the
underlying issue and re-run that proof's `cmd` (not a modified version of it) until it passes, or
the `complete` declaration below blocks, naming the offending proof id(s) and their verdict. No
`proof.json` beside `progress.json` means nothing to run here — skip straight to Step 2.

## Step 2 — Assemble `retro.json`

Written at `schema_version` 2, beside `progress.json`.

| Field | Notes |
|---|---|
| `session_id`, `created` | Identity and timestamp. |
| `loop_id` | Copied **verbatim** from `progress.json`. |
| `loop_ordinal` | = `completed_marker` after the native `mark-complete` helper stamps it (the live agentic-loop invocation count, not a running loop-number ordinal — see `loop-state.md`). |
| `envelope` | Verbatim from `progress.json`'s `authorising_prompt_raw`. |
| `loop_stop_counts` | Copied **verbatim** from `progress.json` — HOOK-OWNED, never recomputed. |
| `decisions_absorbed` | Copied **verbatim** from `progress.json`'s array, not reconstructed from conversation memory. |
| `disposition_record` | Distinguish "0 violations" from "no-record" (an audit failure, not a pass). |
| `evals` | `result` / `amendments` / unresolved P1s. |
| `artifacts` | PRs + the verifying check (Phase 12), not the agent's claim. |
| `hook_blocks` | Via `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/lib/discipline_common.py" "<session_id>"`. |
| `review_themes`, `raw_notes` | Free-form. |
| `models_used` | Top-level array of model ids observed this loop — lifted out of the cost-miner's output. |
| `cost` | The dated per-model token/USD breakdown. |

The schema has **no `verdict` field** — raw and unscored is structural, not an oversight: the
retro records what happened, it does not grade it.

## Cost-mining sub-step

Same step 1, after assembling the fields above. Run `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/lib/loop_cost.py" <session_id>`. It enumerates this loop's transcripts (the orchestrator's own
`~/.claude/projects/<slug>/<sid>.jsonl` plus every worker transcript under
`<proj>/<sid>/subagents/`, recursively), dedupes by `message.id` so a transcript read twice isn't
double-counted, sums per-model token usage, prices it from a dated price table, and returns a
single object carrying `prices_as_of`, `per_model`, `total_tokens`, `total_usd_estimate`, and
`models_used` all as siblings.

**Fold-in is a split, not a copy.** Write the miner's returned object as `retro.cost` (its own
nested `schema_version` 1, independent of the retro's), then lift its `models_used` array OUT to
`retro.models_used` (top-level) — `models_used` lives at retro top-level only, never duplicated
inside `cost`. This split is what bumps the retro's own `schema_version` to 2; the
`cost`/`models_used` fields don't exist under `schema_version` 1.

**Fail-open.** The miner never blocks teardown — on any environmental error (missing/invalid
price file) it returns `{}`, so both `retro.cost` and `retro.models_used` end up empty and a
`complete` declaration proceeds exactly as it would with populated values. `loop_stall_guard`
checks the retro's presence and `schema_version`, never the cost field's correctness, so a miner
failure cannot stall a loop. There are two CALLER-error paths — invoking the miner with no session
id, or with a session id that resolves to no transcript anywhere under the projects dir — each
returning a self-describing `{"error":...,"hint":...}` object on stdout instead of `{}` (see the
lib's own header comment). Both can happen even when this sub-step believes it has `<session_id>`
in hand — a stale or wrong id is easier to pass than no id at all. Read the miner's output and, if
`.error` is present, record the error text in the retro rather than treating it as a normal empty
cost.

## Pricing is computed once and frozen

The miner prices `cost.per_model[*].usd_estimate` and `cost.total_usd_estimate` a single time at
teardown, stamped with `cost.prices_as_of` and `cost.price_source`. Nothing downstream re-prices:
the dashboard MUST sum the stored `usd_estimate`/`total_usd_estimate` values as written and MUST
NEVER re-derive them from token counts against a live price table. If a second pricing path is
ever tempting (e.g. a dashboard-side "current price" toggle), that is out of contract — the frozen
number at teardown is the number.

## Step 3 — Update `standing-orders.md`

At the repo-key dir. Match this loop's retro failure modes against existing entries:

- A **match** resets that entry's `loops_since_recurrence` to 0, updates `last_recurred`, and appends evidence.
- A genuinely **new** failure mode appends a new entry (fields: `id`, `created`, `failure_mode`, `lesson`, `evidence`, `last_recurred`, `loops_since_recurrence`).
- **Increment** `loops_since_recurrence` on every non-matched surviving entry.
- When `loops_since_recurrence` reaches **K=5**, move the entry to
  `standing-orders-decayed.md`. K is fixed here; it is not config. Keep the
  entry as a tombstone. Do not delete it. The graduation check looks for
  one clean decay in this file.

This step is additive-or-recurrence-only: no metric-based removal anywhere.

**Typed lessons (optional, degrades to the manual text above).** First run
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lib/memory_adapter.py" probe`. Exit 0 means a Part A `muninn` is installed: emit
each new or recurred lesson as a record with
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lib/memory_adapter.py" add --type lesson --scope loop --loop <session_id> --run <session_id> --claim "<lesson>" --cite <muninn ref> --quote "<verbatim quote>"`
(an uncited write is refused with reason `uncited_write`), then regenerate the view with
`... memory_adapter.py render --standing-orders --loop <session_id> --write <repo-key dir>/standing-orders-generated.md`
(it only overwrites a file whose first line is the generator marker, never
the hand-written `standing-orders.md`). A `Degraded` result makes the CLI
exit 3 and print `{"degraded": "<reason_code>"}`. Use that JSON reason and
exit code to choose the manual edits above. Some failure paths attempt to
append a trace row. Trace writes can fail open, and `probe` degradation
does not attempt one. Trace counters can therefore be partial. Runbook:
`docs/RUNBOOK.md`, "Memory silently using Markdown".

## Steps 4 and 5

4. **Write feedback-type auto-memories** for lessons that generalise beyond this loop.
5. **Only then** run
   `python3 "${CLAUDE_PLUGIN_ROOT}/skills/agentic-loop/scripts/graph.py" verify-completion <state> --session <session_id>`.
   This checks the current graph and identity-bound artifacts. Then run
   `loop_state_common.py mark-complete <cwd> <session_id>` to
   set `progress.json` `status: "complete"` and stamp `completed_marker` together — e.g.
   `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/lib/loop_state_common.py" mark-complete "$PWD" "<session_id>"`.
   Never write `status: "complete"` via a bare atomic update — that leaves
   `completed_marker` unstamped at its prior value (permanently 0 for a loop's first completion),
   which false-positives `loop_state_guard`'s `stale_complete_rearmed` block on every later turn of
   the same session. Then run `graph.py stop <state> --session <session_id> --category complete --reason-code work_complete --reason "<reason>"` and declare `LOOP-STOP: complete`. First apply
   `superpowers:verification-before-completion` to the orchestrator's own completion claim
   (SKILL.md's Phase 13 links the `finishing-out.md` detail). The `loop_stall_guard` proof gate
   blocks the declaration itself if Step 1 was skipped or left a proof unexecuted/failed — it does
   not need a separate manual check here.
