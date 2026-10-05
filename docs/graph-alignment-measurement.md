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
  *Superseded for `confidence_labels` and `verify_loop` by a user override on 2026-10-04: both are demoted to advisory lints without meeting this rule (`docs/decisions/2026-10-04-not-in-gate-demotion.md`). The rule still governs every other gate. After the demotion `blocked / decisions` for those two gates falls to about 0; use `demoted` instead.*
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

**Signing trust boundary.** Signing detects edits made without the key. It binds the suite hash, the chain head and loop_id/session_id to the signer. It lets a different party who holds only the public key (an `allowed_signers` entry) verify. It does NOT stop a same-user agent, which can read the 0600 key and re-sign. It does NOT detect a rollback to an earlier validly-signed state (the `grading.chain_len` check is the only partial guard). Keys: `$CODERAILS_KEYS_DIR` or `~/.coderails/keys` (`evals_ed25519`, `.pub`, `allowed_signers`, all 0600, created on first sign). Config: `evals:` section, `require_signatures: true` in `.coderails/workflow.config.yaml` (default false) makes unsigned and key-less verification block. Sign rows: `command=sign` (`ok|signed`, `degraded|key_missing`); verify rows: `command=verify` (`ok|verified`, `legacy|legacy_unsigned`, `degraded|key_missing`); refusals keep the existing command names. Counters need no change: `eval_trace_counts` keys on `command|outcome|reason_code` and dedupes by `event_id`.

Rows are deduped at write time per (evals.json sha256, command, outcome, reason_code) and the sink stops growing at 1 MiB, so hook polling does not inflate counters; `smoke-run|ok|frozen` records each freeze.

Behaviour changes to know before paging: `grade-loop` without a sibling `progress.json` (archived or hand-built suites) now refuses `progress_missing` (decision: fail closed on both providers, no bypass); a symlinked or blank-id `progress.json` is refused; a PR-scope eval recorded `pass` whose `cmd` exits non-zero is refused `pass_exit_nonzero` by `smoke-verify`; `smoke-run` after an unrecorded oracle edit refuses `suite_hash_mismatch` (use `post_evals.py amend`). Stop-hook text for a tampered suite prints `reason=<code>`; re-running grade-loop will not clear it.

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
revision in the same atomic write that increments the hook-owned `loop_stop_counts`. Final text is never read: with no
row the Stop blocks with trace `stop_row_missing` (`legacy_text_parse` is no longer emitted). Absent-state grace reads `hook_state.json`
`ordinals.absent_blocked` only; there is no discipline.log fallback any more (`legacy_log_parse` is no longer emitted, the
name stays in `FALLBACKS` so history counts). The Claude hook honours a recorded row only if `graph.py stop` ran after the last user prompt (else trace
`stale_stop_row`). The Codex guard writes the same `stop_row_missing` trace row (command `graph_completion_guard`), so the
ratio covers both providers. Counters live in `scripts/graph_alignment_stops.py` (block codes from `scripts/lib/stop_counters.py`,
which also counts `convert_ok` / `convert_refused_<code>`). Flip condition: a high `stop_row_missing` against `stops_consumed`
over the first few loops means agents are not recording stops; fix the prompt, the hook is already strict. Limit: the Stop
payload has no turn id (unverified), so a recorded row counts only when `graph.py stop` appears in the current turn's
structured Bash tool_use records; `voice_announce` is async and may run after the guard consumed the row (it then says
"may have stalled").

**Reproduce.**

```
python3 scripts/graph_alignment_stops.py --json
python3 hooks/scripts/tests/loop_stall_guard_test.py && python3 hooks/scripts/tests/loop_state_guard_test.py
PYTHONPATH=. python3 -m unittest packages/tests/test_provider_stop_record.py scripts/tests/graph_alignment_stops_test.py
```

## Gate counters (measurement note)

`python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/receipt_counters.py` prints a `gate` object next
to `receipts` and `trust`: `authority_denied`, `approval_requirement_missing`, `max_prs_exceeded`, `action_authority_bad_mode`,
`authority_denied_destructive_shell`, `no_receipt` and `merge_py_receipt_executed`. The hook, `enforce_pr_workflow` and
`scripts/merge.py` all land in the same counters (`denied_`, `advisory_` and `merge_py_` prefixes are stripped).
Baseline: none yet on a real loop (the gates went default-on with this change), so every counter starts at 0.
What to read: `approval_requirement_missing` above 0 means a guarded action's permit verdict omitted its approval requirement and was refused before consuming a receipt. `authority_denied` / `max_prs_exceeded` above 0 mean the authority is refusing actions it should (inspect it
with `authority.py inspect`); `no_receipt` dominating `merge_py_receipt_executed` means owners are not minting receipts
(or the agent is trying unreceipted merges); `action_authority_bad_mode` above 0 means a config typo (treated as enforce).
Wiring `gate_summary` into `measure_graph_alignment.py` itself is a handoff to the lane that owns that file; until then
the stdin CLI above is the supported route.

## Strict typed config and wiki fail-closed (measurement note)

