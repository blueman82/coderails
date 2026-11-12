# Workflow gate measurement

This document defines publication-gate entries, hook outcomes, Stop checks, and their limits.
Publication entries come from `scripts/lib/publication_gate.py` and its diff manifest.
The agent and log writer use the same user account.

| Verification | Status |
|---|---|
| Source | The candidate plugin has the publication checks, diagnostic log writers, and hook code catalog. |
| Local | Tests can show an accepted or refused result for a fixed command and data. |
| Installed | A new trusted provider session must show that the hook ran and refused a negative control. |
| Server | Turn on and check the GitHub `integrity-review` rule independently. Source code does not turn it on. |

## Rows

A refusal appends advisory entries to `<loop dir>/<session>/trace.jsonl`.
The session ID is the sanitized label `<repo>@pr-<N>` or `<repo>@<branch>`.
If metadata lookup fails, it uses `pr-<N>` or `local`.
The `measure_graph_alignment.py` script counts them in `trace.by_reason` with key `command/outcome/reason_code`.

| Row | Meaning |
|---|---|
| `diff-manifest/ok/diff_manifest_ok` | The diff satisfied the policy. |
| `diff-manifest/refused/<code>` | The `enforce` mode refused with `<code>` and wrote one entry for each violation. |
| `diff-manifest/warned/<code>` | The `advisory` mode found a violation and let publication continue. |
| `diff-manifest/failed_open/manifest_unreadable` or `diff-manifest/failed_open/manifest_internal_error` | The `advisory` mode could not check the diff. |
| `diff-manifest/legacy/manifest_legacy_absent` | The policy has no `manifest` key. |
| `diff-manifest/warned/diff_manifest_mode_invalid` | The check used `enforce` because the `diff_manifest` setting was unknown. |
| `review-passes/ok/review_passes_ok` | The artifact satisfied all mandatory passes for the diff. |
| `review-passes/refused/<code>` | Codes are `required_review_missing:<name>`, `required_review_failed:<name>`, `review_passes_malformed`, `review_artifact_missing`, `review_policy_unreadable`, or `review_policy_modified`. |
| `eval-level/ok/eval_level_ok` | The suite names the current PR head and all P0 results show success. Its level satisfies the live diff and the declared or posted work-unit floor. The late-freeze stamp agrees. At level 1 or 2, the check accepts a full frozen SHA. |
| `eval-level/refused/<code>` | Codes are `level_below_derived`, `late_freeze_unstamped`, `suite_hash_mismatch`, `suite_hash_marker_mismatch`, `chain_broken`, `chain_truncated`, and `integrity_stripped`. Other codes are `not_frozen`, `eval_facts_missing`, `eval_artifact_missing`, `eval_artifact_unreadable`, `eval_embed_malformed`, `eval_head_mismatch`, `eval_result_mismatch`, and `eval_level_diff_unavailable`. |
| `publication/refused/<code>` | The gate refused with `diff_manifest:<code>`, an inspection or eval-level code, `pr_repo_override`, `pr_base_mutation`, or a subsequent unit code. |
| `routine/<outcome>/<code>` | The `scripts/routine_log.py` script logs outcomes `stage_ok`, `run_ok`, `run_abort`, `run_refused`, or `run_incomplete`. Each procedure has a closed code list. The code is `none` for `stage_ok` and `run_ok`. Examples are `routine/run_abort/docs_sync_deny`, `routine/run_refused/merge`, and `routine/run_incomplete/incomplete-run`. The procedure name is the session ID. |
| `verify-merged/ok/verified` | The `scripts/verify_merged.py` script checked a merge by content or merge-commit ancestry. |
| `verify-merged/refused/<code>` | The first code is one of `pr_number_invalid`, `origin_repo_unresolved`, `repo_mismatch`, `gh_failed`, `not_merged`, or `merged_at_missing`. Other codes are `fetch_failed`, `merge_commit_unreachable`, `content_absent`, `content_preexisting`, `content_check_failed`, and `content_check_required`. The key is `<repo>@pr-<N>`. An option-shaped PR argument gives JSON before parsing and writes no entry. |
| `argv/denied/ceiling_exceeded` | In one worktree, the ceiling denied a third or subsequent full suite or `post_evals.py post` or `post_evals.py validate-structure`. The key is the calling session. |
| `argv/denied/protected_paths_unreadable` | The gate cannot find or parse `policy/protected_paths.json`. It refuses edits on `main`. |

