# Loop state — `progress.json` reference

Use this file with "Context-window persistence" in SKILL.md.
SKILL.md tells you to start the loop file with `graph.py start` in Phase -2 and get its path from the helper.
It also tells you to update the file at phase boundaries and read it again to find your position.
Use the fields, lifecycle, and ownership rules below to write or repair it.

## Contents

- [Path and keying](#path-and-keying)
- [Fields](#fields)
- [Lifecycle](#lifecycle)
- [Recency — a prior `complete` and the next loop](#recency)
- [Concurrent loops in one directory](#concurrent-loops-in-one-directory)
- [Honest boundary](#honest-boundary)
- [Siblings in the same directory](#siblings-in-the-same-directory)

## Path and keying

Keep one `progress.json` at the path from `python3 hooks/scripts/lib/agentic_loop_path.py`.
The path is external to the code repo.
Its key uses the repo, or cwd if there is no repo, and this session’s ID.
It stays the same across restart and compaction.
It does not change the base a worker uses.
Different sessions in the same directory get different files.

Use the helper in Phase -2 to get the path.
Do not calculate the path.
If you give no `session_id` argument, the helper reads `$CLAUDE_CODE_SESSION_ID` from the Bash tool call.

Each phase boundary replaces the JSON object.
Read the full file to find the current position.
Do not use an append log (`.jsonl`).
That would need replay and could have a torn last line after a crash.

## Fields

| Field | Description |
|---|---|
| `schema_version` | Use `3`. The graph refuses legacy, missing, or malformed schemas. There is no schema-2 reader or other writer. |
| `proof_disposition` | If there is no `proof.json`, save the cause with `graph.py record-proof-disposition`. For an owned loop with no executable surface, save `"none: <nonblank reason>"`. Missing or other values block the end of the loop. Check a proof file independently if it is available. |
| `session_id` | The session ID. The guard compares it with the file path. |
| `loop_id` | A unique non-blank ID for this loop. Keep it in mid-loop writes. Use a new value to re-arm for a new loop. Frozen evals for dispatch bind `session_id` and `loop_id`. |
| `revision` | A positive integer that starts at `1` and increases with graph operations. Envelopes for dispatch bind the active revision. Frozen dispatch evals bind only session and loop. Neutral grading binds the revision at loop end. |
| `status` | `in-progress` → `complete` (see Lifecycle). The `graph.py start` command writes `in-progress`. |
| `authorising_prompt_raw` | The authorisation envelope, verbatim. |
| `work_units` | JSON object keyed by unit ID. Each entry has a `status`. Use `pending`, `in-progress`, or `blocked` (with `blockedBy`) for work in flight. Only `done` and `dropped` are terminal. For `dropped`, include `dropped_reason`. Do not use the retired values `merged`, `complete`, or synonyms. |
| `graph` | `{nodes, edges, joins, active_wave, hard_stop}`. Nodes have stable IDs, registry labels, matching status and outcome, retry limits, `evidence` arrays, and `respawn: {generation, intent}`. Edges name nodes in the graph. All-input joins have `id`, `inputs`, and `released`. The native adapter owns transcript cursors and wave history. |
| `loop_stop_counts` | The hook owns these category counts for Phase 13: `{hard-stop, approval-gate, awaiting-input, complete}`. |
| `disposition` | The work unit’s retirement record. The dispatch contract includes it. See the rules below. |
| `named_blocker` | The `disposition.named_blocker` value must be non-blank for `preserve-compat`. Name the consumer that uses the previous path and makes it necessary to keep the path. Do not use this field for `clean-break`. |
| `removal_ticket` | The `disposition.removal_ticket` value must be non-blank for `preserve-compat`. The ticket is for deferred removal. Do not use this field for `clean-break`. If a manual edit drops one of the two fields, `graph.py disposition-audit <state>` exits 1. The loop cannot complete. |
| `decisions_absorbed` | Chronological typed, hash-chained rows. See the rules below. |
| `worker_statuses` | Only `graph.py record-wave` writes this array. Each validated `NEEDS_DECISION`, `OUTSIDE_SCOPE`, or `IRREVERSIBLE_ACTION` status gives one `{seq, node, wave_id, status, payload, decision_pending, revision}` object. The same locked write saves its typed stop row. The `decision_pending` field is `true` until `graph.py record-decision --worker-status-seq <seq>` resolves it. |
| `final_reports` | Only `graph.py record-wave` writes this object keyed by node ID. It holds a validated `final_report {claims, did_not_verify}` from a worker’s `done` result. It is mandatory if the dispatch record has `final_report_required`. |
| `completed_marker` | Number of agentic-loop loops completed in this session. Teardown increases it. The `graph.py start` command keeps it when re-arming a completed loop. |
| `last_updated` | The graph updates this field at each phase boundary. |
| `state_minor` | The schema 3 layout version. It is an integer with default 0 if missing. The current value is 3. See conversion rules below. |

**Retirement records.**
The `graph.py add-unit --disposition clean-break|preserve-compat [--named-blocker X --removal-ticket Y]` command writes `work_units[u].disposition = {kind, named_blocker?, removal_ticket?}`.
Use `clean-break` or `preserve-compat` for `kind`.
The refusal code is `add_unit_refused_disposition`.

**Decision rows.**
Each `decisions_absorbed` row is `{seq, phase, decision, flip_condition, unit, chosen?, worker_status_seq?, revision, ts, prev_sha256, row_sha256, muninn}`.
Only `graph.py record-decision`, through `scripts/lib/decision_record.py`, appends them.
A worker-status answer resolves that status and saves the hashed row in one locked write.
Muninn sync follows after the lock.
A pending or unknown sync blocks the node’s next wave until reconciliation.

Muninn metadata keeps the R_ ID, project, and source window apart from the row hash.
The `flush-decisions` command reads that same submission.
A `syncing` or `unknown` result prevents automatic resubmission.
The reviewer path ignores the legacy `--cite-quote` input.
The dashboard reads `{phase, decision}`.

Phase -1 writes a decision only in a full-autonomous envelope. Workers do not write this field.

**Layout conversion.**
Version 1 adds `graph.wave_history {}`, `stops []`, and `updated_at`.
Version 2 adds `graph.dispatches {}` and `graph.contract_from_revision`.
The `begin-wave` command writes a single-use record for each node. Starting at that revision, waves must include a begin-wave envelope.

Version 3 adds `graph.context_from_revision`. Starting at that revision, records must include typed skills and checks.

The `begin-wave` and `authorize-dispatch` commands refuse a layout below 3.
Conversions from v1 to v2 and from v2 to v3 refuse an open wave with `convert_refused_active_wave_in_flight`.
The `graph.py start` command writes the current layout.
Use `graph.py convert <state> --session <id> [--check]` on the two providers to update an earlier file at the same path.

It writes `progress.json.pre-convert` one time before replacement. It does not overwrite or remove that file. A second conversion does nothing.

The command refuses with `convert_refused_<code>` if it cannot determine the layout or source.
For example, it refuses an unknown `schema_version`, a newer `state_minor`, or an in-flight wave without a `wave_history` entry.
It also refuses malformed `stops` or `work_units`, a non-object `graph`, a different session, torn version-2 dispatch data, or a `progress.json.pre-convert` file.

**Loop-scope evals.**
The `loop_state_guard` hook reads `.work_units | length`.
For one or more units, it checks loop-scope evals.
Without the field, this check does not block.
Keep it populated when the loop tracks one or more units.

**Work units and the Stop gate.**
The `loop_stall_guard` hook blocks `graph.py stop --category complete` while a unit has a nonterminal status.
This includes `pending`, `in-progress`, `blocked`, and values other than the permitted terminal values.
A `done` status is terminal.
A `dropped` status is terminal only with a non-blank string `dropped_reason`.

A missing, empty, whitespace-only, or non-string value blocks.
A unit that is not an object also blocks. The message names the unit IDs.

A missing or null `work_units` field or an empty object means no registered units.
A non-object roster or malformed unit blocks.
A missing or corrupt graph cannot complete.
The retro gate also applies.

**Waves and native worker records.**
Each loop has non-blank `session_id` and `loop_id`, schema 3, and a positive revision.
The orchestrator operates waves with the native Python CLI from `execution-graph.md`.
One provider-owned lock covers checks for changes, retry reads, transcript binding, and the atomic write.

A pending node can start only after each predecessor is `done` or `skipped`.
An open wave or hard stop prevents a new wave.
A `blocked` or `stale` predecessor does not qualify.
A wave outcome of `failed` increments `retry.attempts`. Ordinary nodes go back to pending. The graph does not keep `failed` as a node status.

With `FULL`, `U4`, `U4b-review`, and `U4b-merge-gate` block until a different diagnosed `record-repair` requeues verification.
The retry limit `retry.max` is 1 through 5. The node hard-stops at its limit.
A `stale` result must include an artifact check in the same result: `{"checked":true,"method":"<check>","result":"<observation>"}`.
An idle notice alone does not qualify.

The `respawn-stale` command records the cause and a new generation.
Follow it with a new native worker start.
Keep the prior worker records.
Only the adapter releases joins after each input succeeds.

Frozen dispatch evals bind `session_id` and `loop_id` only.
Native Agent prompts bind the current session, loop, revision, wave, and node.
The graph checks the initial parent and child records, native role, child attribution, satisfactory terminal output, and harness notification.

A caller’s IDs, echoed notifications, or worker claims cannot replace these records.
Each child in a fan-out must qualify.
Do not use the same identity across nodes or retries.

**`work_units` and `graph.nodes` are different records.**
A unit does not have to mirror a node.
Ending the graph does not finish a work unit.
A done unit does not supply the worker records a graph needs.
The two gates check independently and do not copy statuses.

**Only the `loop_stall_guard` hook writes `loop_stop_counts`.**
The `graph.py stop` command writes a `stops[]` row.
The hook marks the row `consumed` in the same atomic write that adds to the count.
Without a row it blocks with `stop_row_missing`.
The last text is for the user. The hook reads the row.

Do not write or increase the counts.
The `graph.py start` command does not write them.
On re-arm, it drops the counts because the completed loop’s `retro.json` has them.
Do not rewrite the full file by hand.

## Lifecycle

The `loop_state_guard` Stop hook checks for a file owned by an active session.
If there is no file, the hook blocks one time for the session and invocation count.
A new invocation count re-arms the check.
For the same count, the hook can let a session stop after it reads this file.
A session mismatch or stale complete after re-arm blocks each time.

- **Start (Phase -2).** Run `graph.py start` as in phases-setup.md. It writes `session_id`, a unique non-blank `loop_id`, `revision: 1`, and `status: "in-progress"`. It starts with an empty graph and no active wave. Then use `graph.py add-unit` for each unit. Do not write the records by hand. The command checks the initial data. If an unfinished loop owns the session, continue that loop. The command refuses a different `loop_id`.
- **Phase 0.** The envelope is in `authorising_prompt_raw`. Update it only if you use a revised envelope.
- **At phase boundaries.** Use `add-unit`, `begin-wave`, `record-wave`, `record-unit`, and `hard-stop` to update the loop. These commands write node and unit statuses, retirement decisions, and `last_updated`. Read them with `inspect` or `summarize`. Do not edit `progress.json` or `loop_stop_counts` by hand.
- **Teardown (Phase 13).** After the last loop updates, use `orders.py record` to record claims for the apply step. Run `orders.py --dir <repo-key dir> --session <session> prepare --loop <logical loop>` if there are claims or if there are none. Setup binds the eligible owned source and records `orders_prepared`. It changes no lifecycle counters.

  After last grading, proof runs, and retro assembly, run `python3 "${PLUGIN_ROOT}/skills/agentic-loop/scripts/graph.py" verify-completion <state> --session <session>`. Then run `python3 "${PLUGIN_ROOT}/hooks/scripts/lib/loop_state_common.py" mark-complete <cwd> <session>`. It sets status and the live invocation-count marker with the same lock.

  After the durable write succeeds, the native command applies the bound `orders.py tick --loop <logical loop>` and `render`. The `orders_ticked` record follows the ledger save. If the apply or observation fails, run `mark-complete` again to retry the pending teardown idempotently. Do not calculate or increase `completed_marker` by hand.

## Recency

A previous loop’s `status: "complete"` must not stop the guard for a new loop in that session.
The `graph.py start` command re-arms it with a new `loop_id` and `in-progress` status.
If a loop skips `graph.py start`, the guard compares the invocation count with `completed_marker`.
A count above the marker blocks and requires a new `start`.

Use native `mark-complete` during teardown.
Do not set `status: "complete"` with a bare write.
The next `start` keeps `completed_marker`.

## Concurrent loops in one directory

The file path uses the repo, or cwd if there is no repo, and `session_id`.
Two `agentic-loop` sessions in one repo get different files.
Different worktrees of that repo use the same parent directory.
The `session_id` alone distinguishes the files there.

The ID stays the same during one conversation’s compaction or restart.
Other conversations have different IDs.
If the ID in the file does not agree with its path, `loop_state_guard.py` blocks.
For example, this can occur with a copied or hand-edited file.

Use a different Git worktree to isolate working-tree changes between sessions.
The repo’s worktrees share the location for `progress.json` files.

## Honest boundary

The guard checks that the file is available and belongs to this session.
The orchestrator must keep its contents current.
The `check_verify_loop.py` hook has the same type of limit.

## Siblings in the same directory

- **`sdd-ledger.md`.** If a unit uses `superpowers:subagent-driven-development`, its workspace helper writes this ledger next to `progress.json`.
- **`retro.json`.** Phase 13 writes it one time next to the session’s `progress.json`.
- **`orders-prepared-<logical-loop sha256>.json` and `teardown.jsonl`.** These session-keyed files hold setup receipts and lifecycle observations. Setup binds the repo directory, loop directory, session, logical loop, revision, and hash of `progress.json`. It records claims for the apply step without changing recurrence or age. A receipt alone cannot authorize apply.
- **`evals.json`.** Freeze loop and PR scopes in Phase 2.7c and 2.7d with `/coderails:task-evals`. See `skills/agentic-loop/SKILL.md`.
- **`proof.json`.** Freeze it for the loop in Phase 2.7e next to `evals.json`. Use a different author agent. Give it only `authorising_prompt_raw`, `session_id`, and `loop_id` as explicit dispatch inputs. Do not give it the plan, spec, conversation, or access to read `progress.json`. Apply the `task-evals` rule for a grader that works independently to the proof author.

  Use `{"schema_version":2,"session_id","loop_id","frozen_at","frozen_sha","proofs":[{"id","claim","cmd","expect","status":"pending"}]}`. If the loop has no executable surface, do not write the file. Record the decision in `decisions_absorbed` and `progress.json`’s `proof_disposition` field.

  **The controller runs the proofs.** The Claude `loop_stall_guard` gate uses `loop_proofs.validate_proofs`. The Codex gate uses `graph_artifacts.validate_completion_evidence`. Run `scripts/lib/proof.py freeze <state-dir>` to check schema 2. Use unique IDs, nonblank `cmd`, and structured `expect` with `{exit_code, stdout_contains, stdout_not_contains}`. The `timeout_s` field is optional.

  Give one or more proofs that have not been withdrawn. The command refuses schema 1 because it ignores structured `expect`.

  The freeze appends a row with the SHA-256 of the canonical document. Run `proof.py run <state-dir> [--id X|--all]` to run each frozen `cmd` unchanged. It uses sandbox-runtime 0.0.65 and a timeout of 600 s by default. The command can read host files, write only in its new `TMPDIR`, and use no network. The controller refuses a command that matches the destructive classifier (`proof_cmd_destructive`). It refuses a run if the sandbox cannot start (`proof_sandbox_unavailable`).

  The controller appends the result row from the parent without the proof sandbox. Run `proof.py status` to see each proof’s latest verdict.

  **Proof result rows.** The controller writes `proof_results.jsonl` next to `proof.json`. Row fields:

  `{seq, kind: freeze|run|disposition|supersede, proof_id, cmd_sha256 (= sha256 of cmd.strip()), proof_json_sha256, session_id, loop_id, head_sha, source_tree_sha, cwd, exit_code, stdout_sha256, stderr_sha256, excerpt (capped 2000), started, ended, expect_matched, verdict: satisfied|failed|expect_mismatch|timeout|refused|sandbox_unavailable|output_limit, prev_sha256, row_sha256}`.

  The hash chain detects edits to kept rows and removal of a row before the last row. It cannot detect removal of last rows that leaves a correct prefix.

  For `LOOP-STOP: complete`, the gate reads the result rows without the transcript or `status` field. Each proof needs a latest run row on a correct chain with these properties:

  - Its `cmd_sha256` equals the current command hash.
  - Its `proof_json_sha256` agrees with the latest freeze row for this session and loop.
  - Its checkout and HEAD agree with the current controller checkout.
  - Its verdict is `satisfied`.

  The codes are also in `proof.freeze|run|gate` rows:

  - `proof_unexecuted`, `proof_failed` (`failed` or `timeout`), or `proof_expect_mismatch`
  - `proof_stale_cmd`, `proof_stale_head`, or `proof_chain_broken`
  - `proof_cmd_destructive`, `proof_sandbox_unavailable`, `proof_output_limit`, or `proof_disposition_no_reason`

  The `proof_stale_cmd` code means a change to `proof.json` after freeze or a different command hash. The `proof_stale_head` code means the checkout or HEAD changed. The message names each proof ID that blocks.

  **One replacement in the same graph.** An isolated proof author writes a pending schema-2 candidate and a different author report in a location external to the active graph. After a reviewer checks it, run `proof.py supersede <state-dir> --candidate <path> --reason <text> --original-sha256 <raw-sha> --author-evidence <path>`. The command keeps `proof.json` unchanged, saves the candidate by raw SHA, and appends one chained `supersede` row.

  That row binds the raw and canonical hashes of the two documents and their loop identity. The binding includes the report’s byte hash and path, the explanation, and issuance HEAD. The reader checks these bindings before it selects the candidate. Then run `proof.py freeze`, `run --all`, and `status`. Previous rows cannot satisfy the selected proofs. The current HEAD must agree with each new run row.

  A second replacement, changed input, missing report, or broken chain blocks. The reader does not select a file from an interrupted append. The check validates report bytes. It does not show who wrote the report or if the author worked independently.

  **Withdrawn proofs.** For a withdrawn proof, use the sibling `withdrawn_proofs` array in the same file: `[{"id","cmd","withdrawn_reason"}]`. Freeze and run it as a proof. Its latest run row must have an observed `failed` or `timeout` verdict. The `withdrawn_reason` must be nonblank. If the run condition is not satisfied, the gate reports `proof_withdrawn_unobserved`.

  Do not put the same `id` in `.proofs`. The two arrays share a cap of 100 entries. The `complete` systemMessage reports accepted withdrawals without blocking.

  **If there is no proof file, make a no-proof record.** This applies to the two providers. Give `proof_disposition` as `"none: <nonblank reason>"`, which logs `proof_disposition_legacy`. Or use the typed `{"kind":"none","reason_code","reason"}`, or a row from `proof.py disposition <state-dir> --none --reason-code <code> --reason <text>`. Use one of `docs_only|no_executable_surface|research_only|superseded|other` for the code.

  The gate reports the accepted record with the result. Without it, a file with no non-withdrawn proof blocks as `proof_no_proofs`. The gate refuses a bare `"none"`. If there is a proof file, it must identify this session and loop and give a numeric schema version of 1 or higher. A malformed file or non-array collection blocks.

  **What the gate checks.** The gate checks that the no-proof record is available. It cannot check that the explanation is correct. For a proof, it checks that the frozen command ran and matched `expect`. It cannot check the quality of the proof.

  **Same-user limit.** The agent and the result ledger writer use the same account. The agent can forge rows and calculate the chain again, remove a valid-prefix tail, or freeze a weaker proof set. The sandbox limits writes to the host and network access.

  The agent can control proof selection and the ledger. A weak proof can succeed. There is no config key or environment setting to disable the gate.

  **Schema 1 recovery.** Keep the previous files. For new work, start a new session and loop with schema 2. The current gate cannot recheck a completed schema 1 loop or retry its teardown. For that recovery, use the prior plugin in an isolated checkout.

  **Committed source.** The command starts in a private copy of `HEAD`. Use relative paths for repo files. It cannot read the initial checkout. Each run row includes `source_tree_sha`. The gate checks that hash, the repo, and `HEAD` before it accepts a satisfactory result.

  **Platform limit.** The runner uses `/tmp` for scratch on macOS and Linux. It refuses Windows proof runs until the Windows policy is in use and passes checks.
- **`orders.json`.** Only `scripts/lib/orders.py` writes this typed ledger. The views `standing-orders.md` and `standing-orders-decayed.md` are read-only (mode 0444) with a marker. They share the repo-key directory, two directories above `progress.json`, across sessions and loops in the repo.

  To read current cited lessons, run `scripts/lib/lessons.py --dir <repo-key dir> --session <known native caller id> query --format contract`. A refused or degraded read is unknown. Do not use a view to replace this query.

A retro belongs to one loop.
A lesson can apply to future loops.
The `orders.py` command holds one `dir_lock` through the currentness lookup, tagged-claim reconciliation, bounded sync, and direct atomic ledger write.
If a read fails, it keeps the prior K-id and gives a degraded result.
External Muninn sync uses no lock on `progress.json`.
The same-user lock gives no exactly-once guarantee for network operations.
