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

The orchestrator audits its own autonomy from the `progress.json` counters and reports raw,
unscored facts — no numeric pass/fail scorecard, no "target: approaching zero" framing. The human
is the only party positioned to judge "should I have been asked about that?"; hand them the raw
list rather than have the process pre-grade itself. A clean-looking scorecard is more dangerous
than an honest unscored list because it is more likely to be trusted uncritically.

**The two core facts:**

- **`LOOP-STOP` category counts, broken down by type** — the per-category counts of this loop's `LOOP-STOP` declarations (`progress.json` `loop_stop_counts`: `hard-stop`, `approval-gate`, `awaiting-input`, `complete`). HOOK-OWNED — the `loop_stall_guard` hook increments it on every consumed stop (a recorded `progress.json` `stops[]` row, else the legacy text declaration); `stops[]` is the model-written intent, `loop_stop_counts` is the hook-owned count of consumed stops. Read it as-is, do not compute or edit it yourself. Report the raw breakdown with no verdict attached. A high `awaiting-input` count is worth the human's attention, but this section states the count, not a judgement on it.
- **Decisions absorbed** — a flat, unscored list of in-scope decisions the loop made autonomously without asking (e.g. a Phase 2.5 design-fork auto-adopted, a Phase 2.6 disposition defaulted to clean-break, a Phase 2.8 routing assignment set, a Phase 5 disconfirm-skip, a Phase 6 in-scope action taken without a check-in). No self-justification text per entry, no automated "this looks calibrated" stamp — just what was decided and where (phase/work-unit). COPIED VERBATIM from `progress.json`'s `decisions_absorbed` array, chronological (oldest first) — never reconstructed from conversation memory, which is exactly the kind of after-the-fact self-report this phase exists to avoid.

**Also report, unscored:**

- **Artifacts produced** — PRs merged, deploys done, each with the verifying check (Phase 12), not the agent's claim.
- **Loop cost** — the per-model token + dated-USD breakdown mined into `retro.json`'s `cost` field, printed to the human WITH a price-staleness age: "prices as of `<cost.prices_as_of>`, N days old". This is a human-facing report deliverable, not just a stored artifact. `loop_stall_guard`'s cost reporter now prints it mechanically via `systemMessage` on every `complete` declaration, the same way `check_verify_loop.py` mechanically enforces the CLAUDE.md DNV rule — but the prose obligation below is still the floor, not something the hook replaces: the hook reports `retro.cost` verbatim (silent on a legacy pre-cost-miner retro, and never blocking on a miner failure), it does not relieve the orchestrator of assembling and writing that field correctly in the first place. The price table (`hooks/scripts/lib/model_prices.json`) is HAND-MAINTAINED — there is no pricing API, so nothing auto-updates it. Past `ALS_PRICE_STALE_DAYS` (14) days old, the reporter also nags a human to go check the rates; the nag verifies the DATE only, never the rates themselves, since staleness of a self-reported date can't prove the rates are wrong.
- **Disposition violations** — work-units where `clean-break` was recorded in `progress.json` but a shim/compat path shipped anyway (caught at the Phase 4b gate, or by the human afterward). Audit as a diff between the `progress.json` disposition record and the merged artifact. Critically, distinguish **"0 violations"** from **"no disposition record found"**: the latter is an **audit failure** — the record was not maintained — not a pass, otherwise the report reads "clean" when the record was simply absent. Separately, surface any `preserve-compat` unit whose `removal_ticket` is still **open at loop end** as a compat-debt drift signal, so deferred removals cannot silently rot.
- **Loop-scope eval result** — graded via `post_evals.py grade-loop` (never hand-written into `evals.json`), the loop's final `evals.json` `result` (`GO`/`NO-GO`/a verification_level-0-exemption-with-justification), reported unscored, plus any `amendments` entries (post-freeze eval edits with recorded reasons). An amendment made after a grader verdict must carry its fresh re-grade (`regraded_by` recorded; `grade-loop` refuses otherwise): a verdict flipped by an orchestrator-written status is an audit failure, not a pass. **"No `evals.json` record found" for a ≥1-work-unit loop is an audit failure, not a pass** — distinguish it from a genuine `GO` the same way "0 disposition violations" is distinguished from "no disposition record found".

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

## Step 3 — Update the standing orders (code, not prose)

Standing orders are typed records in `<repo-key dir>/orders.json` (the grandparent of the `progress.json` path), changed
only by `scripts/lib/orders.py`; `standing-orders.md` and `standing-orders-decayed.md` are generated, read-only views.
Never write those files by hand (`render` refuses an unmarked file with `handwritten_protected`). Run, in order, from the
orchestrator session (`O="python3 ${CLAUDE_PLUGIN_ROOT}/scripts/lib/orders.py --dir <repo-key dir> --session <session_id>"`).
Pass the separate logical `loop_id` copied from owned `progress.json`; it is not the session directory name.