Manifest codes include `out_of_manifest`, `denied_path`, `docs_sync_deny`, `docs_sync_deletion`, `not_linked_worktree`, and `special_file_type`.
Other codes are `mode_change`, `status_not_allowed`, `too_many_paths`, `manifest_unreadable`, and `manifest_internal_error`.
The `diff_manifest_mode_invalid` code warns that the check used `enforce`. It is advisory.

The diagnostic CLI gives `foreign_session` for an explicit `--session` that does not agree.
Publication checks the unit owner-field structure and the worktree path. It does not authenticate the owner fields.

The counters count log entries. One run can have more than one entry. The `run_incomplete` result is provisional.
An explicit `begin --new` closes an open previous ID with `run_abort/incomplete-run`.
If a gate cannot start, the runner logs `run_refused/<gate>`.

If a log write fails, stderr gives `log_unwritable`. If the data belongs to a different procedure, stderr gives `routine_mismatch`.
These errors do not log success or update the saved status.
A write can stop before the end, and the runner can append without a lock in fallback.
These entries cannot prove the status update succeeded. Examine JSONL, the human-readable log, and the saved status together.

## Counters

    python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/workflow_gate_counters.py

The command prints `{command: {outcome/reason_code: count}}`.
It counts `diff-manifest`, `review-passes`, `eval-level`, `publication`, `argv`, `routine`, and `verify-merged`.
When a unit adds a new entry type, add the command name to `COMMANDS` in the counter.
The `measure_graph_alignment.py` script stays unchanged because it is at its line limit.

Hook telemetry keeps a typed record with the hook, observed decision, cause code, parameters, and repair step.
The diagnostic log keeps the full code if the hook writes one. A telemetry cause such as `deny` gives the broader result.
The `scripts/gen_hooks.py --check` command checks hook registrations and code tables. It cannot show that an installed hook ran.

## How to read it

- In usual operation, most entries are `ok`. Each rare `refused` entry corresponds to a diff external to its scope.
- If many entries have `refused/manifest_unreadable`, check policy, diff, paired flags, and unit metadata.
  Check its manifest, owner fields, and worktree. These entries cannot identify a path external to the scope.
- A `refused/manifest_internal_error` entry marks a bug. File it.

- A `refused/eval_head_mismatch` entry means the suite has no current PR head or its head is different.
  A `refused/eval_result_mismatch` entry means a GO artifact has a P0 without success.
  Correct the head or verification records, run and grade the evals again, then post with `post_evals.py post <PR> <evals.json>`.
  The `eval-level/refused/<code>` and `publication/refused/<code>` counters include these codes.
- If there are `warned` entries and no `refused` entries, the installation uses `advisory`, the previous default.
- No `publication/*` entries do not prove the gate ran. Possible causes include a disabled hook, an untrusted Codex plugin, or `diff_manifest: off`.
  Push writes `diff-manifest` entries without `publication` entries.
  Check active registration and observe a denial through the installed consumer before you claim that the check applies.

### Argv rows

- An `argv/denied/ceiling_exceeded` entry should be rare and correspond to a loop that ran a full suite again.
  The authoritative count files are `<loop dir>/verification-ceiling/<sha1>__<target>.count` and Codex `$PLUGIN_DATA/verification-ceiling/`.
  Diagnostic log entries count only denials.

  The optional mirror uses `work_units[u].verification{run_all,post_evals}`.
  It uses only the same payload session and `CLAUDE_LOOP_ID`, an in-progress schema-3 loop, and one physical worktree for the unit.
  That unit must have an active `U3[<id>]` in `active_wave.nodes`. A skipped mirror does not change the ceiling decision.

  The two native `add-unit --worktree` CLIs record the unit worktree. Fixtures alone do not prove installed integration.

