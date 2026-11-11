---
name: agentic-loop
description: Coordinate autonomous multi-step work with native Codex subagents and a durable, fail-closed execution graph. Use for teams, dependent work units, multi-PR runs, or end-to-end work without routine check-ins.
---

# Agentic Loop

Keep the primary Codex session as orchestrator. Workers implement the changes. The orchestrator owns one durable graph and is its only writer.
`update_plan` only displays information. It does not select which work can start, resume, or end.

Set `SKILL_DIR` to the absolute directory containing this `SKILL.md`. The helper is `scripts/graph.py` next to this skill.
It uses only the Python standard library. It calculates and records work. It does not start agents, other providers, nested sessions, or schedulers.

## Start or resume

Read the SessionStart bootstrap text first. It reports the path and inspection of the active graph, or the path for a new `progress.json`.
Use the same path after compaction or when you continue the loop.

For a new loop, put the outcome the user approved in a file. Copy the user's words verbatim.
Before you start workers, run `python3 "$SKILL_DIR/scripts/graph.py" start "$STATE" --session "$SESSION" --loop-id "<unique loop id>" --prompt-file "$PROMPT_FILE"`.
`$STATE` must end in `<session>/progress.json`.

The command writes the schema-v3 graph atomically (`in-progress`, revision 1, empty graph). It does nothing if you give the same loop ID again. It re-arms a completed loop.
If an unfinished loop owns the session, the command refuses with `[reason_code=...]`. Continue that loop.

Add each work unit with `python3 "$SKILL_DIR/scripts/graph.py" add-unit "$STATE" --session "$SESSION" --loop-id "<same id>" --unit N [--depends-on M ...] [--join] [--manifest GLOB ...] [--worktree ABS_PATH]`.
In one locked write it records the unit, its `U3[N]` node, dependency edges, and `J12-all-units` input.
For a pending unit, `set-unit-disposition` records one compatibility selection with its source at the current revision.
See the RUNBOOK for its flags. Do not edit `progress.json` by hand for these steps.

Nodes other than `U3[N]` and `J12-all-units` use the IDs and labels from their registration. Each node carries `respawn: {"generation":0,"intent":null}`.

An all-input join has an entry in `graph.joins`. Its `id` equals the join key. The entry has `mode: "all"`, its registered input node IDs, and `released: false`.
Downstream edges start at that join. Active waves use `wave_id`.

The graph refuses unknown nodes, malformed records, cycles, joins that disagree, or active nodes that do not belong to an active wave.

Keep the top-level `work_units` list apart from `graph.nodes`. Nodes record worker starts and control steps. Work units record the approved deliverables.
Before the loop can end, each registered unit must be `done` or `dropped` with a nonblank `dropped_reason`. Do not infer that a unit is complete from its graph-node status alone.

Before build, make and freeze ungraded loop-local `evals.json` next to `progress.json`.
The frozen suite must contain a nonblank `frozen_sha`, a positive verification level, and one or more P0 evals.
Use correct eval modes and scripted command and negative-control fields. Keep `result` and `grading` null. Grade against actual results at the end. Do not invent a pre-build GO.

Use the `session_id` and `loop_id` of this loop. These stable fields authorize worker starts across waves.
`begin-wave` does not invalidate the loop's eval authority. Keep the suite revision from freeze or grading.

Before build, the provider's hook accepts a correct frozen ungraded eval record. It also accepts actual graded records.
It blocks if graph ownership or loop eval records are unavailable or for a different loop.

If the graph has three or more units or a dependency between units, apply the design guidance in `superpowers:brainstorming`.
Skip its interactive approval gate. Write or use an existing `spec.md` next to `progress.json`.
Then invoke `superpowers:writing-plans` to make durable `plan.md` in that directory. Keep it out of the code repository.

`plan.md` gives the fixed scope and division of work. `progress.json` records the current position and results.
Derive each node's scope from the plan. Read `spec.md` and `plan.md` again when you continue the loop. Do not make these files for one or two self-contained units.

Before you start a node that can write, invoke `superpowers:using-git-worktrees`. Use Coderails `prep` to make the worktree.
For a non-Git folder it also makes the local `main` repository and initial commit. Do not add a remote.

If registration did not name the checkout, run `graph.py assign-worktree "$STATE" --session "$SESSION" --loop-id "<same id>" --unit N --worktree ABS_PATH`.
Run it after prep and before unit publication. This locked command can fill a missing assignment in an active wave without a revision change. It refuses a different assignment.

