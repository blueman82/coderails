# Graph-alignment measurement (plan section 28)

This document records post-migration measurements. It makes no behaviour
recommendation or change. It keeps `work_units` separate from `graph.nodes`.

## Method

The command was `python3 scripts/measure_graph_alignment.py --root . --json`.
It used only the Python standard library. It read data and printed counts
and paths. It did not print log messages, transcripts, or prompt content.

The run used `origin/main` at `04b0eef7f089aebd17ab09ea1464d65b46380d32`.
It ran on the author's workstation on 2026-10-03T19:27+01:00. The telemetry
and loop-state figures describe that machine.

The command measured these keys:

- `hook_counts`: It counted commands per event type in `hooks/hooks.json`
  and `packages/codex/hooks/hooks.json`.
- `bootstrap_bytes`: It ran each provider's `inject_bootstrap.py` hook with
  an empty `{}` payload. It counted the UTF-8 bytes in `additionalContext`.
  No cwd or session was set. Thus, the figure excludes the legacy-config
  nudge and Codex graph-resume text. It is the static floor.
- `gate_blocks`: It read `~/.claude/discipline.log` and
  `~/.coderails/codex/discipline.log`. `CLAUDE_DISCIPLINE_LOG` overrides
  the Claude path. `PLUGIN_DATA` and `CODERAILS_DISCIPLINE_LOG` override
  the Codex path. A row needs `hook=<name>`. `total` counts all rows for
  the gate. `decisions` counts rows with `blocked=0` or `blocked=1`.
  `blocked`, `would_block`, and `warned` count rows where that flag is `1`.
  A missing log gives zero counts.
- `graph_vs_work_units`: It scanned `<root>/*/*/progress.json` under
  `CLAUDE_AGENTIC_LOOP_DIR` and `CODERAILS_AGENTIC_LOOP_DIR`. Their default
  is `~/.coderails/agentic-loop`. It also scanned `~/.claude/agentic-loop`
  and `~/.codex/agentic-loop`. Real paths removed duplicate files. A loop
  entered the comparison only when it had non-empty `work_units` and
  `graph.nodes`. The work-unit side is terminal when all units are terminal.
  The graph side is terminal when all nodes are `done` or `skipped`.
  Divergence means exactly one side is terminal. The strict count treats
  only exact `done` or `dropped` work-unit status as terminal. This is the
  `loop_completion.py` rule.
  The lenient count also accepts statuses that start with those words.
  Many real units use free-text statuses.
