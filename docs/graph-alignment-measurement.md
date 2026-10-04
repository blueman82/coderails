# Graph-alignment measurement (plan section 28)

Post-migration evidence only. This document collects numbers; it does not recommend or implement any
behavioural change, and it does not merge `work_units` into `graph.nodes`.

## Method

Produced by `python3 scripts/measure_graph_alignment.py --root . --json` (stdlib only, read-only, prints
counts and paths, never log-message, transcript or prompt content). Run against `origin/main` at
`04b0eef7f089aebd17ab09ea1464d65b46380d32` on 2026-10-03T19:27+01:00, on the author's workstation, so the
telemetry and loop-state figures describe that one machine and not a fleet.

| Key | Source | Rule |
| --- | --- | --- |
| `hook_counts` | `hooks/hooks.json`, `packages/codex/hooks/hooks.json` | Commands registered per event type. |
| `bootstrap_bytes` | `hooks/scripts/inject_bootstrap.py`, `packages/codex/hooks/scripts/inject_bootstrap.py` | Each hook is executed with an empty `{}` payload; the figure is the UTF-8 size of its `additionalContext`. No cwd or session means no legacy-config nudge and no Codex graph-resume text, so this is the static floor. |
| `gate_blocks` | `~/.claude/discipline.log` (override `CLAUDE_DISCIPLINE_LOG`); `~/.coderails/codex/discipline.log` (overrides `PLUGIN_DATA`, `CODERAILS_DISCIPLINE_LOG`) | Lines with `hook=<name>`. `total` = every line naming the gate; `decisions` = the subset carrying a `blocked=0\|1` field; `blocked`, `would_block`, `warned` = lines with that flag `=1`. Missing log = zeros. |
| `graph_vs_work_units` | `<root>/*/*/progress.json` for `CLAUDE_AGENTIC_LOOP_DIR`/`CODERAILS_AGENTIC_LOOP_DIR` (default `~/.coderails/agentic-loop`), `~/.claude/agentic-loop`, `~/.codex/agentic-loop`; de-duplicated by real path | Divergence is counted only for loops having both non-empty `work_units` and `graph.nodes`: all work_units terminal XOR all graph nodes in `done`/`skipped`. Strict: work_unit terminal means exactly `done` or `dropped` (the `loop_completion.py` rule). Lenient: statuses merely starting with `done`/`dropped` also count (many real units carry free-text statuses). |
| `duplication` | line counts of the three `graph_semantics.py` copies and the two provider `agentic-loop/scripts` directories | Content identity by SHA-256. |

Known measurement limits: the discipline log is append-only for the whole life of the machine (Claude log
starts 2026-08-04, Codex log spans 2026-08-20 to 2026-09-17), and the Claude figures include this session's
own hook activity at run time. `blocked=1` says a gate fired, not that the block was correct or useful.

## Measured data (verbatim from the run)

### Hook counts

| Event | Claude | Codex |
| --- | ---: | ---: |
| SessionStart | 2 | 1 |
| UserPromptSubmit | 2 | 2 |
| PreToolUse | 11 | 8 |
| PostToolUse | 1 | 1 |
| Stop | 8 | 3 |
| SubagentStop | 3 | 1 |
| **Total** | **27** | **16** |

### Bootstrap bytes (SessionStart: startup, clear, compact; Codex also resume)

| Provider | Injected bytes | Notes |
| --- | ---: | --- |
| Claude | 6288 | Wrapper plus full `skills/using-coderails/SKILL.md` (6057 bytes). |
| Codex | 225 | A pointer telling the agent to load `coderails-codex:using-coderails`; the skill itself (5089 bytes) is deferred to a later agent tool call, not injected, so it is not in the 225. Registered `additionalContextLimit` is 1200. |

### Gate telemetry

Claude log: 15394 hook lines, 2026-08-04T19:36:33+01:00 to 2026-10-03T19:26:31+01:00.