Before you end a turn that pauses an active loop, run `graph.py stop`:
`python3 "$SKILL_DIR/scripts/graph.py" stop "$STATE" --session "$SESSION" --category <hard-stop|approval-gate|awaiting-input> --reason-code <code> --reason "<reason>"`.
The Stop hook consumes the recorded row one time. Its vocabulary comes from the shared `graph_vocab.py`, as it does for Claude.
The Stop hook does not consume a `complete` row. That row goes through `complete` and `verify-completion`.

Hooks do not read the displayed last line. If there is no row, the Stop hook blocks and records `stop_row_missing`.
Run `python3 "$SKILL_DIR/scripts/graph.py" inspect "$STATE"` before you continue the loop.
Use that inspection for loop and session identity, revision, active wave, node status, and cause of a hard stop. Do not reconstruct these facts from chat history.

## Run one wave

Current native Codex dispatch encrypts the worker message before the hook sees it. The hook refuses graph workers with `dispatch_prompt_unverifiable`.
A task name and ciphertext hash cannot prove the worker instructions. Do not open a native wave on this transport. Record a `hard-stop` row with that `reason_code`.

When the checked local Codex OAuth graph driver is installed, follow its `cutover-driver` and `drive` instructions. Until then, the graph cannot start workers.
The native steps below apply only if a future transport exposes the full message and role to the hook.

Use this sequence for each wave.

After the machine ownership marker in each worker prompt, give a human-readable line with the printed one-word `job_name`, `lane_code`, and stable node ID.
For example, use `Builder · A-1 [U3[1]]`. The line is for display only. Use the stable node ID for task identity, authorization, and verification records.

1. Run `graph.py begin-wave "$STATE"`. It validates the full graph and refuses an existing active wave.
   It finds the complete deterministic set of nodes that can start and marks them `running`.
   It increments the revision and writes one single-use record for each node in `graph.dispatches`.

   It prints the wave ID, node list, and `task_names` mapping. For each node it prints `dispatch_id`, `prompt_prefix`, and `prompt_sections`.
   You must run `begin-wave` before `spawn_agent`. For a file below `state_minor` 3, first run `graph.py convert`.
   Conversion refuses an open wave. `inspect` prints the task-name mapping again while a wave is active.

2. For a wave with two or more nodes that can work independently, invoke `superpowers:dispatching-parallel-agents` for guidance.
   The guidance is advisory. `graph.py` decides which nodes can start.

3. Use native `spawn_agent` one time for each printed node. Use the provider's printed `task_name` if the tool has that parameter.
   For a guarded read-only scout, set `agent_type` to the role in the record.
   The roles with this check are `preflight-scout`, `design-scout`, `disposition-scout`, `source-auditor`, and `deploy-safety-reviewer`.
   Other nodes accept their own role or an unnamed native role. A different named role gives `role_mismatch`.
   If the tool has no role parameter, do not invent one for unguarded nodes.

   Put the printed `prompt_prefix` (the `CODERAILS_GRAPH_DISPATCH=` envelope) on its own line. Then copy the printed `prompt_sections` verbatim.
   The native hook must get readable text. It refuses encrypted prompts with `dispatch_prompt_unverifiable` because it cannot check their instructions.

   The canonical task name encodes loop ID and node ID as lowercase UTF-8 hex with `_` between them.
   Retries and stale respawns append `_aN`, where N is the count of retries that did not succeed plus respawn generation plus one.
   This makes the native identity unique across loops and tries. You can decode the identity from the name.

   Read `../../agents/loop-worker.toml` relative to this skill. After the copied sections, include its `developer_instructions` text explicitly.
   Then give the task brief and current user restrictions.

   Tell the worker to work only in its scope, use tests first for testable changes, and check actual command results.
   Tell it to check its own work and report the result honestly. Do not infer that a native label loads these instructions.
   User restrictions on commits, remote writes, or test scope override the template.

   Give each worker its own prompt with node ID, scope, allowed paths, worktree, exclusions, checks, mandatory artifact, and short verification report.
   For testable code, specify `superpowers:test-driven-development`.
   Specify `superpowers:subagent-driven-development` for worker construction and `superpowers:verification-before-completion` before the worker reports.
   Do not use a different provider or start a nested Codex session.