- `duplication`: It counted lines in three `graph_semantics.py` copies and
  both provider `agentic-loop/scripts` directories. It used SHA-256 to
  test content identity.

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
| crack_on_prose_gate (retired; historical) | 103 | 103 | 5 | 0 | 0 | 4.9% |
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
  *A user override on 2026-10-04 superseded this rule for
  `confidence_labels` and `verify_loop`. Both became advisory lints without
  meeting the threshold. See
  `docs/decisions/2026-10-04-not-in-gate-demotion.md`. The rule still
  applies to other gates. After demotion, `blocked / decisions` for those
  two gates is about 0. Use `demoted` to measure them.*
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
  *Superseded 2026-10-05 (`docs/decisions/2026-10-05-dynamic-context-manifest.md`): the manifest was built anyway.
  `bootstrap_bytes` before: Claude 6288, Codex 225. After, with an empty payload (static floor): 258 and 258;
  with an active loop: Claude 499, Codex 486 (measured by running each hook on the fixture loop used in
  `packages/tests/test_context_manifest.py`; the script's empty payload cannot show the loop-active size).
  Manifest and route trace rows are counted under `context` in the script output, deduped by event_id.*
- **(c) Not crossed, and the sample is too small to say it never would be.** 2 divergent of 14 loops with
  both (14.3%), strict and lenient agreeing. That fails the count (2 < 5), the share (14.3% < 25%) and the
  sample floor (14 < 20). Unrelated to the thresholds: 25 loops (39 with a graph, 14 with both) have a graph and no work_units, so
  graph-only is already the common shape on this machine.
- **Duplication.** The three `graph_semantics.py` copies are byte-identical (394 lines each), so there is
  no drift between them today. No threshold was set for duplication, so none is evaluated.
- **Not covered.** Single machine, single user, mixed Claude and Codex loops that cannot be separated,
  logs not rotated, no transcript sampling, and `blocked=1` counts not validated as correct blocks.

## Eval integrity runbook (Phase F)

Sink: `eval_trace.jsonl` beside the `evals.json` it describes (loop dir for loop scope; wherever the file lives at PR
scope, so it is not loop-safe). Rows are append-only, fail-open and NON-AUTHORITATIVE: nothing reads them to decide a
grade. Fields: `schema_version, session_id, loop_id, timestamp, command, outcome, reason_code, event_id, inputs`
(`inputs` are sha256 only). Every refusal also prints `reason=<code>` to stderr. Counters:
`python3 scripts/measure_graph_alignment.py --root . --json [--eval-trace <PR-scope file>]` reports
`eval_trace` events deduped by `event_id`.

Query: `jq -r 'select(.outcome!="ok")|[.command,.outcome,.reason_code]|@tsv' <loop dir>/eval_trace.jsonl | sort | uniq -c`

| reason_code | symptom | remediation |
|---|---|---|
| `legacy_unhashed` | suite has no `frozen_hash`; graded (outcome `legacy`) | none required; re-freeze with `post_evals.py smoke-run` before any grade to get tamper evidence |
| `suite_hash_mismatch` | oracle text differs from `frozen_hash` or the last amendment | revert the edit, or re-apply it with `post_evals.py amend ...` then regrade |
| `integrity_stripped` | `frozen_hash` deleted from a suite graded with one (reader shows `TAMPERED:integrity_stripped`) | restore the file; deleting hash and tombstones together is NOT detectable |
| `legacy_unsigned` | frozen suite carries no `signature` and was never signed (outcome `legacy`, command `verify`/`loop-evals-read`) | none required; re-freeze a new suite with `post_evals.py smoke-run` under a key to get a signature |
| `signature_invalid` | signature does not verify, signs a different payload (suite head, chain head/length, loop_id, session_id) or the chain was truncated and re-hashed | restore the file; amendments must go through `post_evals.py amend`, which re-signs |
| `signer_unknown` | signature is cryptographically valid but its key is not in `allowed_signers` | add the signer's public key line to `~/.coderails/keys/allowed_signers` only if you trust it; otherwise the suite was signed by another key |
| `signature_missing` | `signature` removed from a suite with `grading.signed: true`, listed in this host's `signed_suites` ledger (keys dir; catches a pre-grade strip + swap on the signing host only) or under `evals.require_signatures: true` (reader shows `TAMPERED:signature_missing`) | restore the file; `amend` refuses to re-sign a stripped suite |
| `key_missing` | no ssh-keygen or no `allowed_signers` where the suite is verified (outcome `degraded`, non-blocking; command `sign` when freezing unsigned); blocks when `evals.require_signatures: true`; `grade-loop` and `amend` refuse (`key_missing`) to re-sign a signature they could not verify, so a forged or foreign signature is never laundered into a local one | install OpenSSH or copy the public `allowed_signers` to `$CODERAILS_KEYS_DIR`/`~/.coderails/keys` |
| `key_perms` | private key `evals_ed25519` is group/world accessible | `chmod 600 ~/.coderails/keys/evals_ed25519` |
| `sign_failed` | ssh-keygen could not create a key or sign | run `ssh-keygen -Y sign` by hand to see the error |
| `cmd_env` | loop-scope `cmd` exited 126/127/>=128 at grade time | fix the command's tooling or cwd (grade-loop runs it in the caller's cwd, 10s cap) |
| `chain_broken` | `amendment_chain` entry edited, reordered or chain without `frozen_hash` | restore the file from the loop dir backup; do not hand-edit the chain |
| `chain_truncated` | fewer chain entries than `grading.chain_len` | restore the removed entries; regrading after truncation is not detectable |
| `progress_missing` / `progress_unparseable` | `progress.json` absent, invalid, or lacks `session_id`/`loop_id` | restore `progress.json` beside `evals.json`; there is no bypass flag |
| `progress_foreign` | suite stamped with different ids than `progress.json` | the suite belongs to another loop; regenerate it for this loop |
| `control_passes` | a loop-scope `negative_control` exited 0 | rewrite the control so it fails on the unmet state |
| `control_env` | control exited 126/127/>=128 (missing tool, timeout) | fix the control's tooling or cwd |
| `pass_exit_nonzero` | gate: eval recorded `pass` but `cmd` exits non-zero | the PASS is wrong or the build regressed; re-grade |
| `fixture_formula_not_in_cmd` | `fixtures.formula` is not the literal tail of `cmd` | make the fixtures run the real checker text |

**Signing trust boundary.** A signature detects an edit made without the
signing key. It binds the suite hash, chain head, loop ID, and session ID to
the signer. A party with an `allowed_signers` public key can verify it.

The signature does not stop an agent with the same user access. That agent
can read the mode-0600 key and sign a changed suite. A signature also does
not detect a rollback to an earlier validly signed state. The
`grading.chain_len` check gives only partial rollback protection.

The keys live in `$CODERAILS_KEYS_DIR` or `~/.coderails/keys`:
`evals_ed25519`, its `.pub` file, and `allowed_signers`. They use mode 0600
and are created on first sign. In `.coderails/workflow.config.yaml`, set
`evals.require_signatures: true` to block unsigned or keyless verification.
The default is false.

Trace rows for signing use `command=sign` with `ok|signed` or
`degraded|key_missing`. Verification uses `command=verify` with
`ok|verified`, `legacy|legacy_unsigned`, or `degraded|key_missing`.
Refusals keep their existing command names. `eval_trace_counts` groups by
`command|outcome|reason_code` and deduplicates by `event_id`.

