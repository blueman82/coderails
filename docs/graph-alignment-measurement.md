# Graph-alignment measurement (plan section 28)

This document records measurements after migration. It makes no behavior changes and leaves `work_units` and `graph.nodes` as different fields.

## Method

Run `python3 scripts/measure_graph_alignment.py --root . --json`. The script uses only the standard library and does not write data.
It prints counts and paths without log-message, transcript, or prompt content.
The author ran it against `origin/main` at `04b0eef7f089aebd17ab09ea1464d65b46380d32` on 2026-10-03T19:27+01:00.
The telemetry and loop data come from that workstation only.

| Key | Source | Rule |
| --- | --- | --- |
| `hook_counts` | `hooks/hooks.json`, `packages/codex/hooks/hooks.json` | Number of registered commands for each hook type. |
| `bootstrap_bytes` | `hooks/scripts/inject_bootstrap.py`, `packages/codex/hooks/scripts/inject_bootstrap.py` | The script runs each hook with an empty `{}` payload and counts UTF-8 bytes in `additionalContext`. The missing cwd and session mean the measurement has no legacy-config nudge or Codex graph-resume text. It gives the static minimum. |
| `gate_blocks` | `~/.claude/discipline.log` (override `CLAUDE_DISCIPLINE_LOG`) and `~/.coderails/codex/discipline.log` (overrides `PLUGIN_DATA`, `CODERAILS_DISCIPLINE_LOG`) | The script reads lines with `hook=<name>`. The `total` count includes all lines with that name. The `decisions` count includes only lines with `blocked=0` or `blocked=1`. The `blocked`, `would_block`, and `warned` counts use value `1` in those fields. If the script finds no log, it gives zero counts. |
| `graph_vs_work_units` | `<root>/*/*/progress.json` for `CLAUDE_AGENTIC_LOOP_DIR` or `CODERAILS_AGENTIC_LOOP_DIR` (default `~/.coderails/agentic-loop`), `~/.claude/agentic-loop`, and `~/.codex/agentic-loop`. The script counts each resolved path only one time. | Count divergence only if `work_units` and `graph.nodes` are nonempty and only one group has all entries in terminal status. Nodes use `done` or `skipped`. The strict check for work units follows `loop_completion.py` and accepts only `done` or `dropped`. The lenient check also accepts work-unit statuses that start with `done` or `dropped`, as many have free-text values. |
| `duplication` | Line counts for the three `graph_semantics.py` copies and the two provider `agentic-loop/scripts` directories. | Use SHA-256 to compare content. |

The discipline log is append-only for the life of the workstation. The Claude log starts on 2026-08-04.
The Codex log covers 2026-08-20 to 2026-09-17. The Claude figures include the hooks from the session that ran the script.
The field `blocked=1` records a block. It cannot show if the block was correct or useful.

## Measured data (verbatim from the run)

### Hook counts

| Hook type | Claude | Codex |
| --- | ---: | ---: |
| SessionStart | 2 | 1 |
| UserPromptSubmit | 2 | 2 |
| PreToolUse | 11 | 8 |
| PostToolUse | 1 | 1 |
| Stop | 8 | 3 |
| SubagentStop | 3 | 1 |
| **Total** | **27** | **16** |

### Bootstrap bytes (SessionStart: startup, clear, compact; Codex also resume)

| Provider | Bytes added | Contents |
| --- | ---: | --- |
| Claude | 6288 | Wrapper plus full `skills/using-coderails/SKILL.md` (6057 bytes). |
| Codex | 225 | The hook tells the agent to use `coderails-codex:using-coderails`. A subsequent agent tool call loads its 5089 bytes, so they do not count in 225. The registered `additionalContextLimit` is 1200. |

### Gate telemetry

Claude log: 15394 hook lines, 2026-08-04T19:36:33+01:00 to 2026-10-03T19:26:31+01:00.

