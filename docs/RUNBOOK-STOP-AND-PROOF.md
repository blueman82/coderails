# Stop checks, routine runs, and proofs

[Runbook](RUNBOOK.md).

## A stop has no recorded row

- Symptom: The Stop hook blocks with `stop_row_missing`. The last reply cannot release it.
  Run `graph.py stop` in the current turn with the correct category, cause code, explanation, data path, and session. The command writes `stops[]`.

- Query: Run `python3 scripts/graph_alignment_stops.py --json` for `stops_recorded`, `stops_consumed`, and `stop_row_missing`.
  Run `python3 scripts/lib/stop_counters.py` for refusal codes. A stale row gives `stale_stop_row`.
  The hook owns `loop_stop_counts`. Do not edit it or `stops[]` by hand.

- Remediation: Correct the source named by the refusal from `graph.py stop`.
  This applies to a different session, unknown category or code, or an unresolved graph on `complete`.
  The guard consumes a correct row one time. Codex can release an `awaiting-input` or `approval-gate` row while graph work remains.
  The `complete` row must have a resolved graph and verification records. See `docs/graph-alignment-measurement.md` for limits and commands.

## Host resource errors or bounded Stop checks

The codes `EMFILE`, `ENFILE`, `EAGAIN`, and `ENOMEM` during necessary Git reads indicate that the host ran out of resources.
The `destructive_patterns.git_output` function raises `HostResourceError` for these errors.
The destructive-command gate in each provider then denies the operation because the check could not run.
The denial cannot show that the operation is destructive or that the graph data has an error.

Usual nonzero Git exits give an empty lookup. Other Git errors can have different causes.

The Codex `graph_completion_guard` starts one **nine-second aggregate budget** before it reads input.
Data lookup, `inspect`, `consume-stop`, `verify-completion`, status, and recovery share that budget.
The registration gives the hook ten seconds, with time for the response.
If lookup or a graph check times out, the hook gives `decision: block`. A status or recovery error cannot show that the loop ended.

