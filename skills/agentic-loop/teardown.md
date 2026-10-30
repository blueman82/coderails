# Teardown write contract — `retro.json` and standing-orders

Detail-carrier for Phase 13's teardown. Prepare and assemble before the durable completion save;
apply standing orders afterward. Use the source-writing commands below.

`loop_stall_guard` blocks a `complete` declaration if `retro.json` is absent or fails the
schema 3 source check. The check rejects a hand-written retro, stale source hashes, a broken
decision chain, or missing teardown steps. Run `retro.py assemble` before completion.
The guard also blocks when a frozen proof lacks a satisfied controller-recorded run row in
`proof_results.jsonl`. Run every proof before assembly (Step 1 below).

Before assembling the retro, run `graph.py flush-decisions <progress.json> --session <id>` through the
current provider's graph CLI. If it returns 3, record the named Muninn degradation or uncertain
sync and preserve the local decision rows; reconcile `decision_sync_unknown` against the store
before any manual retry. If it returns 2, stop and inspect the chain. The assembler reads the
`decisions_absorbed` rows from `progress.json`; do not copy or edit them by hand.

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

- **`LOOP-STOP` category counts, broken down by type** — the per-category counts of this loop's recorded stops (`progress.json` `loop_stop_counts`: `hard-stop`, `approval-gate`, `awaiting-input`, `complete`). HOOK-OWNED — the `loop_stall_guard` hook increments it when it consumes a valid `progress.json` `stops[]` row. Read it as-is; do not compute or edit it. Report the raw breakdown with no verdict attached.
- **Decisions absorbed** — a flat, unscored list of in-scope decisions the loop made autonomously without asking (e.g. a Phase 2.5 design-fork auto-adopted, a Phase 2.6 disposition defaulted to clean-break, a Phase 2.8 routing assignment set, a Phase 5 disconfirm-skip, a Phase 6 in-scope action taken without a check-in). No self-justification text per entry, no automated "this looks calibrated" stamp — just what was decided and where (phase/work-unit). The assembler reads `progress.json`'s `decisions_absorbed` array in chronological order. Report those rows verbatim; never reconstruct them from conversation memory.

**Also report, unscored:**

- **Artifacts produced** — PRs merged, deploys done, each with the verifying check (Phase 12), not the agent's claim.
- **Loop cost** — the per-model token + dated-USD breakdown mined into `retro.json`'s `cost` field, printed to the human WITH a price-staleness age: "prices as of `<cost.prices_as_of>`, N days old". This is a human-facing report deliverable, not just a stored artifact. `loop_stall_guard`'s cost reporter now prints it mechanically via `systemMessage` on every `complete` declaration, the same way `check_verify_loop.py` mechanically enforces the CLAUDE.md DNV rule — but the prose obligation below is still the floor, not something the hook replaces: the hook reports `retro.cost` verbatim (silent on a legacy pre-cost-miner retro, and never blocking on a miner failure), it does not relieve the orchestrator of assembling and writing that field correctly in the first place. The price table (`hooks/scripts/lib/model_prices.json`) is HAND-MAINTAINED — there is no pricing API, so nothing auto-updates it. Past `ALS_PRICE_STALE_DAYS` (14) days old, the reporter also nags a human to go check the rates; the nag verifies the DATE only, never the rates themselves, since staleness of a self-reported date can't prove the rates are wrong.
- **Disposition violations** — work-units where `clean-break` was recorded in `progress.json` but a shim/compat path shipped anyway (caught at the Phase 4b gate, or by the human afterward). Audit as a diff between the `progress.json` disposition record and the merged artifact. Critically, distinguish **"0 violations"** from **"no disposition record found"**: the latter is an **audit failure** — the record was not maintained — not a pass, otherwise the report reads "clean" when the record was simply absent. Separately, surface any `preserve-compat` unit whose `removal_ticket` is still **open at loop end** as a compat-debt drift signal, so deferred removals cannot silently rot.
- **Loop-scope eval result** — graded via `post_evals.py grade-loop` (never hand-written into `evals.json`), the loop's final `evals.json` `result` (`GO`/`NO-GO`/a verification_level-0-exemption-with-justification), reported unscored, plus any `amendments` entries (post-freeze eval edits with recorded reasons). An amendment made after a grader verdict must carry its fresh re-grade (`regraded_by` recorded; `grade-loop` refuses otherwise): a verdict flipped by an orchestrator-written status is an audit failure, not a pass. **"No `evals.json` record found" for a ≥1-work-unit loop is an audit failure, not a pass** — distinguish it from a genuine `GO` the same way "0 disposition violations" is distinguished from "no disposition record found".