| Gate | total | decisions | blocked | would_block | `warned` | blocked / decisions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| confidence_labels | 3712 | 258 | 194 | 322 | 64 | 75.2% |
| verify_loop | 3546 | 3546 | 153 | 6 | 6 | 4.3% |
| loop_stall_guard | 495 | 469 | 37 | 0 | 0 | 7.9% |
| loop_dispatch_guard | 21 | 21 | 5 | 0 | 0 | 23.8% |
| crack_on_prose_gate (retired, historical) | 103 | 103 | 5 | 0 | 0 | 4.9% |
| loop_state_guard | 780 | 780 | 6 | 0 | 0 | 0.8% |
| voice_announce | 448 | 309 | 0 | 0 | 0 | 0.0% |
| agent_only_gate, agent_model_routing_nudge, crack_on_gate, enforce_pr_workflow, no_edit_on_main, offload_push_guard, unregistered_loop_guard | 7 gates, 6289 lines combined | 0 | 0 | 0 | 0 | n/a (the log has no `blocked=` field) |

The `confidence_labels` hook writes a bookkeeping line on each check (3453 lines: 769 Stop plus 2684 SubagentStop).
It writes a decision line only when text of 200 or more characters has no label. The 194 blocks are 5.6% of all checks.
The 75.2% figure applies only to checks that found a missing label.

Codex log: 117 hook lines, 2026-08-20T11:40:26+01:00 to 2026-09-17T11:30:25+01:00.

| Gate | total | decisions | blocked | would_block | `warned` | blocked / decisions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| graph_completion_guard | 114 | 114 | 114 | 0 | 0 | 100.0% (the hook logs blocks only, so the count has no denominator for all checks) |
| loop_dispatch_guard | 2 | 2 | 0 | 0 | 0 | 0.0% |
| no_edit_on_main | 1 | 0 | 0 | 0 | 0 | n/a |

### Loop state: graph versus work_units

| Measure | Count |
| --- | ---: |
| Loops scanned (`progress.json`) | 42 |
| With non-empty `work_units` | 19 |
| With `graph.nodes` | 39 |
| With the two fields | 14 |
| Divergent, strict | 2 |
| Divergent, lenient | 2 |

The author used `ls` to check that this machine has no `~/.codex/agentic-loop`.
Codex loops write to the shared `~/.coderails/agentic-loop`. This scan cannot tell Claude loops from Codex loops.

### Duplication

| File | Lines |
| --- | ---: |
| `graph_semantics.py` x3 (`packages/graph-semantics/`, `skills/agentic-loop/scripts/`, `packages/codex/skills/agentic-loop/scripts/`) | 394 each, same content |
| Claude `skills/agentic-loop/scripts` (`graph.py` 135 + `graph_semantics.py` 394) | 529 total |
| Codex `packages/codex/skills/agentic-loop/scripts` (10 files, `graph.py` 244) | 1675 total |

## Pre-committed decision thresholds

The author wrote these thresholds before the measurement results. Each has a minimum sample.

- **(a) Demote a gate.** The gate must have 100 or more `decisions` and a `blocked / decisions` ratio of 10% or more.
  Manually sample 30 or more of its blocks. The rate of substantive corrections must be below 30%.
  Count a correction when the next reply changes content. Do not count a reply that only adds a token or acknowledgement.
  Without the sample rate, the gate cannot qualify for demotion.

  *The user overrode this rule for `confidence_labels` and `verify_loop` on 2026-10-04.
  The two gates became advisory lints without satisfying the rule. See `docs/decisions/2026-10-04-not-in-gate-demotion.md`.
  The rule applies to all other gates. After demotion, `blocked / decisions` falls to about 0 for the two gates. Read `demoted` for advisory counts.*

- **(b) Compact bootstrap manifest.** Compact if a provider adds more than 8192 bytes of SessionStart context.
  This is about 2k tokens for each startup, clear, and compaction.

- **(c) `work_units` / `graph.nodes` RFC.** Sample 20 or more loops with the two nonempty fields.
  The strict count must show 5 or more divergent loops and 25% or more divergence. The lenient count must also show 5 or more divergent loops.

## Findings against the thresholds