Guarded actions read `.coderails/workflow.config.yaml` through `strict_settings` and deny with `config_rejected`
(trace `action_authority/denied/config_rejected`, `diff-manifest/refused/config_rejected`,
`wiki_taxonomy_gate/failed_closed/config_rejected`). Once the vault is positively identified, a missing or invalid
`wiki.schema.json` also denies (`wiki_taxonomy_gate/failed_closed/wiki_schema_missing|wiki_schema_invalid`). Safety
controls default ON in `config.schema.json`: `sandbox_workers`, `action_authority`, `evals.require_signatures`, and
`diff_manifest` (the latter remains inactive until a policy path is configured). The receipt CLI is shipped for both
providers in this stack. Limits: no config file keeps non-action config consumers inert; `dispatch_mode` is computed in
`plan()` and consumed in Phase 3c; the srt probe checks `npx` and `gh` on PATH, not whether runtime sandbox startup works.

**Reproduce.**

```
python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/receipt_counters.py
PYTHONPATH=. python3 -m unittest hooks/scripts/tests/authority_permits_test.py
python3 scripts/lib/config_counters.py
python3 hooks/scripts/tests/config_strict_test.py && python3 hooks/scripts/tests/wiki_taxonomy_gate_test.py
```

## One attestation parser (measurement note)

`scripts/lib/integrity_attestation.py` replaces two hand-written regex copies (merge.py path and the PreToolUse merge
hook). Each denial under a session writes trace `pr_merge_gate/denied/<attest_code>`; `scripts/lib/state_counters.py`
tallies them. Flip condition: a nonzero `attest_not_bound` with a green daemon means the daemon's description format
drifted from `format_attestation` (the daemon-description test should fail first). Limits: the root-owned daemon is
not wired to the parser (separately installed); `merge.py` itself writes no trace row.

**Reproduce.**

```
python3 scripts/tests/integrity_attestation_test.py
python3 scripts/lib/state_counters.py
```

## Typed hook state, verdicts and readiness (measurement note)

`hook_state.json` (hooks/scripts/lib/hook_state.py) replaces `discipline.log` greps for grace and nudge dedupe:
`hook_state_unreadable` (outcome `missing` | `torn`), `nudge_first` and `nudge_suppressed` are trace rows; `arms[]` records
each absent-state block. `EvalVerdict` blocked completions write `eval_verdict_<status>`; graph readiness writes
`predecessor_pending` / `node_unknown`. All tally with `python3 scripts/lib/state_counters.py` (own module because
`scripts/measure_graph_alignment.py` is at its line limit; integration into that script is a handoff). Flip condition:
`hook_state_unreadable` with outcome `torn` above zero means a state write is failing (grace can no longer release);
`nudge_suppressed` far above `nudge_first` is normal (one nudge per session). Limits: GO verdicts and `state_unreadable`
readiness are not traced; first-Stop `missing` is expected once per unregistered loop session.

**Reproduce.**

```
python3 scripts/lib/state_counters.py
python3 hooks/scripts/tests/hook_state_test.py && python3 hooks/scripts/tests/graph_readiness_test.py
```

## Stop text retired, shared vocabulary, versioned conversion (measurement note)

Neither provider reads final text any more: `loop_stall_guard` and the Codex `graph_completion_guard` release only on a
recorded `stops[]` row, and `voice_announce` takes its category from the same row (async, so it can lose the race to the
guard that consumes the row and then says "may have stalled"). The enum lives once in
`packages/graph-semantics/graph_vocab.py`, materialized byte-for-byte into both script dirs next to `graph_semantics.py`
and `graph_convert.py` by `scripts/installer/files.py` (a list of source/targets pairs, reused by later units).
`graph.py convert` writes trace `convert_ok` / `convert_refused_<code>` to `recovery-trace.jsonl`; `stop_row_missing` and
`stale_stop_row` go to `trace.jsonl`; `python3 scripts/lib/stop_counters.py` tallies all of them (own module because
`scripts/measure_graph_alignment.py` is at its line limit; folding it in is a handoff). Flip condition: any
`convert_refused_active_wave_ambiguous` means a loop was upgraded mid-wave (finish or recover the wave first); a
sustained `stop_row_missing` means the prompt is not teaching `graph.py stop`. Limits: the Stop payload has no turn id
(unverified), so "recorded this turn" is read from structured Bash tool_use records; `convert` refuses rather than
guesses, so an in-flight wave on a pre-history file needs manual recovery.

**Reproduce.**

```
python3 scripts/lib/stop_counters.py
python3 hooks/scripts/tests/graph_convert_test.py && python3 hooks/scripts/tests/loop_stall_guard_test.py
PYTHONPATH=. python3 -m unittest packages.tests.test_provider_stop_record packages.tests.test_provider_graph_lifecycle
```

## Machine-readable graph spec and policy (measurement note)