4. Use the native `wait_agent` tool in the collaboration surface. Wait for a terminal report from each node in the active wave.
   A wakeup or mailbox notice alone does not give a terminal result.
   `record-wave` resolves each task marker from the legacy `CollabAgentToolCall` record or the native `spawn_agent` function call and its one `SubAgentActivity`.
   It then checks the child's `source.subagent.thread_spawn` metadata and `task_complete` with a success status.

   Use only loop-scoped names (`task_names` from `begin-wave`). A legacy node-only name gives `legacy_task_identity_refused`.
   You cannot reopen a done node. Start a loop that uses legacy names again with a new `--loop-id`. `verify-completion` also refuses completed legacy loops.

   A quiet worker alone does not show an error. Examine its artifact.
   If necessary, use one focused correction through `send_message` for an active worker or `followup_task` to continue an idle worker.

5. Check each report against the actual diff, test output, PR status, or other current artifact.
   A worker summary alone does not show that the work is complete.
   A worker that must stop for a person gives one typed status (`NEEDS_DECISION`, `OUTSIDE_SCOPE`, or `IRREVERSIBLE_ACTION`).
   The schema is in `scripts/worker_status.py`. Only the orchestrator contacts the person, after `validate()` and `to_decision_request()`.
   These statuses are not `record-wave` results.

6. Make one result object with a key for each active-wave node and no other keys.
   Each result is `{"outcome":"done|skipped|failed","evidence":"observed evidence"}`. Record it with:

```bash
python3 "$SKILL_DIR/scripts/graph.py" record-wave "$STATE" \
  '{"wave_id":"wave-N","results":{"U3[1]":{"outcome":"done","evidence":"check passed"}}}'
```

The envelope names a single-use dispatch record. A second use gives `dispatch_replayed`.
The task name must equal the name in the record. The binder uses it to identify the records.
`graph_transcript` reads the first line of `CollabAgentToolCall` only for historical transcripts.
Native task paths, child and thread IDs, and the supplied role must agree with the provider transcript records.

If the caller supplies a native role, it must agree with the two child role fields.
For a role-less spawn, the binder accepts only the recognized `collaboration` function call and `SubAgentActivity` with an explicit null nested spawn role.
The top-level role can be null or omitted. If the top-level path has a value, it must agree.

The binder checks parent and session, depth, unique dispatch, terminal results for completed runs, cursor, and reuse.
For a checked stale result, it checks the unique native spawn and child ownership. It does not invent a terminal success.
At loop end it checks each abandoned run again from native transcripts.

On a future readable transport, `loop_dispatch_guard.py` uses `graph.py authorize-dispatch --dispatch-id --message-file --agent-type --task-name --tool-use-id` for a graph-bound spawn.
It checks the graph, session, wave, record, role, eval authorization, and full prompt before the worker starts.
On the current encrypted transport, it refuses with `dispatch_prompt_unverifiable` before authorization. The task name or ciphertext hash cannot replace the full prompt.

`add-unit` accepts `--model-role`, `--write-scope`, `--lesson`, and `--scope` in the contract. The manifest gives the default write scope.
The check only asserts `agent_type`. It does not check Codex role containment (no shell and MCP for each role).

If each worker in the active wave stays silent longer than a lease, run `graph.py recover-wave "$STATE" --session "$SESSION" [--lease-seconds N] [--report-only]`.
It gives one stable `reason_code` and one status for each node:

- `dispatch`: No spawn exists. Start the worker. The command records nothing for it.
- `record`: The worker finished or the launch was refused. Record that result.
- `waiting` or `stalled`.

Only if all nodes are `stalled` does the command record them `stale` and schedule a respawn in one locked write. It does not count a try without a stored worker record.
If a node has `retry.max` respawns or more, the command refuses with `recovery_budget_exhausted`. A person decides what to do.
Each result appends a non-authoritative row to `recovery-trace.jsonl` next to the graph file. See `docs/recover-wave-runbook.md`.

For plain-language status, run `graph.py summarize "$STATE"`. To list graphs and readable node names, run `graph.py collection <state-root>`.
An optional `collection.json` explicitly links graphs:
`{"schema_version":1,"graphs":[{"key":"build","path":"build/progress.json","loop_id":"build-loop","links":["verify"]},{"key":"verify","path":"verify/progress.json","loop_id":"verify-loop","links":[]}]}`.

Paths and loop IDs must agree with the schema-v3 graph files. Entries in `links` name keys. The command refuses unknown or ambiguous targets.
Without an index, it lists disconnected graphs. It only reads graph files and gives links plus `unresolved_targets` (empty for a correct index).
The collection command refuses malformed graph files.