| Gate | total | decisions | blocked | would_block | warned | blocked / decisions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| confidence_labels | 3712 | 258 | 194 | 322 | 64 | 75.2% |
| verify_loop | 3546 | 3546 | 153 | 6 | 6 | 4.3% |
| loop_stall_guard | 495 | 469 | 37 | 0 | 0 | 7.9% |
| loop_dispatch_guard | 21 | 21 | 5 | 0 | 0 | 23.8% |
| crack_on_prose_gate | 103 | 103 | 5 | 0 | 0 | 4.9% |
| loop_state_guard | 780 | 780 | 6 | 0 | 0 | 0.8% |
| voice_announce | 448 | 309 | 0 | 0 | 0 | 0.0% |
| agent_only_gate, agent_model_routing_nudge, crack_on_gate, enforce_pr_workflow, no_edit_on_main, offload_push_guard, unregistered_loop_guard | 7 gates, 6289 lines combined | 0 | 0 | 0 | 0 | n/a (no `blocked=` field logged) |

`confidence_labels` writes a bookkeeping line on every evaluation (3453 lines: 769 Stop plus 2684
SubagentStop) and a decision line only when text of at least 200 characters lacks a label. Against all
evaluations, 194 blocks is 5.6%. The 75.2% figure is conditional on a missing label already having been
detected.

Codex log: 117 hook lines, 2026-08-20T11:40:26+01:00 to 2026-09-17T11:30:25+01:00.

| Gate | total | decisions | blocked | would_block | warned | blocked / decisions |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| graph_completion_guard | 114 | 114 | 114 | 0 | 0 | 100.0% (logs only when it blocks, so no pass denominator) |
| loop_dispatch_guard | 2 | 2 | 0 | 0 | 0 | 0.0% |
| no_edit_on_main | 1 | 0 | 0 | 0 | 0 | n/a |

### Loop state: graph versus work_units

| Measure | Count |
| --- | ---: |
| Loops scanned (`progress.json`) | 42 |
| With non-empty `work_units` | 19 |
| With `graph.nodes` | 39 |
| With both | 14 |
| Divergent, strict | 2 |
| Divergent, lenient | 2 |

`~/.codex/agentic-loop` does not exist on this machine (verified by `ls`); Codex loops write to the shared
`~/.coderails/agentic-loop`, so Claude and Codex loops are not separable in this scan.

### Duplication

| File | Lines |
| --- | ---: |
| `graph_semantics.py` x3 (`packages/graph-semantics/`, `skills/agentic-loop/scripts/`, `packages/codex/skills/agentic-loop/scripts/`) | 394 each, 1 distinct content |
| Claude `skills/agentic-loop/scripts` (`graph.py` 135 + `graph_semantics.py` 394) | 529 total |
| Codex `packages/codex/skills/agentic-loop/scripts` (10 files, `graph.py` 244) | 1675 total |

## Pre-committed decision thresholds

Written before interpreting the data above. Each needs a minimum sample so a small count cannot trigger it.

- **(a) Demote a gate.** A gate is a demotion candidate only if all hold: at least 100 `decisions`;
  `blocked / decisions` of at least 10%; and, on a hand-sampled set of at least 30 of its blocks, a
  real-fix rate below 30%, where a real fix means the next turn changed substance rather than appending a
  token or acknowledgement. Without the sampled rate, no gate may be called demotable.
- **(b) Compact bootstrap manifest.** Justified if a provider's injected SessionStart context exceeds
  8192 bytes (roughly 2k tokens, paid on every startup, clear and compaction).
- **(c) `work_units` / `graph.nodes` RFC.** Justified if, among at least 20 loops carrying both, at least
  5 diverge (strict) and divergence is at least 25% of those loops, with the lenient count also at least 5.

## Findings against the thresholds

- **(a) Not decidable.** The ratio and volume tests are crossed only by `confidence_labels`
  (258 decisions, 75.2%; 5.6% of all evaluations, which would not cross 10%). `loop_stall_guard` (7.9%),
  `verify_loop` (4.3%) and the rest fall below 10%; `loop_dispatch_guard` (23.8%) has 21 decisions, under
  the 100 floor. The real-fix rate was not measured: it needs reading transcript turns, which this script
  deliberately never does. So no gate is shown to meet the demotion criteria and none is shown to fail on
  the real-fix leg; the data is too thin to decide. Codex `graph_completion_guard` records blocks only, so
  its block ratio cannot be computed at all.
