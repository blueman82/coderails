# Not-in gate demotion: confidence labels and Did Not Verify become advisory lints

Status: user override accepted on 2026-10-04. **Supersedes**
`e1-confidence-gate-demotion.md`.

## Decision

`hooks/scripts/check_confidence_labels.py` and
`hooks/scripts/check_verify_loop.py` no longer block on Stop or
SubagentStop. This applies inside and outside a loop. A flagged event now:

- emits `[discipline-advisory]` in `additionalContext`, with no stderr and
  exit 0;
- logs `would_block=1 demoted=1 blocked=0` and the applicable
  `reason_code=<confidence_label_missing|verify_loop_missing>`;
- appends a non-authoritative trace row with `outcome=demoted`. Old
  `blocked` and `warned` rows keep their original meaning.

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

The real-fix rate was not sampled for either gate. The logs are live and
append-only, so their counts change over time.

## Consequences

- `blocked / decisions` for these two gates falls to about 0. The pre-demotion value is the baseline; compare
  `demoted / decisions` afterwards. Reproduce: `python3 scripts/measure_graph_alignment.py --root . --json`
  and read `gate_blocks.claude.gates.<gate>` (`blocked`, `would_block`, `warned`, `demoted`) and `trace.by_reason`.
- Delivery caveat (inferred, not proven): `additionalContext` at Stop or
  SubagentStop may not reach the model. Do not call the warning
  "model-visible" without a live test. Until then, describe it as
  "advisory plus trace". If a live run shows the host drops it, the lint
  only logs. The user can then choose logging alone, a `systemMessage`
  fallback, or a blocking path.
- The Codex copy in
  `packages/codex/hooks/scripts/check_confidence_labels.py` is separate.
  It also emits an advisory through `hookSpecificOutput.additionalContext`
  and always exits 0. Its `append_trace_row` writes a fail-open `demoted`
  row. Codex has no `verify_loop` hook. Codex host delivery of
  `additionalContext` at Stop or SubagentStop remains unverified.
