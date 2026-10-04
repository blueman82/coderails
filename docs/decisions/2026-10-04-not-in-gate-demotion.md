# Not-in gate demotion: confidence labels and Did Not Verify become advisory lints

Status: accepted by user override, 2026-10-04. **Supersedes** `e1-confidence-gate-demotion.md`.

## Decision

`hooks/scripts/check_confidence_labels.py` and `hooks/scripts/check_verify_loop.py` no longer block on any path
(`Stop` outside a loop, `Stop` inside a loop, `SubagentStop`). A flagged event now:

- emits a `[discipline-advisory]` `additionalContext` for the event, with no stderr and exit 0;
- logs `would_block=1 demoted=1 blocked=0 reason_code=<confidence_label_missing|verify_loop_missing>`;
- appends a non-authoritative trace row with `outcome=demoted` (rows already written as `blocked` and `warned`
  keep their meaning, so the three series stay separable).

Unchanged: the hooks stay registered (`hooks.json`), the headless `Stop` skip, `loop_stall_guard`,
`loop_state_guard`, the destructive-shell gate and every other gate.

## User override of the unmet criteria

Rule (a) in `docs/graph-alignment-measurement.md` and the e1 verdict said the criteria were not met. They were
not, and this change does not claim otherwise. The user directed the demotion regardless.

| Source | `confidence_labels` blocked/decisions | `verify_loop` blocked/decisions |
| --- | ---: | ---: |
| e1 verdict | 200/272 | 160/3663 (4.4%, fails the 10% leg) |
| measurement doc | 194/258 | 153/3546 |
| `measure_graph_alignment.py` at this commit's base | 202/277 | 163/3704 |

The real-fix-rate leg was never sampled for either gate. The logs are live and append-only, so every figure drifts up.

## Consequences

- `blocked / decisions` for these two gates falls to about 0. The pre-demotion value is the baseline; compare
  `demoted / decisions` afterwards. Reproduce: `python3 scripts/measure_graph_alignment.py --root . --json`
  and read `gate_blocks.claude.gates.<gate>` (`blocked`, `would_block`, `warned`, `demoted`) and `trace.by_reason`.
- Delivery caveat (inferred, not proven): `additionalContext` at `Stop`/`SubagentStop` may not reach the model.
  Do not call the advisory "model-visible" until a live session shows it. Until then the change is
  "advisory plus trace". If a live run shows it is dropped, the lint is a pure logger; the user then chooses between
  a logger-only lint, a `systemMessage` fallback, or reintroducing a blocking path.
- The Codex copy (`packages/codex/hooks/scripts/check_confidence_labels.py`) is a separate implementation. It is
  demoted the same way (advisory via `hookSpecificOutput.additionalContext`, always exit 0, a fail-open `demoted`
  trace row via its own `append_trace_row`). Codex has no `verify_loop` hook. Codex host handling of
  `additionalContext` at Stop/SubagentStop is unverified, same caveat as above.