If a blocked Stop finds a silent wave, the hook can run this recovery. The limit is one run for each 900s lease for the same graph.
It has a 4s budget. It can respawn a worker that is alive but silent, so a duplicate is possible. `retry.max` limits respawns. If recovery times out, the result is unknown.

The collection command adds `key` and `links` to each graph record. An unlinked record has `"links": []`.
Each node keeps its stable `id` and gives its one-word `name`, optional `lane_code`, and current `status`.
For example, `{"id":"U3[15]","name":"Builder","lane_code":"C-3","status":"pending"}`. A missing or malformed target gives a `graph:` error.

The command refuses malformed, stale, unsuccessful, duplicate, or reused worker records. The record set must include all the active wave's nodes and no other nodes.
The command also refuses records from a different wave or session. These refusals do not change the graph.

`record-wave` adds compact transcript records to the node's existing array atomically. Workers do not write to the graph.
A node that does not succeed increments its try count and keeps its own record for that try.

If `spawn_agent` refuses (for example "agent thread limit reached"), try again with the same printed `task_name` until it succeeds.
If it continues to refuse, report the node as `failed`. `record-wave` uses the latest refusal (an error result with no `SubAgentActivity`) as that try's record.
A refused call cannot satisfy `done`, `skipped`, or `stale`.

A `followup_task` turn on a recorded child does not invalidate its earlier recorded result. The child's latest turn must end with success.
The node goes back to pending while the retry budget permits. A spent budget becomes a durable hard stop.
All-input joins release deterministically after all inputs succeed. Run `inspect` again, then `begin-wave`.

**Stop on scout spawn refusal.** If the design scout or a reviewer cannot start, do not use an orchestrator or worker read as the scout.
Try the spawn again with the same `task_name`. If it continues to refuse, use `graph.py record-wave` to record the node as `failed`.
`graph.py record-wave` uses the refused call as the record for that try. A refusal does not satisfy `done`.

A `not_found` for a `task_name` from a previous session or resumed loop is different from a capacity refusal.
Try with a new `task_name`. Do not use the same name.

If no scout can do the check independently, stop the loop and wait for the user.
A `non_independent` fallback needs explicit user approval.

After you record the refused scout call, send the owner this question verbatim:
`Coderails: Approve a non-independent design-scout fallback for loop <loop_id>, node S2.5, attempt <next_attempt>? Reply approve or deny.`
Replace the two placeholders with the current values. The next direct user reply must be `approve`.
The native record command checks the two transcript messages. It refuses a missing or different reply.

Only after that reply, record `S2.5` as `skipped` with an `evidence` prefix of `non_independent: human approved`.
Run `graph.py record-decision` with that phase and decision text.
A `non_independent` read cannot count as a check by a different agent or as `done`.

If there is no design fork, record `no_design_fork: <reason>` before a scout call.
If no path retires, use `no_retired_path: <reason>` for the sibling.
The skip records let `J2` release.

Before each `graph.py record-decision` call, read the current `loop_id` and `revision` from `progress.json`.
Give them as `--loop-id` and `--revision`. The CLI refuses a stale caller.

**Agent limit.** A spawned agent thread counts until you retire it. This includes completed and idle threads.
Before you start a scout, use the provider's close tool where one exists to retire completed threads (Codex: `close_agent`).

If the tool is unavailable, nothing frees the slot. Record the limit in the refusal and stop. Do not infer that a thread closed.

Check the deliverable independently and record its wave. Then record the registered work unit:
`python3 "$SKILL_DIR/scripts/graph.py" record-unit "$STATE" --session "$SESSION" --unit "<id>" --status done --evidence "<observed check>"`.
If the user withdraws the approved deliverable, use `--status dropped --reason "<reason>"`.
The command needs a pending unit with no active wave. It records the decision atomically.

It does not change the revision, so the stored wave records stay in effect. Completing a graph node does not change its work unit by itself.
Grade the last evals against the current graph revision.

Use the user's concurrency limit if given. If not, use a maximum of three workers at the same time. Set up a graph with wave widths that satisfy the limit before you start it.
If a wave has more nodes than the limit, do not start an unrecorded subset.

## Review and release

Keep inspections in Codex. Use new Codex reviewers and Codex workflow skills for inspection and eval records, push, and merge.
Inspection and release can use nodes in the graph. Do not use cross-provider joins. Check each worker result before accepting its claim.

