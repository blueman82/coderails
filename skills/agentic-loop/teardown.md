# Teardown write contract — `retro.json` and standing-orders

Use this file for Phase 13 teardown.
Prepare the inputs and assemble the retro before the durable save of the completed loop.
Apply the standing-order records after that save.
Use the commands below to write the source files.

The `loop_stall_guard` hook blocks `complete` if there is no `retro.json` or the schema 3 source check refuses it.
The check refuses a hand-written retro, stale source hashes, a broken decision chain, or missing teardown steps.
Run `retro.py assemble` before you complete the loop.
Each frozen proof must have a controller run row with a satisfactory verdict in `proof_results.jsonl`.
Run each proof before assembly as in Step 1.

Before assembly, run `graph.py flush-decisions <progress.json> --session <id>` with the current provider’s graph CLI.
For exit 3, report the Muninn degradation or uncertain sync. Keep the local decision rows.
Before a manual retry, reconcile `decision_sync_unknown` against the store.
For exit 2, stop and examine the chain.

The assembler reads `decisions_absorbed` from `progress.json`.
Do not copy or edit those rows by hand.

**Boundary for graph dispatch.**
The Claude role map has no entries for `S13-proof`, `S13-retro`, or `S13-complete`.
The native graph CLI `plan` command reports them as `unresolved:true`.
The orchestrator does these steps and keeps their results in the phase and artifact record.
Do not make fake worker-completed nodes for them.
To start a graph worker, resolve its instruction source and use the native worker records.

## Contents

