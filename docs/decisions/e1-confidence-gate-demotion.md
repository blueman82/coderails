# E1: demote the Stop discipline gates?

> Superseded 2026-10-04 by `2026-10-04-not-in-gate-demotion.md`: the user overrode the unmet criteria and demoted both gates to advisory lints. The verdict below is retained as the record of why the criteria were not met.

Verdict: **criteria NOT met. No behaviour change. No exit code edited. Hooks stay.**

## Rule

`docs/graph-alignment-measurement.md`, rule (a): a gate is a demotion candidate only if all hold: at least 100
`decisions`; `blocked / decisions` of at least 10%; and a hand-sampled real-fix rate below 30% over at least 30
of its blocks. "Without the sampled rate, no gate may be called demotable."

## Numbers (2026-10-04, local Claude log 2026-08-04 to 2026-10-04)

Reproduce: `python3 scripts/measure_graph_alignment.py --root . --json`
(then `['gate_blocks']['claude']['gates']['confidence_labels' | 'verify_loop']`).

| Gate | blocked | decisions | blocked/decisions | blocked/total lines | Rule (a) |
| --- | ---: | ---: | ---: | ---: | --- |
| `confidence_labels` | 200 | 272 | 73.5% | 5.2% (200/3843) | volume and ratio legs met on decisions; **real-fix leg never sampled** |
| `verify_loop` | 160 | 3663 | 4.4% | 4.4% | **fails the 10% leg** |

The earlier 194/258 baseline is stale. The log is a live append-only file, so figures drift upward.

- Hand-sample of at least 30 `confidence_labels` blocks: **not taken** (it needs transcript reads, which the
  measurement script deliberately never does). Status: undecided, not "passed".
- Read on all evaluations the doc says `confidence_labels` would not cross 10%.
- `verify_loop` fails the ratio leg regardless of any sample, so it stays blocking.

## Behaviour at time of writing (read from source; superseded, outside-loop `Stop` is now an advisory exit 0 for both hooks)

- Outside a loop, `Stop` exits 2 (both hooks).
- Inside an active loop, `Stop` already emits a `[discipline-warn(loop)]` `additionalContext` and exits 0
  (`loop_active_incomplete` branch).
- `SubagentStop` has no loop branch and blocks. The doc dictates that worker output stays blocking; kept.
- Headless `Stop` (`CODERAILS_HEADLESS_RUN=1`) is already skipped.
- Codex has `check_confidence_labels.py` only; there is no Codex `verify_loop`.

## What this change adds (observability only)

- `reason_code=confidence_label_missing` / `reason_code=verify_loop_missing` on the existing `blocked=1` and
  `warned=1` log lines. The `hook=`, `blocked=`, `would_block=`, `warned=` fields the counters read are unchanged.
- One non-authoritative trace row per block or warning (`command` = hook script, `outcome` = blocked | warned).
  Count them with `['trace']['by_reason']` in the same command.
- Guard: the 12 discipline fixture suites (`discipline_responses_test.py`) pass unchanged; the new
  `discipline_reason_code_test.py` fails if the field or the row is removed.

## Flip condition

If a hand-sample of at least 30 `confidence_labels` blocks (next turn changed substance, versus a token appended)
shows a real-fix rate under 30%, with 100+ decisions and blocked/decisions of at least 10% still holding, demote
only the outside-loop `Stop` branch of `check_confidence_labels.py` by reusing its existing warn-and-exit-0 branch,
keeping the `blocked` / `would_block` / `warned` log fields. `verify_loop` stays blocking either way.