For a confirmed problem, diagnose and make a maximum of five different repairs.
If the cause is unclear, invoke `superpowers:systematic-debugging` before you try a different repair. The same step again does not count as a new try.

Stop if verification cannot continue, a premise is incorrect, or the approved scope does not include a material decision.
Also stop before an irreversible step without user approval. Record the cause in the graph's `evidence` field and `hard_stop`.
After the work-unit PR merges, use `superpowers:finishing-a-development-branch` for worktree cleanup.

## Complete

Before you finish, run `graph.py flush-decisions "$STATE" --session "$SESSION"`. Keep and report degraded Muninn sync results. Stop if the decision chain is invalid.
Then update and grade `evals.json` again against the current revision. Write these files next to the graph file:

- Graded `evals.json` for the current session, loop, and revision.
- `proof.json` for the same session and loop. Use schema version 2 with unique IDs and nonblank `cmd`.
  Use structured `expect` `{exit_code, stdout_contains, stdout_not_contains}` and optional `timeout_s`.
  For a loop with no executable surface, record the typed decision below and leave no proof file.
- `retro.json` from `retro.py` for the same session and loop. Use schema version 3 and `status: "complete"`.

For a loop with no executable surface, record the cause in `decisions_absorbed`. Do not write `proof.json`. Get the current revision from `inspect`. Then run:

```bash
python3 "$SKILL_DIR/scripts/graph.py" record-proof-disposition "$STATE" \
  --session "$SESSION" --loop-id "$LOOP" --revision "$REVISION" \
  --disposition none --reason "no executable surface"
```

The command writes `none: no executable surface`. It refuses a different session owner, a stale revision, an active wave, an existing proof file, or a second decision.

Prepare standing instructions through the tool. Do not edit Markdown by hand. Set `D` to the repo-key directory (the grandparent of `$STATE`).
Set `LOOP` to the logical `loop_id` from the graph this session owns. Set `O="python3 $SKILL_DIR/../../scripts/lib/orders.py --dir $D --session $SESSION"`.

For each problem, run `$O record --failure-mode "<mode>" --lesson "<imperative lesson>" --loop "$LOOP"`.
Add `--scope agnostic` if the lesson applies to all repositories. Run from the mapped project repository.
The tool binds the eligible owned source and records `orders_prepared` without recurrence or aging. The native `complete` command checks the prepared source again.

Exit 3 prints a `reason_code`. Report it. Do not write a Markdown fallback. `memory.backend: off` explicitly disables this step.

A pending R-ID shows only that the tool accepted the entry. Cite recovery examines the retained source entry. The tool ignores the deprecated quote option.

Current Notes keep conditions, expiry, and the full set of verified selected source records. They explicitly show unsupported conditional uses.
Source records do not qualify the native, live, installed, or release operation of the initial I work. Claude live is not complete.
See `docs/RUNBOOK.md`, "Current request and citation boundary".

Flush and reload pending updates to the source before the last `prepare`. The command refuses changed sources by default.
For an allowed retry with an unfinished source, use `$O prepare --loop "$LOOP" --refresh-from-sha256 <CURRENT evidence_sha256>`.
Give it the canonical hash from the current `prepare` result.

Immutable ownership must agree. The revision cannot roll back. No tick or recurrence can have been applied for that session and loop.
The tool keeps the records it prepared without applying effects. If a saved replacement has no usable receipt, use ordinary unchanged `prepare` to correct it.
Do not refresh completed inputs.

The controller runs the proofs. Set `P="python3 $SKILL_DIR/../../scripts/lib/proof.py"` and `D` to the directory that contains `$PROOF`.
Run `$P freeze "$D"` one time. Then run `$P run "$D" --all` and read the verdicts with `$P status "$D"`.
Each frozen `cmd` runs unchanged with its timeout in sandbox-runtime 0.0.65. It can read host files, write only below its new `TMPDIR`, and use no network.

If the classifier identifies a destructive command, the controller refuses it with `proof_cmd_destructive`.
If the sandbox is unavailable or does not start, the controller records `proof_sandbox_unavailable`.
After each run, the controller writes a row to `proof_results.jsonl` next to `proof.json`. If you edit `proof.json` after freeze, freeze it again.

With no proof, run `$P disposition "$D" --none --reason-code <code> --reason "<text>"`.
The controller refuses a bare `none`. It accepts `proof_disposition: "none: <reason>"` in the graph file.
Keep retained schema 1 proof files. For new work, start a new session and loop with schema 2.
To check a historical schema 1 end or retry its teardown, use the earlier plugin version in an isolated checkout.