- [The Phase 13 self-audit report](#the-phase-13-self-audit-report)
- [Step 1 — Run each `proof.json` cmd](#step-1--run-every-proofjson-cmd)
- [Step 2 — Assemble `retro.json`](#step-2--assemble-retrojson)
- [Cost-mining sub-step](#cost-mining-sub-step)
- [Frozen pricing](#pricing-is-computed-once-and-frozen)
- [Step 3 — Update the standing-order records](#step-3--update-the-standing-orders-code-not-prose)
- [Steps 4 and 5](#steps-4-and-5)

## The Phase 13 self-audit report

Read the autonomy counters in `progress.json`.
Report the facts without a score or target.
Let the user judge if the loop should have waited for approval.

**Report these two facts:**

- **`LOOP-STOP` counts.** Read the `loop_stop_counts` categories from `progress.json`: `hard-stop`, `approval-gate`, `awaiting-input`, and `complete`. The `loop_stall_guard` hook adds to these counts when it consumes a correct `stops[]` row. Read the counts as written. Do not calculate, edit, or score them.
- **Decisions absorbed.** Report the in-scope decisions the loop made without user input. For example, report Phase 2.5 auto-adoption, a Phase 2.6 clean-break default, Phase 2.8 role assignments, or a Phase 5 disconfirm-skip. Also include Phase 6 steps you did without a check-in. Give the decision and its phase or unit. Use no score or self-justification. The assembler reads `decisions_absorbed` from `progress.json` in chronological sequence. Copy those rows verbatim. Do not reconstruct them from conversation memory.

**Also report these results without a score:**

- **Artifacts.** Give the PRs merged and deployments done. Include the Phase 12 check for each artifact.
- **Loop cost.** Report token counts and dated USD estimates for each model from the `cost` field in `retro.json`. Include the age of the prices: "prices as of `<cost.prices_as_of>`, N days old". The `loop_stall_guard` hook also reports `retro.cost` verbatim through `systemMessage` on `complete`. It reports no cost for a legacy retro without a cost field. It does not block on a miner error. The orchestrator must assemble the field correctly and report the cost. This is like the CLAUDE.md DNV rule that `check_verify_loop.py` checks.

  Keep the price table `hooks/scripts/lib/model_prices.json` current by hand. No pricing API updates it. If prices are older than `ALS_PRICE_STALE_DAYS` (14), the reporter tells the user to check rates. It checks the price date only. An older date does not show if the rates are incorrect.

- **Retirement decision violations.** Compare the decisions in `progress.json` with the merged artifacts. Report a unit that used `clean-break` and shipped a shim or compatibility path. The Phase 4b gate or the user can find these violations. Use "0 violations" only when the records show none. Report "no disposition record found" as an audit error. Also report a `preserve-compat` unit with a `removal_ticket` open at loop end. Include the deferred removal in the report.
- **Loop-scope eval result.** Use `post_evals.py grade-loop`. Report the last `evals.json` `result` without a score. It can be `GO`, `NO-GO`, or a verification_level-0 exemption with justification. Include all `amendments` and their recorded causes. Do not write the verdict in `evals.json` by hand.

  If an eval changes after a grader verdict, obtain a new grade and record `regraded_by`. Without it, `grade-loop` refuses the result. Report an orchestrator-written status change that flips a verdict as an audit error. For a loop with one or more work units, "No `evals.json` record found" is an audit error. Distinguish it from `GO` as you distinguish "0 disposition violations" from "no disposition record found".

## Step 1 — Run every `proof.json` cmd

If a `proof.json` was frozen at Phase 2.7e, have the controller run it — before assembling the retro:

```
python3 <plugin-root>/scripts/lib/proof.py freeze <state-dir>     # Run one time to record the freeze row.
python3 <plugin-root>/scripts/lib/proof.py run <state-dir> --all  # runs each frozen cmd in the pinned proof sandbox
python3 <plugin-root>/scripts/lib/proof.py status <state-dir>     # per-proof verdict from the latest run row
```

Use the directory with `progress.json` and `proof.json` as `<state-dir>`.
The script runs each `cmd` unchanged in the foreground with its timeout.
The command can read host files and write only in its new `TMPDIR`.
It cannot use the network.
After the command ends, the controller appends a hash-chained row to `proof_results.jsonl`.

The proof gate reads only those rows.
It does not read the transcript or `status` field.
A proof run by other means does not give the `loop_stall_guard` a controller row.

If a proof fails, correct the underlying problem and run `proof.py run` again.
Keep the `cmd` unchanged.
If `proof.json` changes, run `freeze` again.
If the latest verdict does not satisfy the check, the gate blocks `complete` and gives the proof IDs and cause code.

If there is no `proof.json`, run `proof.py disposition <state-dir> --none --reason-code <code> --reason <text>`.
You can also use `proof_disposition: "none: <reason>"` in `progress.json`.
The gate refuses a bare `"none"`.
Continue at Step 2.

## Step 2 — Assemble `retro.json`

After Step 3 setup and the last decision flush, run
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lib/retro.py" assemble <state-dir> --session <session_id>`.
It writes schema 3 next to `progress.json`.
It reads the envelope, counters, decisions, evals, proof results, retirement decisions, cost, and memory disclosure from their sources.
It records `retro_assembled` in `teardown.jsonl`.

The `source_hashes` field binds the sources before the save of the completed loop and the receipts `proof_run`, `decisions_flushed`, `orders_prepared`, and `retro_assembled`.
The `orders_ticked` record after the save does not change those hashes.
Exit 3 means the retro discloses degraded memory sync.
The graph and proof gates continue to apply.
Do not write or edit derived fields by hand.
For optional prose, use a JSON object through `--free-file`.

### Schema 3 field spec

The derived fields are `session_id`, `loop_id`, `created`, `status`, `envelope`, `loop_stop_counts`,
`decisions_absorbed`, `disposition_record`, `evals`, `proof_results`, `hook_blocks`, `models_used`,
`cost`, `teardown`, `memory`, `source_hashes`, and `free`. The schema has no `verdict` field.

## Cost-mining sub-step

The `retro.py assemble` command invokes `loop_cost.py` to calculate cost.
It reads `~/.claude/projects/<slug>/<sid>.jsonl` and worker transcripts recursively below `<proj>/<sid>/subagents/`.
It uses `message.id` to count each message one time.
It sums tokens for each model and uses a dated price table.
It gives one object with `prices_as_of`, `per_model`, `total_tokens`, `total_usd_estimate`, and `models_used`.

The assembler puts the cost data in `retro.cost` with its own nested `schema_version` 1.
It moves the `models_used` array to top-level `retro.models_used`.
The retro itself uses schema 3.

**Cost does not block teardown.**
If the environment has an error such as a missing or malformed price file, the miner gives `{}`.
Then `retro.cost` and `retro.models_used` are empty.
The gate for `complete` checks the retro’s sources and steps and does not calculate cost again.

There are two caller errors: no session ID, or a session ID with no transcript in the projects directory.
For these errors, the miner prints `{"error":...,"hint":...}` to stdout. For an environment error, it gives `{}`.
See the header comment in its library.

An outdated or incorrect `<session_id>` can cause the same problem as a missing ID.
Check the output. If it has `.error`, record its text in the retro.

## Pricing is computed once and frozen

The miner calculates `cost.per_model[*].usd_estimate` and `cost.total_usd_estimate` one time at teardown.
It records `cost.prices_as_of` and `cost.price_source`.
The dashboard must sum the saved `usd_estimate` or `total_usd_estimate` values as written.
Do not calculate a price again from token counts with a live table.
Do not add a dashboard-side "current price" toggle.
Use the number frozen at teardown.

## Step 3 — Update the standing orders (code, not prose)

The typed standing-order records are in `<repo-key dir>/orders.json`, two directories above `progress.json`.
Use only `scripts/lib/orders.py` to change them.
The files `standing-orders.md` and `standing-orders-decayed.md` are read-only views.
Do not write them by hand. The `render` command refuses an unmarked file with `handwritten_protected`.

Run these steps from the orchestrator session.
Use `O="python3 ${CLAUDE_PLUGIN_ROOT}/scripts/lib/orders.py --dir <repo-key dir> --session <session_id>"`.
Copy the logical `loop_id` from the owned `progress.json`.
The session directory name is a different value.

1. For each problem in the retro, run `$O record --failure-mode "<mode>" --lesson "<imperative lesson>" --loop <loop_id>`. Add `--scope agnostic` for a lesson that applies across repos. Before the save of the completed loop, this saves the observation and cited sync for the apply step. It changes no lifecycle counters. An ID must name the same problem and scope. The command refuses claims longer than 500 collapsed characters and does not truncate them.
2. After the last loop updates and decision flush, record one `graph.py stop --category complete` row. Run `$O prepare --loop <loop_id>` before assembling the retro. It checks the owned graph and work units for eligibility. It records `orders_prepared` for the source directory, session, logical loop, revision, and hash of the loop data. Run it also if the retro lists no problems. Prospective eligibility permits setup only.

   By default the command refuses a changed source. To retry a source that did not finish, use `$O prepare --loop <loop_id> --refresh-from-sha256 <CURRENT evidence_sha256>` with the canonical hash the current setup gives you. The command keeps the records for application. It refuses rollback, other sources, and sources it applied before. It changes no lifecycle counters. If the replacement save succeeded but its receipt did not, run ordinary `prepare` against the unchanged replacement.

   Flush and read pending source updates before the last stop. Do not record a new stop on retry. Do not refresh after the durable save of the completed loop.
3. After the native command saves the completed loop, that command runs `$O tick --loop <loop_id>` and `$O render --loop <loop_id>`. It applies the recorded recurrences and ages each unmatched active record one time. A recurrence from a new completed session and loop resets the counter and revives a tombstone. Replay does not change the counter or revive a tombstone. At **K=5**, a record becomes `decayed` and stays in the ledger. The decayed record appears only in `standing-orders-decayed.md`.

Setup and apply read `<repo-key dir>/<session_id>/progress.json`.
They check ownership and source binding.
They refuse missing, malformed, unfinished, stale sources or sources with a different identity.
If the native command cannot save the completed loop, no record ages.
The `orders_ticked` observation follows the ledger save.

If the ledger save or observation fails after the loop completes, the command reports `pending_teardown: true`.
Run the native command again to continue the same bound tick and render.
The Claude Stop guard blocks until the bound receipts and views are current.
The Codex equivalent is in `packages/codex/skills/agentic-loop/SKILL.md`.

A previously completed loop without D4 receipts needs explicit legacy admission after a reviewer check.
See the standing-order decision and runbook.
Admission checks the file hash and permits bookkeeping for the completed loop with the bound graph source.
It does not age records.
Do not use it for a new loop.

Use `$O predicate` and `lessons.py predicate` for graduation and promotion selection.
This step adds records or recurrences only.
Do not remove records based on metrics.

**Typed lessons use Muninn as the source.**
Run `$O` from the mapped project repo.
One standing-order lock covers the callback and local save.
The teardown receipt uses its own short lock.
The `record` command saves an unknown-before-submit marker.
Then it keeps the R-id, source window, project, and task that it gets.

A pending submission has no written lesson.
For a current read, use the committed receipt and current Note for that submission.
The `$O cite <id>` command examines the initial retained source submission, also for recovery from a different session.
A new task and source session get their own marker and submission.

Do not resubmit automatically if the submission is unknown and has no R-id.
Changing the claim alone does not clear the restriction.
Keep the initial unknown claim hash.
Report `reconciliation_reason: learning_request_unknown`.
The command ignores the deprecated `--quote` input and reports that.
Use the selected source citations.

Keep the revision, conditions, expiry, selected quotes, and all `supports` mappings in the lesson output.
Conditional dispatch, promotion, and rendering remain `learning_conditional_use_unsupported`.
Check conditions before you say they are satisfied.
Sensitivity is unknown. Scope, physical source, redaction, and owner-authority checks do not classify it.

For exit 3, report the explicit cause in the retro.
Do not use Markdown or an uncited local claim for that disclosure.
Use `memory.backend: off` to opt out.
Legacy imports are local diagnostics without citations.

Source citations do not show initial I native, live, installed, or release approval.
Codex has its own live qualification.
Claude live qualification remains unfinished.
See `docs/RUNBOOK.md`, "Current request and citation boundary".

## Steps 4 and 5

4. Write feedback-type auto-memories for lessons that apply to other loops.
5. Then run `loop_state_common.py mark-complete <cwd> <session_id>`. It checks the native result and the prepared standing-order source. It writes the loop data, applies the tick and render, and records `completed_marker`. For example, run `python3 "${CLAUDE_PLUGIN_ROOT}/hooks/scripts/lib/loop_state_common.py" mark-complete "$PWD" "<session_id>"`.

   Do not write `status: "complete"` with a bare atomic update. This keeps `completed_marker` at its previous value, such as 0 for the first completed loop. This can cause `stale_complete_rearmed` on subsequent turns in the session.

   If the result reports pending teardown, run `mark-complete` again. Then run `graph.py verify-completion <state> --session <session_id>` to check the graph and the bound standing-order records.

   Apply `superpowers:verification-before-completion` to the orchestrator’s claim as in SKILL.md and `finishing-out.md`. Write `LOOP-STOP: complete` for the user. The hook reads the stop row from before setup. The proof gate blocks if Step 1 did not run or if a proof did not succeed.
