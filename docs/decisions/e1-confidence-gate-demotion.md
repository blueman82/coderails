# E1: demote the Stop discipline gates?

> Superseded 2026-10-04 by `2026-10-04-not-in-gate-demotion.md`: the user overrode the unmet criteria and demoted the two gates to advisory lints. This verdict records the unmet criteria.

Verdict: **Criteria NOT met. No behavior change. No exit code change. Hooks stay.**

## Rule

A gate qualifies for demotion only if it satisfies all conditions in rule (a) of `docs/graph-alignment-measurement.md`:

- The gate has 100 or more `decisions`.
- `blocked / decisions` is 10% or more.
- Fewer than 30% of the blocked replies in a manual sample have substantive corrections. The sample has 30 or more blocks.

"Without the sampled rate, no gate may be called demotable."

## Numbers (2026-10-04, local Claude log 2026-08-04 to 2026-10-04)

Run `python3 scripts/measure_graph_alignment.py --root . --json`.
Read `['gate_blocks']['claude']['gates']['confidence_labels' | 'verify_loop']`.

| Gate | blocked | decisions | blocked/decisions | blocked/total lines | Rule (a) |
| --- | ---: | ---: | ---: | ---: | --- |
| `confidence_labels` | 200 | 272 | 73.5% | 5.2% (200/3843) | Above the count and ratio thresholds. **No sample of substantive corrections.** |
| `verify_loop` | 160 | 3663 | 4.4% | 4.4% | **Below the 10% threshold** |

The previous baseline of 194/258 is stale. The log is live and append-only, so the figures can increase.

- No one sampled 30 or more `confidence_labels` blocks. The sample uses transcripts, which the measurement script does not read.
  The verdict for this condition remains open.
- The measurement document says `confidence_labels` is below 10% if the denominator is all checks.
- `verify_loop` stays blocking because its ratio is below 10%. A sample cannot change that result.

## Behaviour at time of writing (read from source; superseded, outside-loop `Stop` is now an advisory exit 0 for both hooks)

- Out of a loop, `Stop` exits with code 2 for the two hooks.
- In an active loop, `Stop` gives a `[discipline-warn(loop)]` `additionalContext` and exits with code 0 (`loop_active_incomplete` branch).
- `SubagentStop` has no loop branch and blocks. This keeps the block on worker output that the measurement document specifies.
- Headless `Stop` (`CODERAILS_HEADLESS_RUN=1`) skips the check.
- Codex has `check_confidence_labels.py` only. It has no `verify_loop` hook.

## What this change adds (observability only)

- `reason_code=confidence_label_missing` or `reason_code=verify_loop_missing` on the `blocked=1` and `warned=1` log lines.
  The `hook=`, `blocked=`, `would_block=`, and `warned=` fields that the counters read stay the same.
- One advisory diagnostic log entry for a block or warning (`command` = hook script, `outcome` = blocked | warned).
  Count them with `['trace']['by_reason']` in the same command.
- The 12 discipline fixture suites (`discipline_responses_test.py`) complete with the same results.
  The new `discipline_reason_code_test.py` fails if someone removes the field or the log entry.

## Flip condition

Manually sample 30 or more `confidence_labels` blocks. Count a substantive correction when the next reply changes its content.
Do not count a reply that only appends a token.

If the correction rate is below 30%, check that the gate has 100 or more decisions and `blocked / decisions` of 10% or more.
If all conditions hold, demote only the `Stop` branch of `check_confidence_labels.py` for sessions out of a loop.
Use its warn-and-exit-0 branch and keep the `blocked`, `would_block`, and `warned` log fields.
`verify_loop` stays blocking with all results.