If one replacement in the same graph is necessary, use an isolated proof author. Have the author write a pending schema-2 candidate and report apart from the active graph.
Examine it, then run `$P supersede "$D" --candidate <path> --reason "<text>" --original-sha256 <raw-sha> --author-evidence <report-path>`.
The controller keeps `proof.json` unchanged and records one chained binding to the candidate and report bytes.

Freeze and run the selected candidate at the current HEAD. Earlier run rows do not satisfy it.
The controller blocks a second replacement, changed file, missing report, or broken chain.
The report hash binds bytes only. A reviewer must check author independence independently.

The proof command starts in a private copy of committed `HEAD`. The controller refuses a committed tree that has a symlink. Use relative paths for repository files. The initial checkout is not readable. The result records the source tree hash. The gate checks that hash against the current commit.

After the proof run or typed decision to use no proof, make all last updates and flush decisions.
Record one `complete` stop with `graph.py stop "$STATE" --session "$SESSION" --category complete --reason-code work_complete --reason "<reason>"`.
Then run `$O prepare --loop "$LOOP"`. Run it if there are no lesson records too. Run `python3 "$SKILL_DIR/../../scripts/lib/retro.py" assemble "${STATE%/*}" --session "$SESSION"`.
Do not record a second stop on retry.

Apply `superpowers:verification-before-completion` to the orchestrator's claim that the loop is complete. Then run:

```bash
PROOF="${STATE%/*}/proof.json"
python3 "$SKILL_DIR/scripts/graph.py" complete "$STATE" \
  --session "$SESSION" --evals "$EVALS" --proof "$PROOF" --retro "$RETRO" \
  --transcript "$TRANSCRIPT_PATH"
```

Keep this sibling `proof.json` path if the recorded decision leaves no file.

The command runs `prepare` before it gets the graph lock. It checks the prepared source and writes the complete result with the lock.
After it releases the lock, it runs `$O tick --loop "$LOOP"` and `$O render --loop "$LOOP"`.
Apply checks the independently bound directory, session, logical loop, and source. It checks the actual provider revision when the loop ends.

New completed recurrences reset counters. Lesson records with no match age one time and become tombstones at K=5. The tool does not remove them.
If the native write does not succeed, nothing ages. The tool records `orders_ticked` after the ledger write.
If apply or its observation does not succeed after the loop ends, the result is `pending_teardown: true`.

Run the same native `complete` command again to continue the bound tick and render before you report teardown complete.
`verify-completion` and the Stop hook refuse pending teardown.

An earlier complete loop without D4 receipts needs explicit legacy admission after an inspection. See the standing instructions decision and runbook.
Admission checks the file hash. Then it records the binding to the graph source and lets the tool record the completed result.
It does not age lesson records. New loops cannot use it.

The `complete` command refuses if it finds one of these conditions:

- Active wave, nodes in `pending`, `running`, or `hard-stop`, a graph hard stop, or unreleased joins.
- Missing or invalid native worker transcript records, or records from a different loop.
- Stale eval revision, missing or ungraded evals, missing proof, or missing retro.

It checks each stored worker record against the owning parent and child transcripts. Then it checks `proof_results.jsonl`.
For each proof, the latest run row for this session and loop must have:

- `cmd_sha256` equal to the current cmd hash.
- `proof_json_sha256` equal to the value in the latest freeze row.
- The current controller checkout and HEAD.
- Verdict `satisfied` on a correct hash chain.

The command does not use the transcript or a `status` field for proof checks. It accepts and ignores `--transcript`.
It can give `proof_unexecuted`, `proof_failed`, `proof_expect_mismatch`, `proof_stale_cmd`, or `proof_stale_head`.
It can also give `proof_chain_broken`, `proof_cmd_destructive`, `proof_sandbox_unavailable`, or `proof_disposition_no_reason`.
See `docs/RUNBOOK.md`, "Proof gate blocked a `complete` declaration".

A same-user agent can forge rows or remove rows at the end and keep a correct prefix. This safeguard relies on agent cooperation.

On success, the command atomically marks the loop complete and increments the revision. The provider's Stop hook does the same proof checks before it lets the complete loop end.
A durable graph hard stop can end only with one of these as the last nonblank report line:

- `LOOP-STOP: waiting-on-human`
- `LOOP-STOP: stopped`
- `LOOP-STOP: stall`
