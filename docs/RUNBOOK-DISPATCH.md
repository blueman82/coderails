# Graph dispatch and publication recovery

[Runbook](RUNBOOK.md).

## Typed state, verdicts and attestation (merge blocked by `attest_*`, eval verdict, hook state)

Use the [typed records and attestation guide](typed-state-runbook.md) for current codes and steps.

The shared parser in `scripts/lib/integrity_attestation.py` has the same bytes in `packages/codex/scripts/lib/`.
It owns parsing of `integrity=pass` and `sha=`. The `integrity_status.py` module for `merge.py` and the hook's `pr_merge_gate.py` fetch through `gh`.
They format messages from the closed code list. Codex uses `integrity_status.py` because it has no PreToolUse merge hook.

A historical root-owned daemon from `scripts/integrity-gate` did not import the parser.
In that setup, `attest_missing` or `attest_not_success` meant the daemon had given no status that shows success for the head.
Wait or push a new head. The `attest_wrong_creator` code meant `integrity_review.machine_user` differed from the status poster.
The `attest_not_bound` code meant the description had no full `integrity=pass sha=<head>` tokens. Do not bypass the check.

Run `python3 scripts/lib/state_counters.py [--since <ISO ts>]` for `attest_*`, `hook_state_unreadable`, `nudge_first`, `nudge_suppressed`, and `eval_verdict_<status>`.
The `pr_merge_gate/denied/<code>` entries use the session ID from the hook payload.
A test checks that the historical daemon's success description parses.

The `EvalVerdict{status, tamper_code}` status is one of `GO`, `VERIFICATION_LEVEL0`, `FROZEN`, `NO-GO`, `ABSENT`, `UNJUSTIFIED`, `UNSTAMPED`, `STALE`, or `TAMPERED`.
Callers use those fields and do not read `TAMPERED:<code>` text. A block at loop end logs `loop_state_guard/blocked/eval_verdict_<status>`.
The retro cost line uses `CostReport{state, message}` and logs `cost_report=<state>`.

Run `graph_readiness.py <progress.json> <node>`. It prints `{"ready": bool, "reason_code": ...}`. Exit code 0 means the node can run.
The codes are `ready`, `predecessor_pending`, `node_unknown`, `node_not_pending`, `graph_blocked`, `join_not_dispatchable`, and `state_unreadable`.
A missing script or output that is not JSON prevents a result. A readable refusal logs `graph_readiness/not_ready/<code>`.

The `state_unreadable` outcome has no session ID for logging.

Claude's `atomic_progress_update` and Codex's `graph_io.write` put `updated_at` in each `progress.json` write.
A refused change keeps the same bytes.

The `<loop dir>/<session>/hook_state.json` structure is `{schema_version, ordinals{absent_blocked}, arms[{hook,ordinal}], nudged{<hook>:true}}`.
This file supplies absent-state grace and nudge dedupe for `offload_push_guard` and `unregistered_loop_guard`.
Session `ab` does not equal `abc`. The hooks do not use `discipline.log` to make these decisions.

If the file is torn or unavailable, it cannot release grace. The hook logs `hook_state_unreadable`.
A first Stop in a session can give outcome `missing`. Outcome `torn` indicates an error.
A torn file also suppresses the nudge with the same code, so an advisory does not run again without a record.

Nudges log `nudge_first` or `nudge_suppressed`. For `torn`, remove the file by hand. The hook cannot repair it.

The session user can edit this plain file. An agent with Bash or Write can make it before the hook does.
An `ordinals.absent_blocked` value equal to the current invocation count can release grace without a prior block.
A value `nudged.<hook>=true` can suppress a nudge. The controls prevent accidental repetition and depend on the agent to follow the rules.

Codex has no `loop_state_guard`, `offload_push_guard`, or `unregistered_loop_guard` in `hooks.json`.
The hook data, `EvalVerdict`, and `CostReport` behavior above is for Claude. Codex uses the shared attestation parser and `updated_at` stamp.
The `mine_hook_blocks` function counts the log's full `session=` token. For a switch to diagnostic entries in Phase 6, all gates must write entries.

## Graph refused with `spec_*`, or `instantiate` refused

See [graph specification recovery](RUNBOOK-GRAPH-SPEC.md).

## A procedure script (wiki_lint, verify_merged, merge --describe, memory_dir, detect_test_command, check --json) answered unexpectedly