1. For each failure mode in this loop's retro, `$O record --failure-mode "<mode>" --lesson "<imperative lesson>" --loop <loop_id> --quote "<verbatim words of the owner's own prompt, 12-300 chars>"`. Add `--scope agnostic` for a lesson that applies
   to any repo. Before completion this stages the observation and any cited sync; it changes no lifecycle counters.
   An id must name the same failure mode and scope. A claim over 500 collapsed characters is refused, never truncated.
2. After final progress updates, `$O prepare --loop <loop_id>` validates the owned eligible graph and work units,
   binds the source directory, session, logical loop, revision and progress hash, and records `orders_prepared`.
   This also runs when the retro has no failure mode. Prospective eligibility authorizes preparation only.
   A changed source is refused by default. For a legitimate incomplete-source retry, pass
   `$O prepare --loop <loop_id> --refresh-from-sha256 <CURRENT evidence_sha256>` using the canonical hash returned by
   the current preparation. It preserves staged records, refuses rollback/foreign/already-applied sources, and has
   no lifecycle effect. A saved replacement whose receipt failed needs ordinary unchanged `prepare` to repair it.
   Flush and reload pending source updates before final preparation. Never refresh after durable completion.
3. In Step 5, after native completion is durably saved, `$O tick --loop <loop_id>` applies the staged recurrences
   and ages every unmatched active order once. A new completed session+loop recurrence resets the counter and revives
   a tombstone; replay does neither. At **K=5** an order becomes `decayed`, **never deleted**. Then `$O render` regenerates
   both views; a decayed order appears only in `standing-orders-decayed.md`.

Preparation and apply read `<repo-key dir>/<session_id>/progress.json`, validate its ownership and source binding,
and refuse missing, foreign, malformed, incomplete or stale sources. A failed native completion save ages nothing.
`orders_ticked` is emitted only after the ledger save. A failed postcompletion ledger save or observation reports
`pending_teardown: true`, exit 3; retry the same bound tick. This caller remains **advisory** in this checkpoint:
automatic provider completion wiring is pending. The Codex equivalent is in `packages/codex/skills/agentic-loop/SKILL.md`.

The graduation predicate and the promotion selection are `$O predicate` and `lessons.py predicate`. This step is
additive-or-recurrence-only: no metric-based removal anywhere.

**Typed lessons (Muninn authoritative).** The cited claim of each order lives in Muninn as a `lesson` tagged `order` and
`ord-<id>`; the one orders lock covers currentness lookup, tagged-claim reconciliation, bounded sync and local save.
Current claims are reconciled even for degraded/pending local rows; a failed lookup retains a prior K-id and reports
degradation. The cite must anchor in a user prompt (`--quote`): with none, the staged or completed local row has
`muninn.state=degraded` and reason `no_user_cite`, exit 3, and
`$O cite <id> --quote "<owner's words>"` attaches it later. Exit 3 prints `{"muninn": {... "reason_code": ...}}`:
**report that reason code in the retro; never skip it silently and never write the lesson to Markdown instead.**
`memory.backend: off` (reason `memory_backend_off`, exit 0) is the only explicit opt-out. A first-time adoption of an old
hand-written file is `$O import-legacy` (the original is moved to `standing-orders.legacy.md`, not deleted). Runbook:
`docs/RUNBOOK.md`, "Standing order stored without a cite"; decision records:
`docs/decisions/2026-10-05-memory-authoritative.md`, `docs/decisions/2026-10-05-orders-vs-muninn-overlap.md`.

## Steps 4 and 5

4. **Write feedback-type auto-memories** for lessons that generalise beyond this loop.
5. **Only then** run `python3 "${CLAUDE_PLUGIN_ROOT}/skills/agentic-loop/scripts/graph.py" verify-completion <state> --session <session_id>` to validate the current native graph and identity-bound artifacts. Then run `loop_state_common.py mark-complete <cwd> <session_id>` to
   set `progress.json` `status: "complete"` and stamp `completed_marker` together — e.g.
   `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/lib/loop_state_common.py" mark-complete "$PWD" "<session_id>"`.
   Never write `status: "complete"` via a bare atomic update — that leaves
   `completed_marker` unstamped at its prior value (permanently 0 for a loop's first completion),
   which false-positives `loop_state_guard`'s `stale_complete_rearmed` block on every later turn of
   the same session. After a successful durable save, run `$O tick --loop <loop_id>` and `$O render` as described in
   Step 3; a pending teardown must be recovered before reporting it as finished. Then run
   `graph.py stop <state> --session <session_id> --category complete --reason-code work_complete --reason "<reason>"`
   and declare `LOOP-STOP: complete`. First apply
   `superpowers:verification-before-completion` to the orchestrator's own completion claim
   (SKILL.md's Phase 13 links the `finishing-out.md` detail). The `loop_stall_guard` proof gate
   blocks the declaration itself if Step 1 was skipped or left a proof unexecuted/failed — it does
   not need a separate manual check here.
