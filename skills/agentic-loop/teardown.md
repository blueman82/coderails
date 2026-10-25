# Teardown write contract — `retro.json` and standing-orders

This file gives the Phase 13 teardown steps and `retro.json` fields. Run all
five steps in order before you declare `complete`.

`loop_stall_guard` blocks `complete` if `retro.json` is absent, malformed, or
has `schema_version` below 1. Version 2 adds cost fields. The guard also
blocks if a sibling `proof.json` has a proof that did not run in this session
or whose last run failed. Run each proof command in the foreground before you
declare `complete`.

Before you assemble the retro, run `graph.py flush-decisions <progress.json>
--session <id>` through the current provider's graph CLI. On exit 3, record
the Muninn degradation or uncertain sync. Preserve local decision rows.
Check `decision_sync_unknown` against the store before a manual retry. On exit
2, stop and inspect the chain. Copy the resulting `decisions_absorbed` rows
verbatim into the retro.

**Graph dispatch boundary.** `S13-proof`, `S13-retro`, and `S13-complete` deliberately have no
entry in the Claude role map, so the native graph CLI `plan` command reports them as `unresolved:true`. These are orchestrator actions. Keep them in the phase/artifact record; do not create fake worker-completed graph nodes for them. An actual graph dispatch requires a resolved instruction source and native worker evidence.

## Contents