- The command `wiki_lint.py stale --repo R --vault V` uses `wiki_stale_days` for candidate age. The default is 30 and the value 0 is correct.
  A source commit more than 7 days after the page date shows possible drift.
  If there is no comparable repo source, a candidate is stale with `basis: date_only`. This result also gives `no_repo_sources`.

  The `data_gaps` field gives unresolved sources, missing commit dates, missing `last_updated`, and `no_repo_sources`.
  A missing directory gives exit 2 with `repo_unavailable` or `vault_unavailable`.
  An incorrect threshold gives `wiki_stale_days_invalid`. Correct the input and run again. The check skips point-in-time and structural directories.

- The command `verify_merged.py <PR> [--grep STR --path P]` exits 0 only after it checks `content` or `merge-commit-ancestry`.
  The code `pr_number_invalid` means the PR number is not a positive decimal. The code `origin_repo_unresolved` means the tool cannot use the URL for `origin`.
  The code `repo_mismatch` means `GH_REPO` names a different host or repository.
  Other codes include `gh_failed`, `not_merged`, `merged_at_missing`, `fetch_failed`, `merge_commit_unreachable`, and `content_absent`.

  The `content_preexisting` code means the text predates the merge. The `content_check_failed` code means a Git error or a missing parent.
  The `content_check_required` code means there is no search text and no two-parent ancestry.
  Use `--grep` for a squash. Select new search text or put back missing history.

  For a parsed PR number, the script tries to write `verify-merged/<ok|refused>/<reason>`.
  An option-shaped PR number such as `--comments` gives a JSON `pr_number_invalid` refusal before parsing and writes no entry.
  Entries feed `trace.by_reason` and the `verify-merged` counter.

- The command `merge.py --describe` prints JSON from `VERIFY_STAGES` and then `publication_gate.CHECKS` without a remote call.
  Conditional steps can skip. A refusal stops subsequent steps. Target, auth, status, and approval checks run first.

- The command `memory_dir.py [--provider claude|codex]` gives a path without checking the directory.
  It resolves the path and changes each non-alphanumeric character to `-`.
  The `detect_test_command.py` command gives null if it finds no candidate or more than one. Callers get approval before they write config.
  An unavailable project gives exit 2 with `directory_unavailable`. An empty or malformed npm test script is not a candidate.
  Correct input and run again.

- The command `scripts/quality/check.py --json` prints `{scanned, findings[{path,line,message}], external_ok}`. Tool output goes to stderr.
  The two feedback hooks report check results, unusable JSON, nonzero checker exits, and external errors with bounded diagnostics.
  The Codex adapter uses only built-in checks. The value `external_ok: true` means it tried no external tools.

- Skills select these helpers. Verification writes a diagnostic entry. The checks trust same-user `gh`, clones, dates, sources, and config.
  Wiki lint is advisory. A page on base and no page at the first parent cannot prove that the PR author wrote it.

## Source-bound dispatch upgrade and rollback

This procedure applies to the two provider installations.
Before you activate the source-bound dispatch and publication runtime, finish active loops with the runtime that made them.
Finish worker publication and the end-of-loop checks. Do not upgrade a live implementation or publication wave.

A previously assigned unit can have no `source_manifest_sha256`. The new publication check refuses it with `publication:source_manifest_mismatch`.
The `assign-worktree` command accepts pending units only. It cannot repair an active assignment.
The reader can read a previous dispatch record without showing that its unit can publish with this runtime.