- **(b) Not crossed.** Claude injects 6288 bytes (1904 under the line); Codex injects 225 (5089 more are
  loaded on demand, 5314 combined, also under). The multiplier (how many startup, clear and compaction
  events fire) is not in any log, so total injected volume is unmeasured.
- **(c) Not crossed, and the sample is too small to say it never would be.** 2 divergent of 14 loops with
  both (14.3%), strict and lenient agreeing. That fails the count (2 < 5), the share (14.3% < 25%) and the
  sample floor (14 < 20). Unrelated to the thresholds: 25 loops (39 with a graph, 14 with both) have a graph and no work_units, so
  graph-only is already the common shape on this machine.
- **Duplication.** The three `graph_semantics.py` copies are byte-identical (394 lines each), so there is
  no drift between them today. No threshold was set for duplication, so none is evaluated.
- **Not covered.** Single machine, single user, mixed Claude and Codex loops that cannot be separated,
  logs not rotated, no transcript sampling, and `blocked=1` counts not validated as correct blocks.

## Reproduce

```
python3 scripts/measure_graph_alignment.py --root . --json
python3 scripts/tests/measure_graph_alignment_test.py
```

Telemetry and loop-state numbers will differ on re-run because both sources keep growing.

## Stale mkdir lock recovery (runbook)

Before this change a SIGKILLed hook left `progress.json.lock` (or `verification-ceiling/*.count.lock`) behind
forever: every later `atomic_progress_update` returned `False` and the verification ceiling denied every command.
Both sites now take the lock through `hooks/scripts/lib/dir_lock.py`.

**Policy.** The lock dir holds `owner` = `{pid, start, ts}` (`start` is `ps -o lstart=`). A lock is stolen only when
the owner is provably dead: `os.kill(pid, 0)` raises `ProcessLookupError`, or the pid is alive with a different
start time (pid reuse). `PermissionError` means alive and never steals. An absent, empty or torn owner file is not
dead on its own (it is the mkdir-then-write window); it is stolen only when the lock dir's mtime is older than
`CLAUDE_LOCK_STALE_S` (default 60). An old lock with a live owner is never stolen. A future mtime (clock skew)
counts as young. The steal is `os.rename(lock, lock.stale.<pid>.<uuid>)`: one racing stealer wins, losers retry
`mkdir`; the renamed owner is rechecked against the one judged, and a mismatch is given back as `lock_busy`.
Release removes the lock only if `owner.pid` is the caller's.

**Reason codes** (appended as non-authoritative rows `{ts, event_id, reason, schema:"lock_event",
non_authoritative:true}` to `lock-events.jsonl` beside the lock; fail-open, a write failure never changes the
lock result):

| Code | Meaning |
| --- | --- |
| `lock_stolen_dead_owner` | Owner pid gone or reused; lock stolen. |
| `lock_stolen_age` | Owner unreadable and lock older than the bound; stolen. |
| `lock_busy` | Retry budget exhausted against a live, young or ambiguous lock. |

`python3 scripts/measure_graph_alignment.py --root . --json` reports `lock_events` counts per code, deduped by
`event_id` across all loop-state roots.

**Manual recovery** (only if a lock never clears): confirm the owner is gone with
`cat <lock>/owner; ps -p <pid>`, then move the directory aside (`mv <lock> /tmp/trash/`); do not delete a lock
whose pid is alive.

**Known ceiling.** If a new holder wins between the steal's judgement and its rename, and a third process takes the
vacated name before the rename-back, two holders can briefly coexist. The Codex copy
(`packages/codex/hooks/scripts/verification_volume_ceiling.py`, `acquire_lock`) still has the bare mkdir lock; it
is a named follow-up because it has its own `lib/` and would need a vendored copy.

**Reproduce.**

```
python3 -m unittest hooks.scripts.tests.dir_lock_test hooks.scripts.tests.lock_recovery_test
python3 -m unittest scripts.tests.measure_graph_alignment_test
```