The deadline comes from the config and does not guarantee wall-clock time in all conditions.
See [the measurement limits](workflow-gates-measurement.md#hook-and-stop-measurements-f2).

An unresolved graph can use `request_human_approval`. Codex gives `decision: block` and a human-approval `systemMessage`.
Claude gives the notice and blocks Stop with exit 2. The notice key has loop, revision, session, active wave, and hard stop.
The hook suppresses a duplicate notice for 900 seconds. Stop remains blocked.

After that lease, a stall that continues can cause a notice and recovery again.
A status check can use `recover-wave` for a waiting worker. If the call times out, its outcome is unknown.
Codex does not record the notice marker after its deadline. Thus a deadline cannot suppress the next notice.
A notice cannot show that a worker recovered.

A correct `approval-gate` row with `needs_approval` can be consumed one time while graph work remains.
The typed row lets Stop continue. Its explanation does not control the result.
Consuming the row gives no authority for operations and does not complete the graph.

Use [the recorded-stop procedure](#a-stop-has-no-recorded-row) for the current provider.
The `request_human_approval` name is a function. A blocked call records `block` as its telemetry cause.

To find the cause of a refusal:

1. Record the provider, hook, source version or commit, session ID, and active hook registration.
2. Open the corresponding `hook_telemetry.jsonl` row. Compare `ts`, `pid`, typed output, and the session diagnostic log.
   The [measurement note](workflow-gates-measurement.md#hook-and-stop-measurements-f2) gives paths, causes, and counters.
3. Read the named graph data and verification records without changes. If the host ran out of resources, correct that condition.
   For a refusal about the graph or its records, correct the named fault through its workflow.
4. Retry the operation and examine its output and entries. Keep the records for the previous refusal.

Do not remove graph data, disable checks, or raise limits to clear a refusal with an unknown cause.
Change the interpreter only if the records show an interpreter fault.
These same-user hooks and file-based observations are advisory safeguards for agents that follow the rules.

Source checks and synthetic inputs do not prove installed hook trust, native-provider execution, live account use, server rules, or native worker recovery.
Integrity activation and publication have their own checks. See [integrity setup](INTEGRITY-GATE.md#turn-on-the-gate) and [publication measurement limits](workflow-gates-measurement.md#limits).

Sources: [Git lookup](../hooks/scripts/lib/destructive_patterns.py), [Claude gate](../hooks/scripts/destructive_bash_gate.py), [Codex gate](../packages/codex/hooks/scripts/destructive_bash_gate.py),
[Codex Stop guard](../packages/codex/hooks/scripts/graph_completion_guard.py), [Stop registration](../packages/codex/hooks/hooks.json), [Claude Stop guard](../hooks/scripts/loop_stall_guard.py),
and [shared notice helper](../hooks/scripts/lib/stall_notice.py).

## A routine run ended incomplete, aborted or refused

- Symptom: The dashboard gate for `docs-sync` or `loop-retro-promotion` is red.
  The last log marker is `abort=incomplete-run`, `abort=<code>`, `refused=<gate>`, `incomplete=merged`, or `incomplete=merge-unknown`.

- Query: Read the JSONL next to the run log (`run-{date}.jsonl` or `promotion-runs.jsonl`).
  The last row for the newest `run_id` gives `stage`, `outcome`, and `reason_code`.
  The outcomes are `stage_ok`, `run_ok`, `run_abort`, `run_refused`, and `run_incomplete`.
  The `trace.by_reason` keys are `routine/<outcome>/<reason_code>`.
  Run `python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/workflow_gate_counters.py` and read `routine`.

- Codes: `incomplete-run` means the session ended after `begin`. `runner_exit_no_terminal` means the runner saw the child exit with no terminal row.
  Other codes include `stage_out_of_order`, `audit_failed`, and `mining_failed`.

  The diff-manifest codes from `manifest_check` are `out_of_manifest`, `denied_path`, `docs_sync_deny`, `docs_sync_deletion`, and `special_file_type`.
  The list also has `status_not_allowed`, `too_many_paths`, `manifest_unreadable`, and `manifest_internal_error`.
  For `run_refused`, read the gate name: `push`, `review`, `post_review`, `post_evals`, or `merge`.

- Remediation: If the session stopped before the terminal row, read the output in the runs directory. Correct the cause.
  The `begin` command refuses an open run or a same-day abort or refusal. An open run continues across midnight.
  Use `begin --new` explicitly to replace the run. An open previous run first gets `run_abort incomplete-run`.

  A refusal names the gate that exited nonzero or did not start. If it did not start, stderr shows `gate_spawn_failed`.
  Cleanup prints `cleanup_failed: <step>` if it could not close a PR or local branch. Examine the named PR before cleanup by hand.
  The remote branch stays. Exit 2 with `routine_unknown`, `reason_code_invalid`, or `outcome_invalid` means the caller used a value off the lists.

- The `merged_incomplete` code means GitHub shows that the pinned PR merged, but the local run did not finish.
  Do not abort the run or close its PR.
  The `merge_state_unknown` code means GitHub did not identify the pinned PR and head. Put back that read before retry or cleanup.
  A changed head also stays unknown.

- The `log_unwritable` code refuses an update or a terminal result. Examine the two entry logs and saved data for part of an interrupted write.
  Then repair the destination. The `routine_mismatch` code means the log belongs to a different scheduled procedure.
  Select the correct log for this procedure. Do not finish or replace the data for a different scheduled procedure.

- See "Routine state machine and event log" in `docs/routines.md` for limits.

## Proof gate blocked a `complete` declaration

To replace a frozen proof suite in the same graph, keep the initial `proof.json` unchanged.
Get a pending schema-2 candidate and its author report from an isolated proof author.
Keep the two inputs external to the active graph. Examine them, then run:

```bash
python3 scripts/lib/proof.py supersede <state-dir> --candidate <candidate-path> \
  --reason "<why the original cannot run>" --original-sha256 <raw-proof-json-sha256> \
  --author-evidence <report-path>
python3 scripts/lib/proof.py freeze <state-dir>
python3 scripts/lib/proof.py run <state-dir> --all
python3 scripts/lib/proof.py status <state-dir>
```

For each proof, the controller makes a private copy of committed `HEAD`. The proof runs there and cannot read the initial checkout.
The controller uses fixed system paths for Git and Node. It refuses a committed tree with a symlink.
It starts the pinned sandbox from its cached absolute path. An unavailable or changed cached runtime gives `sandbox_unavailable`.

The command keeps one candidate by content hash and appends a chained `supersede` row.
It records the initial and candidate raw and canonical hashes, loop identity, report bytes, cause, and issuance HEAD.
The two providers use the same selected suite. Only freeze and run rows after that binding count.
The run HEAD and the current checkout HEAD must agree.

The check blocks a second replacement, changed initial or candidate file, missing report, or damaged chain.
Keep the report at its recorded path. An orphan candidate file has no effect.
The CLI checks the report bytes. Examine the author's identity and independence independently.

- Symptom: The Claude `loop_stall_guard` or Codex `graph.py complete` or `verify-completion` names frozen proofs as `P1(proof_...)`.
  The gate reads only `proof_results.jsonl` next to `proof.json`. The controller writes it through `scripts/lib/proof.py`.
  The gate does not read the transcript or the `status` field.

- Query: Run `python3 scripts/lib/proof.py status <state-dir>` for the latest verdict for each proof.
  Run `python3 scripts/measure_graph_alignment.py --root . --json | python3 -c "import sys,json;print(json.load(sys.stdin)['memory'])"`.
  Read `by_reason_code` for `proof.freeze|run|gate`. Or run `grep '"command": "proof\.' <agentic-loop dir>/<session_id>/trace.jsonl`.

- Remediation: The `REASONS` list in `scripts/lib/proof_results.py` supplies the codes.

  | Code | Procedure |
  |---|---|
  | `proof_unexecuted` | Run `proof.py run <state-dir> --all`. |
  | `proof_failed` | The latest run exited nonzero or timed out. Correct the cause and run again. |
  | `proof_expect_mismatch` | The exit code or stdout differs from the frozen `expect`. |
  | `proof_stale_cmd` | The `proof.json` file changed after freeze or the run row hashes a different command. Run `proof.py freeze`, then `run`. |
  | `proof_stale_head` | The run repository, HEAD, or source tree is different. Run again from the current repository checkout. |
  | `proof_chain_broken` | Someone edited a saved row or removed a row before the last row. Keep `proof_results.jsonl`. Start a new session and loop. |
  | `proof_cmd_destructive` | The destructive classifier refused the command before it ran. Reword the proof. |
  | `proof_output_limit` | The combined stdout and stderr went above 1 MiB. The controller stopped the group and recorded `output_limit`. The hashes use captured bytes only. The excerpt starts with `partial output`. Decrease the output and run again. |

  For `proof_sandbox_unavailable`, the pinned sandbox did not start. Prepare and check the pinned runtime, then retry:

  ```bash
  npx --yes @anthropic-ai/sandbox-runtime@0.0.65 --help
  npx --offline --yes @anthropic-ai/sandbox-runtime@0.0.65 --help
  ```

  The first command can download the runtime. The second checks the offline command that `proof.py` uses.

  For `proof_disposition_no_reason`, if there is no `proof.json`, record `proof.py disposition <state-dir> --none --reason-code <code> --reason <text>`.
  The check refuses bare `none` or a code other than `docs_only`, `no_executable_surface`, `research_only`, `superseded`, or `other` in `DISPOSITION_CODES`.
  The gate prints a correct decision.

  The `proof_no_proofs` code means `proof.json` is empty or has only withdrawn proofs. Freeze a proof or record a decision.
  The `proof_disposition_legacy` entry is advisory and accepts the string `none: <reason>`.
  The `proof_withdrawn_unobserved` code means a withdrawal must have a nonzero or timeout run row and an explanation.

- The proof command runs in its own pinned OS sandbox. It can read host files. It can write only in a new temporary directory named by `TMPDIR`.
  It cannot use the network. The repository and loop data are read-only to the proof command. The controller writes the result after the command ends.
  Use `TMPDIR` for temporary proof files. If the runtime is unavailable or the sandbox does not start, the run fails closed.

  The runner uses `/tmp` as private scratch space on macOS and Linux.
  Windows proof runs fail closed until the Windows scratch policy is in code and has checks. The live containment probe for this release ran on macOS.

- Limits: An agent with the same user ID can forge rows and calculate the chain again. It can also forge a transcript.
  The chain can find changes to rows that the writer kept and removal of a row before the last row. It cannot find removal of the last row if the other rows have a correct prefix sequence.
  The latest freeze wins. An agent can weaken a command or withdraw an unsuccessful proof and freeze again.

  If the controller stops before it appends a refusal, an earlier result that shows success can stay the latest row.
  The check for a decision looks for explanation text and an enum code. It cannot show if the explanation is correct.

- Schema 1 proof files are historical records. Do not edit them or change their format.
  For new work, start a new session and loop with a schema 2 proof.
  The current runner cannot check the end of a schema 1 loop or retry its teardown.
  Use the previous plugin version in an isolated checkout for that recovery.

- The proof gate is always on in the two providers. There is no config key or environment setting to turn it off.
  The previous check that used transcripts is gone.
