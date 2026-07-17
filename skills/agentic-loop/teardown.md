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

- **`LOOP-STOP` category counts, broken down by type** — the per-category counts of this loop's `LOOP-STOP` declarations (`progress.json` `loop_stop_counts`: `hard-stop`, `approval-gate`, `awaiting-input`, `complete`). HOOK-OWNED — the `loop_stall_guard` hook increments it on every valid declaration; read it as-is, do not compute or edit it yourself. Report the raw breakdown with no verdict attached. A high `awaiting-input` count is worth the human's attention, but this section states the count, not a judgement on it.
- **Decisions absorbed** — a flat, unscored list of in-scope decisions the loop made autonomously without asking (e.g. a Phase 2.5 design-fork auto-adopted, a Phase 2.6 disposition defaulted to clean-break, a Phase 2.8 routing assignment set, a Phase 5 disconfirm-skip, a Phase 6 in-scope action taken without a check-in). No self-justification text per entry, no automated "this looks calibrated" stamp — just what was decided and where (phase/work-unit). COPIED VERBATIM from `progress.json`'s `decisions_absorbed` array, chronological (oldest first) — never reconstructed from conversation memory, which is exactly the kind of after-the-fact self-report this phase exists to avoid.

**Also report, unscored:**

- **Artifacts produced** — PRs merged, deploys done, each with the verifying check (Phase 12), not the agent's claim.
- **Loop cost** — the per-model token + dated-USD breakdown mined into `retro.json`'s `cost` field, printed to the human WITH a price-staleness age: "prices as of `<cost.prices_as_of>`, N days old". This is a human-facing report deliverable, not just a stored artifact — a `complete` loop must print it, not merely write it to disk.
- **Disposition violations** — work-units where `clean-break` was recorded in `progress.json` but a shim/compat path shipped anyway (caught at the Phase 4b gate, or by the human afterward). Audit as a diff between the `progress.json` disposition record and the merged artifact. Critically, distinguish **"0 violations"** from **"no disposition record found"**: the latter is an **audit failure** — the record was not maintained — not a pass, otherwise the report reads "clean" when the record was simply absent. Separately, surface any `preserve-compat` unit whose `removal_ticket` is still **open at loop end** as a compat-debt drift signal, so deferred removals cannot silently rot.
- **Loop-scope eval result** — graded via `post_evals.sh grade-loop` (never hand-written into `evals.json`), the loop's final `evals.json` `result` (`GO`/`NO-GO`/a tier-0-exemption-with-justification), reported unscored, plus any `amendments` entries (post-freeze eval edits with recorded reasons). An amendment made after a grader verdict must carry its fresh re-grade (`regraded_by` recorded; `grade-loop` refuses otherwise): a verdict flipped by an orchestrator-written status is an audit failure, not a pass. **"No `evals.json` record found" for a ≥3-work-unit loop is an audit failure, not a pass** — distinguish it from a genuine `GO` the same way "0 disposition violations" is distinguished from "no disposition record found".

## Step 1 — Assemble `retro.json`

Written at `schema_version` 2, beside `progress.json`.

| Field | Notes |
|---|---|
| `session_id`, `created` | Identity and timestamp. |
| `loop_ordinal` | = `completed_marker` after the Phase 13 bump. |
| `envelope` | Verbatim from `progress.json`'s `authorising_prompt_raw`. |
| `loop_stop_counts` | Copied **verbatim** from `progress.json` — HOOK-OWNED, never recomputed. |
| `decisions_absorbed` | Copied **verbatim** from `progress.json`'s array, not reconstructed from conversation memory. |
| `disposition_record` | Distinguish "0 violations" from "no-record" (an audit failure, not a pass). |
| `evals` | `result` / `amendments` / unresolved P1s. |
| `artifacts` | PRs + the verifying check (Phase 12), not the agent's claim. |
| `hook_blocks` | Via `bash -c 'source "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/lib/discipline_common.sh" && dc_mine_hook_blocks "<session_id>"'`. |
| `review_themes`, `raw_notes` | Free-form. |
| `models_used` | Top-level array of model ids observed this loop — lifted out of the cost-miner's output. |
| `cost` | The dated per-model token/USD breakdown. |

The schema has **no `verdict` field** — raw and unscored is structural, not an oversight: the
retro records what happened, it does not grade it.

## Cost-mining sub-step

Same step 1, after assembling the fields above. Source `hooks/scripts/lib/loop_cost.sh` and run
`dc_mine_token_usage <session_id>`. It enumerates this loop's transcripts (the orchestrator's own
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

**Fail-open.** The miner never blocks teardown — on any error it returns `{}`, so both
`retro.cost` and `retro.models_used` end up empty and a `complete` declaration proceeds exactly as
it would with populated values. `loop_stall_guard` checks the retro's presence and
`schema_version`, never the cost field's correctness, so a miner failure cannot stall a loop.

## Pricing is computed once and frozen

The miner prices `cost.per_model[*].usd_estimate` and `cost.total_usd_estimate` a single time at
teardown, stamped with `cost.prices_as_of` and `cost.price_source`. Nothing downstream re-prices:
the dashboard MUST sum the stored `usd_estimate`/`total_usd_estimate` values as written and MUST
NEVER re-derive them from token counts against a live price table. If a second pricing path is
ever tempting (e.g. a dashboard-side "current price" toggle), that is out of contract — the frozen
number at teardown is the number.

## Step 2 — Update `standing-orders.md`

At the repo-key dir. Match this loop's retro failure modes against existing entries:

- A **match** resets that entry's `loops_since_recurrence` to 0, updates `last_recurred`, and appends evidence.
- A genuinely **new** failure mode appends a new entry (fields: `id`, `created`, `failure_mode`, `lesson`, `evidence`, `last_recurred`, `loops_since_recurrence`).
- **Increment** `loops_since_recurrence` on every non-matched surviving entry.
- When an entry's `loops_since_recurrence` reaches **K=5** (a constant stated here, not config), MOVE it to `standing-orders-decayed.md` — a tombstone, **never a delete**; the graduation predicate's "one clean decay" is checked against this file.

This step is additive-or-recurrence-only: no metric-based removal anywhere.

## Steps 3 and 4

3. **Write feedback-type auto-memories** for lessons that generalise beyond this loop.
4. **Only then** set `progress.json` `status: "complete"` and declare `LOOP-STOP: complete`. First apply `coderails:verification-before-completion` to the orchestrator's own completion claim (SKILL.md's Phase 13 links the `finishing-out.md` detail).