## Step 1 — Run every `proof.json` cmd

If a `proof.json` was frozen at Phase 2.7e, have the controller run it — before assembling the retro:

```
python3 <plugin-root>/scripts/lib/proof.py freeze <state-dir>     # once, records the freeze row
python3 <plugin-root>/scripts/lib/proof.py run <state-dir> --all  # runs each frozen cmd in the pinned proof sandbox
python3 <plugin-root>/scripts/lib/proof.py status <state-dir>     # per-proof verdict from the latest run row
```

`<state-dir>` is the directory holding `progress.json`/`proof.json`. The script runs each `cmd` unchanged,
in the foreground, with its timeout. The command can read host files, write only below its fresh `TMPDIR`, and use
no network. The controller appends hash-chained rows to `proof_results.jsonl` after the command ends; the gate reads
those rows and nothing else (no transcript, no `status` field). A proof run any other way leaves no row and
cannot satisfy the `loop_stall_guard` proof gate. If a proof fails, fix the underlying issue and re-run
`proof.py run` (not a modified cmd; editing `proof.json` needs a fresh `freeze`) until it passes, or the
`complete` declaration below blocks, naming the offending proof id(s) and reason code. No `proof.json`
means nothing to run: record `proof.py disposition <state-dir> --none --reason-code <code> --reason <text>`
(or `proof_disposition: "none: <reason>"` in `progress.json`; a bare `"none"` is rejected) and skip to Step 2.

## Step 2 — Assemble `retro.json`

After Step 3 preparation and final decision flush, run
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lib/retro.py" assemble <state-dir> --session <session_id>`.
It writes schema 3 beside `progress.json`, derives the envelope, counters, decisions, evals, proof results,
dispositions, cost and memory disclosure from their sources, and records `retro_assembled` in `teardown.jsonl`.
`source_hashes` binds the precompletion sources and the required receipts: `proof_run`, `decisions_flushed`,
`orders_prepared`, `retro_assembled`. A postcompletion `orders_ticked` observation does not change those hashes.
Exit 3 means degraded memory sync is disclosed in the assembled retro; it does not waive graph or proof gates.
Do not hand-write or edit the assembled fields. Optional prose belongs in a JSON object passed through `--free-file`.

### Schema 3 field spec

The derived fields are `session_id`, `loop_id`, `created`, `status`, `envelope`, `loop_stop_counts`,
`decisions_absorbed`, `disposition_record`, `evals`, `proof_results`, `hook_blocks`, `models_used`,
`cost`, `teardown`, `memory`, `source_hashes`, and `free`. The schema has no `verdict` field.

## Cost-mining sub-step

`retro.py assemble` invokes `loop_cost.py` while deriving the cost field. It enumerates this loop's transcripts (the orchestrator's own
`~/.claude/projects/<slug>/<sid>.jsonl` plus every worker transcript under
`<proj>/<sid>/subagents/`, recursively), dedupes by `message.id` so a transcript read twice isn't
double-counted, sums per-model token usage, prices it from a dated price table, and returns a
single object carrying `prices_as_of`, `per_model`, `total_tokens`, `total_usd_estimate`, and
`models_used` all as siblings.

**Fold-in is a split, not a copy.** The assembler writes the miner's returned object as `retro.cost` (its own
nested `schema_version` 1, independent of the retro's), then lifts its `models_used` array to
`retro.models_used` (top-level). The retro itself is schema 3.

**Fail-open.** The miner never blocks teardown — on any environmental error (missing/invalid
price file) it returns `{}`, so both `retro.cost` and `retro.models_used` end up empty and a
`complete` declaration proceeds exactly as it would with populated values. The completion gate
checks the assembled retro's sources and steps, but does not rederive the cost field, so a miner
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