- [The Phase 13 self-audit report](#the-phase-13-self-audit-report)
- [Step 1 — Run every `proof.json` cmd](#step-1--run-every-proofjson-cmd)
- [Step 2 — Assemble `retro.json`](#step-2--assemble-retrojson)
- [Cost-mining sub-step](#cost-mining-sub-step)
- [Pricing is computed once and frozen](#pricing-is-computed-once-and-frozen)
- [Step 3 — Update the standing orders (code, not prose)](#step-3--update-the-standing-orders-code-not-prose)
- [Steps 4 and 5](#steps-4-and-5)

## The Phase 13 self-audit report

Read the autonomy counters in `progress.json`. Report the facts without a
score or target. The user judges whether the loop should have asked for
approval. Do not pre-grade that decision.

**The two core facts:**

- **`LOOP-STOP` category counts, broken down by type** — the per-category counts of this loop's recorded stops (`progress.json` `loop_stop_counts`: `hard-stop`, `approval-gate`, `awaiting-input`, `complete`). HOOK-OWNED — the `loop_stall_guard` hook increments it when it consumes a valid `progress.json` `stops[]` row. Read it as-is; do not compute or edit it. Report the raw breakdown with no verdict attached.
- **Decisions absorbed** — a flat, unscored list of in-scope decisions the loop made autonomously without asking (e.g. a Phase 2.5 design-fork auto-adopted, a Phase 2.6 disposition defaulted to clean-break, a Phase 2.8 routing assignment set, a Phase 5 disconfirm-skip, a Phase 6 in-scope action taken without a check-in). No self-justification text per entry, no automated "this looks calibrated" stamp — just what was decided and where (phase/work-unit). COPIED VERBATIM from `progress.json`'s `decisions_absorbed` array, chronological (oldest first) — never reconstructed from conversation memory, which is exactly the kind of after-the-fact self-report this phase exists to avoid.

**Also report, unscored:**

- **Artifacts produced** — PRs merged, deploys done, each with the verifying check (Phase 12), not the agent's claim.
- **Loop cost.** Report tokens and dated USD estimates by model from
  `retro.cost`. Tell the user: "prices as of `<cost.prices_as_of>`, N days
  old". `loop_stall_guard` also prints this field on `complete`, but it does
  not create or check the field. A miner failure does not block completion.
  The price table in `hooks/scripts/lib/model_prices.json` needs manual
  updates. After `ALS_PRICE_STALE_DAYS` (14), the hook asks the user to
  check its rates. It checks the date, not the price values.
- **Disposition violations.** Compare each `clean-break` decision in
  `progress.json` with the merged code. Report any old path that still runs.
  Say "0 violations" only if a disposition record exists and the check found
  none. If no record exists, report an audit failure. Also report each
  `preserve-compat` unit with an open `removal_ticket` at loop end.
- **Loop eval result.** Run `post_evals.py grade-loop`. Report the
  `evals.json` result (`GO`, `NO-GO`, or a justified verification_level-0
  exemption) and all amendments without a score. An amendment after a
  verdict needs a new grade with `regraded_by`; `grade-loop` refuses it
  otherwise. A missing `evals.json` in a loop with at least one work unit
  is an audit failure. Do not write the result by hand.

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

After you assemble the fields above, run `python3
"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/lib/loop_cost.py" <session_id>`. It reads
the orchestrator transcript at `~/.claude/projects/<slug>/<sid>.jsonl` and
worker transcripts under `<proj>/<sid>/subagents/`. It removes duplicate
`message.id` entries, sums tokens by model, and uses a dated price table.
The result has `prices_as_of`, `per_model`, `total_tokens`,
`total_usd_estimate`, and `models_used` fields.

**Fold-in is a split, not a copy.** Write the miner's returned object as `retro.cost` (its own
nested `schema_version` 1, independent of the retro's), then lift its `models_used` array OUT to
`retro.models_used` (top-level) — `models_used` lives at retro top-level only, never duplicated
inside `cost`. This split is what bumps the retro's own `schema_version` to 2; the
`cost`/`models_used` fields don't exist under `schema_version` 1.

**A cost-miner failure does not block teardown.** An environmental error, such
as a missing or invalid price file, returns `{}`. Leave `retro.cost` and
`retro.models_used` empty. `loop_stall_guard` checks the retro's presence and
schema version, not its cost fields.

A missing session ID or an ID with no transcript returns an object with
`error` and `hint` fields. Read the output. If `.error` is present, record the
error text in the retro. Do not treat it as a normal empty cost.

## Pricing is computed once and frozen

The miner prices `cost.per_model[*].usd_estimate` and `cost.total_usd_estimate` a single time at
teardown, stamped with `cost.prices_as_of` and `cost.price_source`. Nothing downstream re-prices:
the dashboard MUST sum the stored `usd_estimate`/`total_usd_estimate` values as written and MUST
NEVER re-derive them from token counts against a live price table. If a second pricing path is
ever tempting (e.g. a dashboard-side "current price" toggle), that is out of contract — the frozen
number at teardown is the number.

## Step 3 — Update the standing orders (code, not prose)

Standing orders are typed records in `<repo-key dir>/orders.json` (the grandparent of the `progress.json` path), changed
only by `scripts/lib/orders.py`; `standing-orders.md` and `standing-orders-decayed.md` are generated, read-only views.
Never write those files by hand (`render` refuses an unmarked file with `handwritten_protected`).
For each manual subcommand, use the full prefix:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lib/orders.py" --dir "<repo-key dir>" --session "<session_id>" <subcommand>
```

Run the steps below in order from the orchestrator session.
Pass the separate logical `loop_id` copied from owned `progress.json`; it is not the session directory name.

1. For each failure mode in this loop's retro, run `record --failure-mode "<mode>" --lesson "<imperative lesson>" --loop <loop_id> --quote "<verbatim words of the owner's own prompt, 12-300 chars>"` with that prefix. Add `--scope agnostic` for a lesson that applies
   to any repo. Before completion this stages the observation and any cited sync; it changes no lifecycle counters.
   An id must name the same failure mode and scope. A claim over 500 collapsed characters is refused, never truncated.
2. After final progress updates, the native completion command runs `orders.py prepare --loop <loop_id>`. It validates the
   owned eligible graph and work units, binds the source directory, session, logical loop, revision and progress hash,
   and records `orders_prepared`. This also runs when the retro has no failure mode. Prospective eligibility authorizes
   preparation only.
   A changed source is refused by default. For a legitimate incomplete-source retry, pass
   `orders.py prepare --loop <loop_id> --refresh-from-sha256 <CURRENT evidence_sha256>` using the canonical hash returned by
   the current preparation. It preserves staged records, refuses rollback/foreign/already-applied sources, and has
   no lifecycle effect. A saved replacement whose receipt failed needs ordinary unchanged `prepare` to repair it.
   Flush and reload pending source updates before final preparation. Never refresh after durable completion.
3. After native completion is durably saved, that command runs `orders.py tick --loop <loop_id>` and `orders.py render --loop
   <loop_id>`. It applies staged recurrences and ages every unmatched active order once. A new completed session+loop
   recurrence resets the counter and revives a tombstone; replay does neither. At **K=5** an order becomes `decayed`,
   **never deleted**. A decayed order appears only in `standing-orders-decayed.md`.

Preparation and apply read `<repo-key dir>/<session_id>/progress.json`, validate its ownership and source binding,
and refuse missing, foreign, malformed, incomplete or stale sources. A failed native completion save ages nothing.
`orders_ticked` is emitted only after the ledger save. A failed postcompletion ledger save or observation reports
`pending_teardown: true`. Repeat the native completion command to resume the same bound tick and render. The Claude
Stop guard blocks a finished loop until those bound receipts and generated views are current. The Codex equivalent is
in `packages/codex/skills/agentic-loop/SKILL.md`.
An old complete loop without D4 receipts needs explicit reviewed legacy admission; see the orders decision and
runbook. Admission checks the exact file hash, then permits completion bookkeeping while binding the graph source.
It does not age orders. New loops cannot use it.

The graduation predicate and the promotion selection are `orders.py predicate` and `lessons.py predicate`. This step is
additive-or-recurrence-only: no metric-based removal anywhere.

**Typed lessons (Muninn authoritative).** The cited claim of each order lives in Muninn as a `lesson` tagged `order` and
`ord-<id>`; the one orders lock covers currentness lookup, tagged-claim reconciliation, bounded sync and local save.
Current claims are reconciled even for degraded/pending local rows; a failed lookup retains a prior K-id and reports
degradation. The cite must anchor in a user prompt (`--quote`): with none, the staged or completed local row has
`muninn.state=degraded` and reason `no_user_cite`, exit 3, and
`orders.py cite <id> --quote "<owner's words>"` attaches it later. Exit 3 prints `{"muninn": {... "reason_code": ...}}`:
**report that reason code in the retro; never skip it silently and never write the lesson to Markdown instead.**
`memory.backend: off` (reason `memory_backend_off`, exit 0) is the only explicit opt-out. A first-time adoption of an old
hand-written file is `orders.py import-legacy` (it archives a byte copy and retains the original). Verify the archive and
ledger, then retire the hand-written source before generating `standing-orders.md`. Runbook:
`docs/RUNBOOK.md`, "Standing order stored without a cite"; decision records:
`docs/decisions/2026-10-05-memory-authoritative.md`, `docs/decisions/2026-10-05-orders-vs-muninn-overlap.md`.

## Steps 4 and 5

4. **Write feedback-type auto-memories** for lessons that generalise beyond this loop.
5. **Only then** run `loop_state_common.py mark-complete <cwd> <session_id>` to validate native completion, prepare and
   recheck orders, save progress, apply the tick and render, and stamp `completed_marker` — e.g.
   `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/lib/loop_state_common.py" mark-complete "$PWD" "<session_id>"`.
   Never write `status: "complete"` via a bare atomic update — that leaves
   `completed_marker` unstamped at its prior value (permanently 0 for a loop's first completion),
   which false-positives `loop_state_guard`'s `stale_complete_rearmed` block on every later turn of
   the same session. If completion reports pending teardown, repeat `mark-complete` to resume it. Then run
   `graph.py verify-completion <state> --session <session_id>` to check the graph and bound orders evidence. Then run
   `graph.py stop <state> --session <session_id> --category complete --reason-code work_complete --reason "<reason>"`
   and render `LOOP-STOP: complete` for the human. The hook reads the recorded row, not this text. First apply
   `superpowers:verification-before-completion` to the orchestrator's own completion claim
   (SKILL.md's Phase 13 links the `finishing-out.md` detail). The `loop_stall_guard` proof gate
   blocks the declaration itself if Step 1 was skipped or left a proof unexecuted/failed — it does
   not need a separate manual check here.