The node table that only lived in prose is now data: `packages/graph-semantics/graph-spec.yaml` (nodes, requirements,
phases, instruction sources, machine skip predicates) and `policy.yaml` (thresholds, retry bounds, default graph profile),
JSON-syntax YAML read with `json.loads`, validated and expanded by the shared `graph_spec.py`, and materialized
byte-for-byte into both script dirs by `scripts/installer/files.py`. Both providers refuse every load whose graph omits a
spec edge between two nodes it holds (`spec_edge_missing`); a graph built by `graph.py instantiate` is stamped with
`graph.spec_sha256` and also refuses unknown nodes, missing spec nodes and a changed spec. `add-unit` and `plan` take
wiring, instruction sources and skip thresholds from the spec (the old `TARGETS` table and `before_freeze` regex are
gone), and `scripts/gen_graph_docs.py --check` keeps the execution-graph table, its mermaid diagram and the threshold block
generated from the same files. Rows go to `recovery-trace.jsonl` (`load/refused/spec_*`, `instantiate/<status>/instantiate_ok|
instantiate_noop|instantiate_refused_*`, `plan/reported/skip_when_met`); `python3 scripts/lib/spec_counters.py` tallies them
(own module because `scripts/measure_graph_alignment.py` is at its line limit; folding it in is a handoff). Flip
condition: a sustained `spec_edge_missing` after the first week means hand-built or foreign graphs are loading; any
`spec_hash_mismatch` means a spec edit landed while a stamped loop was live. `skip_when_met` against actual skipped nodes
shows whether the machine predicate matches what orchestrators record. Limits: the default profile is `full`; explicitly choosing
`units-only` omits the preparation and lifecycle nodes. Join inputs are enforced on stamped graphs only (`spec_join_inputs`)
and a stamp below the policy profile is `spec_profile_downgrade`; unstamped graphs and a deleted stamp stay the weaker check;
`CODERAILS_GRAPH_SPEC=off` disables the check;
judgement skip rules stay prose; the spec files are plain same-user files, so this is drift detection, not tamper evidence.

**Reproduce.**

```
python3 scripts/lib/spec_counters.py
python3 scripts/gen_graph_docs.py --check && python3 scripts/tests/gen_graph_docs_test.py
PYTHONPATH=. python3 -m unittest packages.tests.test_graph_spec
```

## Structured dispatch envelope and role assertion (measurement note)

See [dispatch envelope measurements](graph-dispatch-measurement.md).

## Disposition, compat findings and typed worker statuses (measurement note)

Row 7 gives the disposition fields a code reader. `graph.py add-unit --disposition clean-break|preserve-compat
[--named-blocker X --removal-ticket Y]` validates through one function in `packages/graph-semantics/graph_vocab.py`
(preserve-compat needs both non-blank, clean-break neither) and stores `work_units[u].disposition`, which the dispatch
contract already carried; `disposition-audit` and both providers' completion gates re-check a hand-edited state. The
review artifact gains a second typed line `<!-- coderails-compat-findings v1 pr=N head_sha=S count=K disposition=D -->`
(`post_review.py compat-line`); `merge.py` refuses `clean-break` with `K > 0` (`compat_findings_nonzero`), a malformed
line (`compat_findings_malformed`), and passes an artifact without the line. The root-owned daemon's v1 marker line is
byte-identical. Row 22 puts `worker_status.prepare()` in front of the untouched core in both `record_wave` paths: a
result with a `status` key is validated or the whole report is rejected (`worker_status_<code>`), a valid one is recorded
in `worker_statuses[]`, spends one retry and writes one typed stop row; a `done` result for a dispatch with
`final_report_required` needs a valid `final_report` (`final_report_invalid`).

What to count: `python3 scripts/lib/worker_counters.py` tallies `worker_status_<reason>` / `final_report_invalid`
(refusals), `worker_status_<status>` / `final_report_recorded` (accepted) from `recovery-trace.jsonl`, and
`pending_statuses` from `progress.json`. Disposition refusals are `add-unit/refused/add_unit_refused_disposition` rows.
Flip condition: refusal codes above zero mean workers return unshaped results (fix the worker prompt, not the gate);
`pending_statuses` that never falls means typed stops were recorded but never followed up;
three typed stops on one node exhaust its retries, so a high `worker_status_*` per node means the unit needs a human
decision up front. Negative controls: delete the `prepare()` call from `record_wave`, skip the preserve-compat pair
check, ignore the compat line in `merge.py`, drop the `final_report_required` branch, or touch `graph_semantics.py`; each
fails its row in `packages/tests/test_provider_disposition.py`, `packages/tests/test_provider_worker_status.py`,
`scripts/tests/compat_findings_test.py` or `hooks/scripts/tests/worker_status_test.py`. Limits: the compat count and
disposition are the reviewer's judgement (an observable-requirement limit, not a measurement), the status spends a retry
because the core has no needs-a-human outcome, `final_report` shape is checked and its truth is not, and merge refusals
leave no trace row (merge.py has no loop session); `measure_graph_alignment.py` does not load `worker_counters`
(handoff H1).

**Reproduce.**

```
python3 scripts/lib/worker_counters.py
python3 hooks/scripts/tests/worker_status_test.py
PYTHONPATH=. python3 -m unittest packages.tests.test_provider_disposition packages.tests.test_provider_worker_status scripts.tests.compat_findings_test
```