1. For each failure mode in this loop's retro, `$O record --failure-mode "<mode>" --lesson "<imperative lesson>" --loop <loop_id>`. Add `--scope agnostic` for a lesson that applies
   to any repo. Before completion this stages the observation and any cited sync; it changes no lifecycle counters.
   An id must name the same failure mode and scope. A claim over 500 collapsed characters is refused, never truncated.
2. After final progress updates and decision flush, record one `graph.py stop --category complete` row. Then run `$O prepare --loop <loop_id>` before assembling the retro. It validates the
   owned eligible graph and work units, binds the source directory, session, logical loop, revision and progress hash,
   and records `orders_prepared`. This also runs when the retro has no failure mode. Prospective eligibility authorizes
   preparation only.
   A changed source is refused by default. For a legitimate incomplete-source retry, pass
   `$O prepare --loop <loop_id> --refresh-from-sha256 <CURRENT evidence_sha256>` using the canonical hash returned by
   the current preparation. It preserves staged records, refuses rollback/foreign/already-applied sources, and has
   no lifecycle effect. A saved replacement whose receipt failed needs ordinary unchanged `prepare` to repair it.
   Flush and reload pending source updates before the final stop. Do not record another stop on retry. Never refresh after durable completion.
3. After native completion is durably saved, that command runs `$O tick --loop <loop_id>` and `$O render --loop
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

The graduation predicate and the promotion selection are `$O predicate` and `lessons.py predicate`. This step is
additive-or-recurrence-only: no metric-based removal anywhere.

**Typed lessons (Muninn authoritative).** Each order requests a task-scoped Muninn review of the source session.
The one orders lock covers local staging, request submission and later inspection. An unknown marker is saved before
submission. A bound `order-request-*.json` journal saves a returned R_ ID before the final order save. If the reply
is lost and no journal exists, do not submit again; inspect `muninn learn list` and the source window.
A saved R_ ID stays pending until its completed receipt yields one exact active K_ note. The old `--quote` option is
accepted for compatibility, ignored, and reported as `quote_ignored`; it does not supply evidence to this request.
Exit 3 prints `{"muninn": {... "reason_code": ...}}`:
**report that reason code in the retro; never skip it silently and never write the lesson to Markdown instead.**
`memory.backend: off` (reason `memory_backend_off`, exit 0) is the only explicit opt-out. A first-time adoption of an old
hand-written file is `$O import-legacy` (it archives a byte copy and retains the original). Verify the archive and
ledger, then retire the hand-written source before generating `standing-orders.md`. Runbook:
`docs/RUNBOOK.md`, "Standing order stored without a cite"; decision records:
`docs/decisions/2026-10-05-memory-authoritative.md`, `docs/decisions/2026-10-05-orders-vs-muninn-overlap.md`.

## Steps 4 and 5

4. **Write feedback-type auto-memories** for lessons that generalise beyond this loop.
5. **Only then** run `loop_state_common.py mark-complete <cwd> <session_id>` to validate native completion, recheck the
   prepared orders source, save progress, apply the tick and render, and stamp `completed_marker` — e.g.
   `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/lib/loop_state_common.py" mark-complete "$PWD" "<session_id>"`.
   Never write `status: "complete"` via a bare atomic update — that leaves
   `completed_marker` unstamped at its prior value (permanently 0 for a loop's first completion),
   which false-positives `loop_state_guard`'s `stale_complete_rearmed` block on every later turn of
   the same session. If completion reports pending teardown, repeat `mark-complete` to resume it. Then run
   `graph.py verify-completion <state> --session <session_id>` to check the graph and bound orders evidence. Render
   `LOOP-STOP: complete` for the human. The hook reads the row recorded before preparation, not this text. First apply
   `superpowers:verification-before-completion` to the orchestrator's own completion claim
   (SKILL.md's Phase 13 links the `finishing-out.md` detail). The `loop_stall_guard` proof gate
   blocks the declaration itself if Step 1 was skipped or left a proof unexecuted/failed — it does
   not need a separate manual check here.