- **(a) Undecided.** Only `confidence_labels` satisfies the count and ratio thresholds, with 258 decisions and 75.2% of those decisions blocked.
  Its 5.6% ratio across all checks is below 10%. The `loop_stall_guard` rate is 7.9%, `verify_loop` is 4.3%, and the other rates are below 10%.
  The `loop_dispatch_guard` rate is 23.8%, but it has 21 decisions, below 100.

  No one measured the correction rate. That requires transcript turns, and the script does not read them.
  These data do not show that a gate qualifies. They also do not show that a gate fails the correction condition.
  The Codex `graph_completion_guard` logs blocks only. The data cannot give its block ratio.

- **(b) Below threshold.** Claude adds 6288 bytes (1904 below the limit). Codex adds 225 bytes.
  Codex loads 5089 more bytes on demand, for 5314 total, which is also below the limit.
  No log counts startup, clear, and compaction occurrences. The total bytes across runs are unknown.

  *The owner asked for the manifest on 2026-10-05. See `docs/decisions/2026-10-05-dynamic-context-manifest.md`.
  The initial `bootstrap_bytes` figures were Claude 6288 and Codex 225. After the change, an empty payload gives 258 for each provider.
  With an active loop, Claude gives 499 and Codex gives 486. Those counts come from the fixture loop in `packages/tests/test_context_manifest.py`.*

  *The script's empty payload cannot measure an active loop. The `context` output counts manifest and routing log entries, deduplicated by `event_id`.*

- **(c) Below threshold.** The sample has 2 divergent loops of 14 with the two fields (14.3%) in the strict and lenient checks.
  It falls below the count, share, and sample thresholds (2 < 5, 14.3% < 25%, 14 < 20).
  The sample cannot predict if a larger set will satisfy the threshold.
  This machine has 25 graph-only loops (39 with a graph, 14 with the two fields), the configuration with the highest count.

- **Duplication.** The three `graph_semantics.py` copies have the same 394 lines and the same bytes.
  This measurement has no duplication threshold.

- **Coverage.** The run uses one machine and one user. The scan cannot tell Claude loops from Codex loops.
  The logs are append-only. The script does not sample transcripts or check if `blocked=1` marks a correct block.

## Eval integrity runbook (Phase F)

See [eval integrity procedures](graph-alignment-eval-integrity.md).

## Reproduce

```
python3 scripts/measure_graph_alignment.py --root . --json
python3 scripts/tests/measure_graph_alignment_test.py
```

Telemetry and loop data can change between runs because their sources get more entries.
For eval integrity tests, see [the test commands](graph-alignment-eval-integrity.md#reproduce).

## Stale mkdir lock recovery (runbook)

See [lock recovery](graph-alignment-measurement-notes.md#stale-mkdir-lock-recovery-runbook).

## Typed stop intent and hook state (measurement note)

See [typed Stop data](graph-alignment-measurement-notes.md#typed-stop-intent-and-hook-state-measurement-note).

## Gate counters (measurement note)

See [receipt gate counters](graph-alignment-measurement-notes.md#gate-counters-measurement-note).

## Strict typed config and wiki fail-closed (measurement note)

See [config and wiki checks](graph-alignment-measurement-notes.md#strict-typed-config-and-wiki-fail-closed-measurement-note).

## One attestation parser (measurement note)

See [attestation checks](graph-alignment-measurement-notes.md#one-attestation-parser-measurement-note).

## Typed hook state, verdicts and readiness (measurement note)

See [hook data, verdicts, and readiness](graph-alignment-measurement-notes.md#typed-hook-state-verdicts-and-readiness-measurement-note).

## Stop text retired, shared vocabulary, versioned conversion (measurement note)

See [Stop records and conversion](graph-alignment-measurement-notes.md#stop-text-retired-shared-vocabulary-versioned-conversion-measurement-note).

## Machine-readable graph spec and policy (measurement note)

See [spec and policy measurements](graph-alignment-measurement-notes.md#machine-readable-graph-spec-and-policy-measurement-note).

## Structured dispatch envelope and role assertion (measurement note)

See [dispatch envelope measurements](graph-dispatch-measurement.md).

## Disposition, compat findings and typed worker statuses (measurement note)

See [compatibility and worker status checks](graph-alignment-measurement-notes.md#disposition-compat-findings-and-typed-worker-statuses-measurement-note).
