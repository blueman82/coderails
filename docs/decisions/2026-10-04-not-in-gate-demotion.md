# Not-in gate demotion: confidence labels and Did Not Verify become advisory lints

Status: accepted by user override, 2026-10-04. **Supersedes** `e1-confidence-gate-demotion.md`.

## Decision

The hooks `hooks/scripts/check_confidence_labels.py` and `hooks/scripts/check_verify_loop.py` no longer block.
This applies to `Stop` in a loop, `Stop` out of a loop, and `SubagentStop`. If a check flags a problem, the hook:

- Gives a `[discipline-advisory]` `additionalContext`. It writes nothing to stderr and exits with code 0.
- Logs `would_block=1 demoted=1 blocked=0 reason_code=<confidence_label_missing|verify_loop_missing>`.
- Appends an advisory diagnostic log entry with `outcome=demoted`.
  Previous `blocked` and `warned` entries keep their meaning. The three series use different outcome values.

The hooks stay in `hooks.json`. The headless `Stop` skip continues to apply.
The change keeps `loop_stall_guard`, `loop_state_guard`, the destructive-shell gate, and all other gates.

## User override of the unmet criteria

The results did not satisfy rule (a) in `docs/graph-alignment-measurement.md` or the criteria in the e1 verdict.
The user directed the demotion.

| Source | `confidence_labels` blocked/decisions | `verify_loop` blocked/decisions |
| --- | ---: | ---: |
| e1 verdict | 200/272 | 160/3663 (4.4%, below 10%) |
| measurement doc | 194/258 | 153/3546 |
| `measure_graph_alignment.py` at this commit's base | 202/277 | 163/3704 |

No one sampled the rate of substantive corrections for the two gates. The logs are live and append-only, so the figures can increase.

## Consequences

- `blocked / decisions` for these two gates falls to about 0. The pre-demotion value is the baseline.
  Compare it with `demoted / decisions`. Run `python3 scripts/measure_graph_alignment.py --root . --json`.
  Read `gate_blocks.claude.gates.<gate>` (`blocked`, `would_block`, `warned`, `demoted`) and `trace.by_reason`.

- The model might not get `additionalContext` at `Stop` or `SubagentStop` (inferred, not proven).
  Use "model-visible" for the advisory only after a live session shows it. Until then the change is "advisory plus trace".
  If a live run shows no message, the lint only logs. The user can keep logging only, use `systemMessage`, or make the lint block again.

- Codex uses its own implementation in `packages/codex/hooks/scripts/check_confidence_labels.py`.
  It gives an advisory through `hookSpecificOutput.additionalContext` and always exits with code 0.
  It tries to log `demoted` through `append_trace_row` without blocking on error.
  Codex has no `verify_loop` hook. There is also no live confirmation that the model gets `additionalContext` at Stop/SubagentStop.