Rows are deduplicated at write time by `evals.json` SHA-256, command,
outcome, and reason code. The sink stops growing at 1 MiB. These limits
prevent hook polling from inflating counters. Each freeze records
`smoke-run|ok|frozen`.

`grade-loop` rejects an archived or hand-built suite without a sibling
`progress.json` as `progress_missing`. Both providers fail closed, with no
bypass. It also rejects a symlinked `progress.json` or one with a blank ID.
`smoke-verify` rejects `pass_exit_nonzero` when a PR eval says `pass` but
its command exits nonzero. After an unrecorded oracle edit, `smoke-run`
rejects `suite_hash_mismatch`. Use `post_evals.py amend` for that change.
The Stop hook prints `reason=<code>` for a changed suite. Running
`grade-loop` again does not clear the refusal.

Also traced as `outcome=legacy`: `legacy_progress_schema` (progress.json schema_version != 3, still allowed).

## Reproduce

```
python3 scripts/measure_graph_alignment.py --root . --json
python3 scripts/tests/measure_graph_alignment_test.py
```

Telemetry and loop-state numbers will differ on re-run because both sources keep growing.

Eval integrity (no `timeout`, it does not exist on macOS):

```
python3 -m unittest hooks.scripts.tests.eval_integrity_test hooks.scripts.tests.post_evals_grading_test scripts.tests.measure_graph_alignment_test
PYTHONPATH=. python3 -m unittest packages/tests/test_codex_grading_encoding.py
```

## Stale mkdir lock recovery (runbook)

Before this change a SIGKILLed hook left `progress.json.lock` (or `verification-ceiling/*.count.lock`) behind
forever: every later `atomic_progress_update` returned `False` and the verification ceiling denied every command.
Both sites now take the lock through `hooks/scripts/lib/dir_lock.py`.

**Policy.** The lock dir holds `owner` = `{pid, host, start, ts}` (`start` is `ps -o lstart=`). A lock is stolen only when
the owner is provably dead: `os.kill(pid, 0)` raises `ProcessLookupError`, or the pid is alive with a different
start time (pid reuse). `PermissionError` means alive and never steals. An absent, empty or torn owner file is not
dead on its own (it is the mkdir-then-write window); it is stolen only when the lock dir's mtime is older than
`CLAUDE_LOCK_STALE_S` (default 60). An old lock with a live owner is never stolen. A future mtime (clock skew)
counts as young. The steal is `os.rename(lock, lock.stale.<pid>.<uuid>)`: one racing stealer wins, losers retry
`mkdir`; the renamed owner is rechecked against the one judged, and a mismatch is given back as `lock_busy`.
Release removes the lock only if `owner.pid` is the caller's.

**Reason codes** (appended as non-authoritative rows `{ts, event_id, reason, schema:"lock_event",
non_authoritative:true, lock, owner_pid, pid}` (lock path, judged owner pid or null, acquirer pid) to `lock-events.jsonl` beside the lock; fail-open, a write failure never changes the
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
vacated name before the rename-back, two holders can briefly coexist. A pid recorded by a different `host`
is never judged by `kill -0` (shared state dirs over NFS or containers); such a lock is stolen only by age.
Same-second pid reuse with an identical `lstart` is not detectable. The Codex hook uses a byte-identical vendored
copy (`packages/codex/hooks/scripts/lib/dir_lock.py`, guarded by `dir_lock_test`); its events land in
`$PLUGIN_DATA/verification-ceiling/lock-events.jsonl`, which the measurement script does not yet scan.

**Reproduce.**

```
python3 -m unittest hooks.scripts.tests.dir_lock_test hooks.scripts.tests.lock_recovery_test
python3 packages/tests/test_codex_ceiling_lock.py
python3 -m unittest scripts.tests.measure_graph_alignment_test
```

## Typed stop intent and hook state (measurement note)

`graph.py stop` records a `progress.stops[]` row; `loop_stall_guard` consumes the newest unconsumed row at the current
revision in the same atomic write that increments the hook-owned `loop_stop_counts`, and falls back to the final
anchored `LOOP-STOP:` line (trace `legacy_text_parse`). Absent-state grace reads `hook_state.json`
`ordinals.absent_blocked`, falling back to the discipline.log regex (trace `legacy_log_parse`). The Claude hook honours a recorded row only if `graph.py stop` ran after the last user prompt (else trace
`stale_stop_row`). The Codex guard writes the same `legacy_text_parse` trace row (command `graph_completion_guard`), so the
ratio covers both providers; before this change Codex fallbacks appeared only in discipline.log and were not counted.
Counters live in `scripts/graph_alignment_stops.py`. Flip condition: if `legacy_text_parse` still dominates `stops_consumed` over the
first few loops, agents are not recording stops; tighten the parse and block text-only stops instead.

**Reproduce.**

```
python3 scripts/graph_alignment_stops.py --json
python3 hooks/scripts/tests/loop_stall_guard_test.py && python3 hooks/scripts/tests/loop_state_guard_test.py
PYTHONPATH=. python3 -m unittest packages/tests/test_provider_stop_record.py scripts/tests/graph_alignment_stops_test.py
```