Start new loops on the new runtime only after previous loops finish.
Keep each loop's matching runtime in an isolated checkout with its loop data, dispatch history, proof, standing instructions, and retrospective artifacts.
Historical data can also use an earlier reader for loop end or retro checks. See the [historical recovery rules](RUNBOOK.md#memory-degraded-muninn-authoritative).
The pre-upgrade runtime cannot necessarily check all saved histories.

After a loop stores the expanded source and lesson contracts, older closed-field readers can refuse them.
Keep the matching newer runtime for publication, loop end, and subsequent checks or retry.
A rollback for future work does not change existing records.

Do not add hashes by hand, relabel units, set the status again, or edit frozen records.
Do not use `graph.py convert` as an automatic migration for missing source bindings.
This procedure has no automatic migration or approval to bypass publication checks.

Native and global installation stays on HOLD until checks in operation verify drain and retention of the matching runtime independently.
Source inspection, local tests, and a commit gate that succeeds do not qualify installed upgrade, rollback, or live-provider loops.

Assigned-source inspection refuses a resolved Git `filter` attribute before status can invoke a `clean` or `process` filter helper.
A filter or LFS config with no use does not cause a refusal.
The check does not disable conversion and use raw bytes as the filtered representation at HEAD.

The refusal also includes explicit `-filter`. Git attribute output cannot tell that value from the literal driver name `unset`.
An actual `!filter` reset has no resolved filter row.
Inspection does not change attributes, filter config, or index metadata.

Keep the trusted checkout and config stable during inspection.
These reads cannot prove an atomic snapshot or stop concurrent filesystem changes from the same user.
If the reader refuses a filtered checkout, use a source workflow that the owner has checked.
The reader has no automatic filter migration or bypass.

The reader also refuses Git submodule entries before status can examine a nested checkout and run its filters.
It does not ignore a dirty submodule or claim to have checked the nested source.

## Dispatch refused: `dispatch_*` or `role_mismatch`

- Symptom: `loop_dispatch_guard` denies a spawn in a graph-bound session, or `begin-wave` or `graph.py authorize-dispatch` fails.
  The hook sees Claude `Agent` and Codex `spawn_agent`. This Codex host reports `collaborationspawn_agent` to hooks.
  The hook message names the cause. The loop's `recovery-trace.jsonl` gives `authorize-dispatch/refused/<code>` or `authorized/dispatch_authorized`.

- Query: Run `python3 scripts/lib/dispatch_counters.py [--since <ISO ts>]` for `dispatch_authorized` and all refusal codes.

- If the Codex hook cannot make or write its temporary message file, it refuses with `dispatch_message_unavailable`.
  It records the code in `discipline.log`. Repair local scratch storage and retry.

- If the hook input or local check causes an unexpected error, the hook refuses with `dispatch_hook_error`. It logs the code in `discipline.log`.
  A plaintext envelope first line above 8192 characters gives the same refusal.
  Codex config discovery, graph discovery, and graph commands share seven seconds.
  A stalled Git lookup or held graph lock cannot use the full ten-second hook limit.

  The hook uses strict reads for config and graph discovery.
  It accepts an ordinary spawn with correct config or no config and no graph data.
  A session ID that fails the safety check, completed graph, lookup error, or multiple fallback graphs causes a refusal.
  Examine hook input and the local runtime. A refused spawn has no authorization.

| Code | Check and procedure |
|---|---|
| `dispatch_missing_envelope` | The first-line `CODERAILS_GRAPH_DISPATCH` envelope has no value, uses a previous format, or has a format error. Copy `prompt_prefix` from `plan` or `begin-wave`. A plaintext Codex spawn uses this prefix. A native hook message with an encrypted prompt uses the issued `task_name` and call ID. |
| `dispatch_unknown_id` | The command did not issue that ID. Run `begin-wave`. |
| `dispatch_foreign` | The session, loop, node, wave, or Codex `task_name` differs from the record. |
| `dispatch_stale_revision` | The envelope predates the current graph revision. Run `begin-wave` again after `recover-wave`. |
| `dispatch_attempt_mismatch` | The saved try does not agree with its dispatch ID or with the node's next try. Examine the graph data and recover the wave. |
| `dispatch_replayed` | A spawn used this ID. Use only one spawn for each ID. Retry in a new wave. |
| `dispatch_call_id_missing` | The native hook message with an encrypted prompt has no usable call ID. Check the native hook payload. |
| `dispatch_contract_altered` | The saved contract differs from its digest or has no mandatory field. Someone edited the graph data. Start the wave again through `recover-wave`. |
| `dispatch_sections_missing` | The prompt's contract block has edits or does not occur. Copy `prompt_sections` verbatim. |
| `role_mismatch` | Use `coderails:<role>` for a controlled scout in Claude and `agent_type: <role>` in Codex. Other roles accept their own type or `general-purpose` in Claude. In Codex they accept their own type or no `agent_type`. A different native role such as `explorer` causes a refusal. A graph-bound Claude `Agent` call with no `subagent_type` also causes a refusal before native dispatch. |
| `dispatch_state_unconverted` | The `state_minor` is below 3 or the contract or context cutoff is malformed. For previous graph data, run `graph.py convert --check`, then `convert`. Examine malformed current data without editing frozen records. Conversion refuses an open wave with `convert_refused_active_wave_in_flight`. |
| `dispatch_context_mismatch` | Typed mandatory skills or checks differ from the registered node and unit facts. Run `recover-wave` and use the new `prompt_sections`. Do not edit the saved record. |
| `dispatch_publication_mismatch` | The saved worker command names a different unit, push script, or loop data path. Use the `publication_command` from `begin-wave` without changes. |
| `dispatch_unauthorized` | Claude `record-wave` or the loop end check found a bound spawn without consumption by the PreToolUse guard. The hook did not see the spawn. Use `recover-wave` and dispatch through the guard. |

A bad `add-unit --model-role` value gives `add_unit_refused_bad_field`. Use `fast-mechanical`, `default`, or `frontier`.

### Dispatch check switch

Set `CODERAILS_GRAPH_DISPATCH=off` in the hooks and graph CLI to skip the contract hash, rendered sections, role, and single-use checks.
The values `0` and `false` also work. The default is ON. Unset the value to turn the checks back on.
Use this switch only to unblock a loop with a bad contract or an uninstalled plugin agent.

A graph-bound spawn must have a current v2 envelope from `begin-wave`, the recorded Codex task name, and frozen evals.
Native records must agree on node, wave, and try. The hook refuses missing and v1 envelopes.

Graph-bound Claude Agent calls must have a nonempty `subagent_type`. Use `general-purpose` for roles without the control.
The hook cannot bind a missing type to native records. Ordinary Agent calls with no graph do not change.
Each spawn that the hook accepts logs `authorize-dispatch/reported/dispatch_check_off`.

### Codex evidence rollout

The default for `CODERAILS_A6_EVIDENCE_WRITE` is OFF.
With OFF, the new reader checks previous and new refs, and `reject-invalid-dispatch --report-only` works.
It refuses to write invalid-dispatch or encrypted-message records without changes to `progress.json`.
The dispatch switch keeps its previous behavior without a receipt.

Install and trust this reader before changing the setting.
Use `inspect` on active previous graphs and `verify-completion` on completed graphs before you set the value to `on`.
After a write of one of the new ref structures, OFF stops more writes. Keep this reader installed for loop end and subsequent checks.
The previous reader cannot check those histories, for active or completed loops. A safe rollback cannot use that reader.

When writes are on, plaintext authorization binds native call IDs differently before the first new ref is written.
The owner must accept this reader requirement before they set the value to `on`.

### Dispatch coverage limits

A controlled scout can run only if the plugin agent is installed. The hook refuses an uninstalled scout without downgrading it.
The sandboxed Bash launcher has no agent type. Only the `Agent` and `spawn_agent` paths check the role (handoff H3).

Single use uses PreToolUse `tool_use_id` when the payload has one (unverified). With no ID, it uses a consumed flag.
A hook retry without an ID reads as replay. Codex role containment checks only `agent_type == role`, without proof of shell or MCP settings.
The session user can edit `progress.json` and the sections. The controls find unintended changes and substitutions for an agent that follows the rules.

The envelope shows authorization and that the rendered block occurs in the prompt.
Other prompt text can be different. The `write_scope` field only supplies prompt text. It cannot apply the write limit.

Only six roles have role containment: `deploy-safety-reviewer`, `design-scout`, `disposition-scout`, `preflight-scout`, `security-reviewer`, and `source-auditor`.
The `spec-reviewer` has an empty tool list. The `shell.raw` roles are `docs-auditor`, `wiki-writer`, and `proof-author`.
These roles and nodes with no `agent_role` (default `loop-worker`) can run with full tools.
Claude accepts explicit `general-purpose`. Codex accepts no `agent_type` or the role's own type.

The matchers `Agent`, `spawn_agent`, and `collaborationspawn_agent` check entry only.
Claude `SendMessage` and Codex resume or `send_input` can send a new prompt to an active or finished worker without an envelope.

The two providers check current-wave dispatches again at `record-wave` and loop end.
Codex uses a native `spawn_agent` function-call message, its v2 record, role, and consumed authorization.

Current native Codex calls give the hook an encrypted worker prompt. The hook refuses before launch with `dispatch_prompt_unverifiable`.
Do not retry a native graph spawn. Use the checked local Codex OAuth graph driver after you install it. Until then, stop graph dispatch.

An earlier entry with only a task name cannot bind a contract-era wave.
Claude checks the native Agent call against a non-null hook `tool_use_id`.
With no ID, it keeps the consumed flag and checks one spawn for each ID. It cannot prove the call ID.
Historical dispatches from before the contract use their previous verification rules.
A Claude hook can let a spawn proceed if it times out before denial (10 s in `hooks.json`).

## Disposition refused, compat findings blocked a merge, or a worker status stopped the loop

- The `add-unit` command gives `add_unit_refused_disposition` for an incorrect field combination.
  With `--disposition preserve-compat`, give a nonempty `--named-blocker` and `--removal-ticket`.
  With `--disposition clean-break`, give no blocker or ticket flag. A blocker or ticket without `--disposition` causes a refusal.

  The command writes `work_units[u].disposition = {kind, named_blocker?, removal_ticket?}`. The dispatch contract uses it.
  Run `graph.py disposition-audit <state>` for each unit's type. It exits 1 for a hand-edited unit that broke the rule.
  The `complete` and `verify-completion` commands refuse the same unit in the two providers. The check is on by default and has no switch.

- For a pending unit without a retirement decision, run:

  ```
  graph.py set-unit-disposition <state> --session S --loop-id L --revision R --unit N --disposition preserve-compat --named-blocker TEXT --removal-ticket ISSUE --source-ref URL
  ```

  For `clean-break`, give no blocker or ticket. Use the current revision with no active wave.
  The command records the source ref and a new revision. It refuses duplicate `--disposition` flags or a second saved decision.
  Examine the source and select the value before you run the command. The command cannot prove that the source justifies the value.

- The `/coderails:merge` command gives `compat_findings_nonzero` if an inspection artifact has `disposition=clean-break` and `K > 0`.
  Its second line is `<!-- coderails-compat-findings v1 pr=N head_sha=S count=K disposition=D -->`.
  Build the line with `post_review.py compat-line <pr> <sha> --count K --disposition D`.

  Remove the compatibility code, make a new head SHA, and post a new inspection. Or use `preserve-compat` for the unit with a blocker and ticket.
  A passing inspection on the same SHA cannot override a previous refusal line.
  A current line with that prefix and an incorrect structure gives `compat_findings_malformed`.

  Legacy inspection artifacts can have no compatibility line. The current-head v1 inspection artifact is mandatory.
  The Codex direct merge hook uses the same check when the mandatory reviewer checks are off.
  The v1 marker that the root-owned integrity daemon reads stays unchanged.

  A refusal line for the head wins. The `merge.py` command has no loop session. It gives a code on stderr without a diagnostic log entry.

- Limits: The reviewer gives `K` and `D` by judgment. The same user can write the line, so the check relies on the reviewer to follow the rules.
  The gate reads the PR artifact. It does not compare `D` with `work_units[u].disposition`.

- The `record-wave` command gives `worker_status_<code>` for an incorrect typed result with a `status` key.
  The codes are `not_an_object`, `unknown_status`, `missing_field`, `unknown_field`, and `bad_field`.
  It rejects the full report and keeps the same bytes in `progress.json`.
  Correct the worker result to follow `scripts/worker_status.py` and record again.

  If a dispatch has `final_report_required`, an incorrect or missing `final_report` in a `done` result gives `final_report_invalid`.
  The schema is `final_report {claims: [{text, label, source?}], did_not_verify: [{item, tag, reason}]}`.
  Claims must be nonempty, a `verified` claim cites a source, and the tags are `resolved|unverifiable`.
  The two types of refusal log `record-wave/refused/<code>`.

- For a correct typed status, the command adds `decision_pending` to `worker_statuses[]` and records an unsuccessful try.
  At the retry limit, it keeps the terminal slot available behind that decision, so an answer can continue the node.
  One write records the status and one typed Stop row.

  The row uses `awaiting-input/needs_human_input` for `NEEDS_DECISION`.
  It uses `approval-gate/needs_approval` for `OUTSIDE_SCOPE` and `IRREVERSIBLE_ACTION`.
  If a wave has the two types, approval goes first. The Stop guard releases the row one time.

  Use `to_decision_request()` to get a human reply. Then record the answer:

  ```
  graph.py record-decision <state> --session S --phase P --decision D --chosen C [--flip-condition F] --worker-status-seq <seq>
  ```

  The command adds one typed row to `decisions_absorbed` and marks the status resolved.
  Run `python3 scripts/lib/worker_counters.py` for `pending_statuses` (rows with `decision_pending`) and `decision_recorded`.

- The `record-decision` command gives `record_decision_refused_<foreign|field|state|status|chosen|human>` for an incorrect input.
  The session must own the graph, flag values must have text, and `decisions_absorbed` must be an array of objects.
  The `--worker-status-seq` flag must name a pending status. The command refuses an unknown, resolved, duplicate, or malformed status.

  The `--chosen` value must be an option for a `NEEDS_DECISION` status.
  For `OUTSIDE_SCOPE` or `IRREVERSIBLE_ACTION`, supply `--human-answer`.
  A refusal does not write or increase the revision.

  Without a linked status, `phase`, `decision`, and `chosen` use free text. They have no enum or check against the graph.
  Hand-appended `{phase, decision}` rows stay readable and unnumbered.
  The caller supplies `--session` and `--human-answer` without authentication. An agent with the same user ID can forge a reply or edit the rows.
  Only the orchestrator uses `--human-answer`, and only after the human replies.

- The check verifies structure. A worker can write claims the check cannot prove.
  Only dispatches with a begin-wave record must have the report. Data from before conversion use the previous behavior.
  The `check_confidence_labels` and `check_verify_loop` hooks stay advisory for the orchestrator's text.