- An `argv/denied/protected_paths_unreadable` entry means the installed plugin has a problem with `policy/protected_paths.json`.
  The hook refuses edits on `main` until repair. It does not log recognition of commits, pushes, or merges.
  Fewer gated commits after the classifier shipped can also mean fewer commits overall.

### Procedure scripts

Only `verify_merged.py` writes entries. The `wiki_lint.py stale`, `memory_dir.py`, `detect_test_command.py`, `merge.py --describe`, and `check.py --json` commands are read-only.
The `memory_dir.py` command prints a path. The other commands print JSON.
They write no entries to count their use.

An increase in `verify-merged/refused/content_absent` or `content_check_required` means the "merged" claims have no content record.
It can also mean the caller omitted `--grep` on a squash merge. These counts do not measure merge errors.

The `content_preexisting` code means the search text predates the merge.
The `content_check_failed` code means Git could not check for the text, for example if a shallow clone has no first parent.
The two codes do not count merge errors. Put back the history or select new search text before you try again.

Wiki candidate counts, data-gap counts, and quality feedback are advisory. They do not count installed calls or enforcement.
The Codex quality adapter uses no external tools.

## Hook and Stop measurements (F2)

For procedures, see the [resource and Stop runbook](RUNBOOK.md#host-resource-errors-or-bounded-stop-checks).
Hook telemetry and graph diagnostics use different records.

### Hook telemetry

The two providers use `hook_telemetry.jsonl`. They select the directory in this sequence without a write check:

1. `CODERAILS_HOOK_TELEMETRY_DIR`.
2. The parent of `CLAUDE_DISCIPLINE_LOG`, then the parent of `CODERAILS_DISCIPLINE_LOG`.
3. `PLUGIN_DATA`.
4. `~/.claude` for Claude, or `~/.coderails/codex` for Codex.

Before an append, a file larger than 1,000,000 bytes replaces `hook_telemetry.jsonl.1`.
The writer keeps only one previous log. Entries have no prompt, payload, or error text.

| Field | Meaning |
|---|---|
| `ts` | UTC timestamp in seconds |
| `hook` | Hook or child-call label |
| `cause` | Outcome type below |
| `exit` | Hook exit code, negative child exit code, or `null` if unspecified |
| `duration_ms` | Integer milliseconds in `run`. Other entries default to 0. |
| `open_fds` | Open descriptors for the writer, without the listing handle. `null` if unavailable. |
| `pid` | Writer PID. A child-signal entry gives the parent PID that wrote it. |
| Optional fields | Only `errno`, `signal`, `error` (class name of the error), and `diagnostic_hint`. There is no error message. |

The writer uses typed markers where the hook writes its output. The `mark_deny` function marks a denial. The `mark_block` function marks a Stop block.
It does not read message prose or use an external Sentinel component.

| Result seen by `hook_telemetry.run` or `note_child` | `cause` |
|---|---|
| Exit 0 with a block marker | `block` |
| Exit 0 with a deny marker and no block marker | `deny` |
| Exit 0 with no marker | `ok` |
| Exit 2 | `block` |
| Other explicit exit | `exit` |
| Uncaught `EMFILE`, `ENFILE`, `EAGAIN`, or `ENOMEM` | `resource` |
| Other uncaught error | `exception` |
| SIGTERM with a signal handler | `sigterm`, exit 143 |
| Negative child exit code | `native_signal`, with signal name and negative `exit` |

If the hook catches a resource fault and writes typed deny or block, it records `deny` or `block`. It does not necessarily record `resource`.
A `request_human_approval` block records `block`. There is no other cause for approval.
Exit 0 alone cannot show if a gate let an operation continue. Refusal words alone cannot show if a gate blocked it.

A `native_signal` entry reports that a child stopped. It cannot give the gated operation's result.
On macOS it adds a hint about the crash report location.
SIGTERM warns that the gate did not check the operation. A warning or signal does not prove enforcement.
SIGKILL and crashes can prevent the last entry.

### Stop traces and counters

The `graph_completion_guard/blocked/stop_row_missing` entry is a graph diagnostic record.
It shows that the check could not check loop end without a Stop row to consume.
The current typed Stop row is in `progress.json.stops[]`. Consumption does not write that refusal entry or prove loop end.

From the repository root, run the read-only counter:

```sh
python3 scripts/lib/stop_counters.py --since 2026-11-03T00:00:00+00:00
```

For all available entries, do not give `--since`.
The counter uses `CLAUDE_AGENTIC_LOOP_DIR` or `~/.coderails/agentic-loop`.
It reads `<root>/*/trace.jsonl` and `<root>/*/*/recovery-trace.jsonl`.
The output includes `stop_row_missing`, `stale_stop_row`, `convert_ok`, and a total for each `convert_refused_<code>`.

The counter counts occurrences of each code and deduplicates by `event_id` in each file.
Entries with no ID can count on their own. The counter skips malformed or unreadable entries.
These counts do not measure unique operations, completed loops, or elapsed time.

The `--since` option selects timestamps at or after the supplied ISO string. Use the same timestamp format.
The `--trace-json` option reads JSON from `measure_graph_alignment.py` on stdin and also reads recovery logs.
Do not use it with `--since`. The reader cannot select an earlier aggregate by timestamp.

### Timing and coverage limits

Codex starts a nine-second aggregate Stop deadline before it reads input. Hook registration gives ten seconds.
Lookup, inspection, Stop consumption, loop-end checks, status, and recovery share that deadline.
The status helper gives each child two seconds and all status work four seconds, subject to the earlier deadline.

Measure wall time for the full hook entry point.
For each trial, record the head and version, provider, input conditions, command, output, exit code, and wall time.
One trial below ten seconds cannot guarantee that all hosts finish in that time.
The `duration_ms` field does not count startup and teardown. It cannot give full wall time.

If a telemetry write does not succeed, the hook continues. Entries can drop, rotate, or interleave. Descriptor counts can be unavailable.
Missing entries cannot prove that the hook accepted an operation or did not run.
Compare typed output, telemetry, graph diagnostic records and data, and active registration before you interpret a result.

The same user owns these advisory files. Source or synthetic checks cannot prove installed trust, native-provider use, live-account operation, server enforcement, or native recovery.
Integrity opt-in and the publication gate have their own checks. See [integrity setup](INTEGRITY-GATE.md#turn-on-the-gate) and [publication limits](#limits).

Sources: [telemetry implementation](../hooks/scripts/lib/hook_telemetry.py),
[Stop counter](../scripts/lib/stop_counters.py), [Codex Stop guard](../packages/codex/hooks/scripts/graph_completion_guard.py),
[Codex hook primitives](../packages/codex/hooks/scripts/hook_common.py),
[notice timing](../hooks/scripts/lib/stall_notice.py) and [hook registration](../packages/codex/hooks/hooks.json).

## Limits

The same user that the gate constrains writes these entries. The gate does not read them for a decision.
They count gate calls. They cannot show a browser merge or a merge in a script the Codex hook cannot recognize.

This is a cooperating-agent safeguard. An agent with write access to `.coderails/workflow.config.yaml` can set `diff_manifest: off`.
The gate checks that edit as a diff only if the policy denies the path.
The default policy denies new or changed files at its own paths and the workflow config. The gate reads the resolved config of the local checkout.

A same-worktree loop data file can satisfy the metadata check with forged owner fields.
The Claude manifest hook runs without a config or transcript. The logs have no entries for raw Git operations, unmatched scripts or aliases, or browser merges.

A hook cannot pin the head or base of the next remote merge. The `merge.py` helper uses `--match-head-commit` for the head.
A log write error does not block the operation. Missing entries cannot prove a check did not run.
