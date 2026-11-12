# Runbook: hook and trace observability

The `hooks/scripts/lib/trace_row.py` writer appends advisory entries to `<agentic-loop dir>/<session_id>/trace.jsonl`.
It writes one `event_id` for each operation. A write error cannot block the operation.
The `autonomous_gate.py` hook uses the same session directory with or without a loop.

An entry has `schema_version`, `event_id`, `session_id`, `loop_id`, `ts`, `command`, `outcome`, `reason_code`, and SHA-256 hashes in `inputs`.
The `loop_id` is null when there is no loop. Gate decisions do not use these entries.
Counters deduplicate by `event_id`, skip torn lines, and use `command/outcome/reason_code` as the tally key.

Read the diagnostic log counters with:

```
python3 scripts/measure_graph_alignment.py --root . --json | python3 -c "import sys,json;print(json.load(sys.stdin)['trace'])"
```

## Native observation report

- Run `python3 scripts/observation_report.py <cohorts.json>`. See the cohort fields and count definitions in [native session observations](OBSERVATION-REPORT.md).

- Exit code 0 gives a JSON metadata report. Exit code 2 gives an input or file error on stderr.
  The report does not change the cohort, source files, or diagnostic log cache.

- If there is a hash or binding error, keep the input files and stderr message.
  Check the declared file hashes, provider, session, parser version, and source refs.
  Put back the initial bound files or prepare a new declared cohort from the new source files.
  Do not change a hash only to suppress the refusal.

- Observation counts use eligible sessions and native reader entries.
  If a count differs from the dashboard, examine the IDs and source refs in the bound data.
  The command has no ledger of its runs or refusals. There are no dedicated diagnostic counters for its stderr codes.

- The publication checks use their own callers, log entries, and counters.
  See [workflow gate measurements](workflow-gates-measurement.md) for default-ON publication checks.
  See [integrity gate instructions](INTEGRITY-GATE.md) for the opt-in integrity status, activation steps, and trust limits.
  These records apply to the named publication control. They cannot show that the observation report ran or count its refusals.

## Generated hook and memory reasons

The first table gives a step for each control category.
The second gives codes from the named source files and the memory code catalog.
The diagnostic log keeps the full code. Hook telemetry keeps a broader result such as `deny` or `block`.
Read the instructions for that record. Dynamic codes can also occur.

<!-- hook-reasons:start -->
| Control | Category | Step |
|---|---|---|
| `action_authority_gate` | operation authority gate | Use the authority path set in config for this operation and session. |
| `agent_model_routing_nudge` | agent model routing nudge | Select a model role that fits the task when the suggestion is useful. |
| `agent_only_gate` | agent only gate | Send source work to an agent or use the allowed workflow command. |
| `check_confidence_labels` | check confidence labels | Add the correct confidence label to each claim that needs one. |
| `check_verify_loop` | check verify loop | Complete the verification section and mark each unresolved check. |
| `comment_citation_gate` | comment citation gate | Write the durable rule in the comment without a session label. |
| `autonomous_gate` | autonomous input gate | Use the typed authority command, or continue after the authority expires. |
| `destructive_bash_gate` | destructive bash gate | Use a safe command that avoids the blocked operation. |
| `enforce_pr_workflow` | PR workflow gate | Run `review-pr`. Post the records for the current PR head. |
| `graph_completion_guard` | check for graph closeout | Resolve the graph status and record a stop result that meets the rules. |
| `inject_bootstrap` | add bootstrap context | Check the plugin root and hook registration if there is no context. |
| `inject_context` | add prompt context | Check the prompt hook registration if there is no context. |
| `loop_dispatch_guard` | loop dispatch guard | Use the current owned graph dispatch envelope and role. |
| `loop_stall_guard` | loop stall guard | Record the required stop and complete unresolved graph work. |
| `loop_state_guard` | check for loop status | Put the owned graph and graded loop eval records back. |
| `no_edit_on_main` | primary branch edit gate | Move the source edit to a feature branch. |
| `offload_push_guard` | offload push guard | Keep the push in the authorised workflow. |
| `pr_publication_gate` | pr publication gate | Complete the required `review-pr` and eval steps for this PR head. |
| `quality_feedback` | quality feedback | Read the quality result and correct the source problems it lists. |
| `remember_inject_cap_guard` | remember inject cap guard | Set the limit for added memory text or use the documented opt-in patch. |
| `reviewer_bash_allowlist` | reviewer bash allowlist | Use an allowed read-only command or a tool that your grant permits. |
| `subagent_identity_gate` | subagent identity gate | Start the agent with a native type that the graph can identify. |
| `test_gate` | test gate | Correct the tests with errors before you commit. |
| `unregistered_loop_guard` | unregistered loop guard | Record the active agentic loop graph before you send more work. |
| `verification_volume_ceiling` | verification volume ceiling | Use focused tests after the allowed full-suite runs. |
| `voice_announce` | voice announce | Read the loop status if you did not get a spoken notice. |
| `wiki_taxonomy_gate` | wiki taxonomy gate | Write the page in a directory that the wiki schema permits. |
| `worker_containment_gate` | worker containment gate | Use the required containment acknowledgement or a low-risk path. |

| Source | Code | Step |
|---|---|---|
| `hooks/scripts/action_authority_gate.py` | `action_authority_failed_open` | Use the authority path set in config for this operation and session. |
| `hooks/scripts/autonomous_gate.py` | `authority_corrupt_ignored` | Use the typed authority command, or continue after the authority expires. |
| `hooks/scripts/destructive_bash_gate.py` | `authority_denied_destructive_shell` | Use a safe command that avoids the blocked operation. |
| `hooks/scripts/autonomous_gate.py` | `authority_deny` | Use the typed authority command, or continue after the authority expires. |
| `hooks/scripts/autonomous_gate.py` | `authority_expired_allow` | Use the typed authority command, or continue after the authority expires. |
| `hooks/scripts/autonomous_gate.py` | `authority_phrase_ignored` | Use the typed authority command, or continue after the authority expires. |
| `hooks/scripts/subagent_identity_gate.py` | `bash_agent_type_absent` | Start the agent with a native type that the graph can identify. |
| `hooks/scripts/verification_volume_ceiling.py` | `ceiling_exceeded` | Use focused tests after the allowed full-suite runs. |
| `hooks/scripts/verification_volume_ceiling.py` | `ceiling_legacy_migrated` | Use focused tests after the allowed full-suite runs. |
| `packages/codex/hooks/scripts/loop_dispatch_guard.py` | `codex_native_worker_uncontained` | Use a parent Codex sandbox that contains the worker. |
| `hooks/scripts/check_confidence_labels.py` | `confidence_label_missing` | Add the correct confidence label to each claim that needs one. |
| `hooks/scripts/subagent_identity_gate.py` | `config_rejected` | Correct .coderails/workflow.config.yaml and retry. |
| `hooks/scripts/worker_containment_gate.py` | `containment_ack_receipt` | Use the required containment acknowledgement or a low-risk path. |
| `hooks/scripts/worker_containment_gate.py` | `containment_ack_required` | Use the required containment acknowledgement or a low-risk path. |
| `hooks/scripts/worker_containment_gate.py` | `containment_fallback_low_risk` | Use the required containment acknowledgement or a low-risk path. |
| `hooks/scripts/worker_containment_gate.py` | `containment_gate_error` | Use the required containment acknowledgement or a low-risk path. |
| `hooks/scripts/worker_containment_gate.py` | `containment_unavailable` | Use the required containment acknowledgement or a low-risk path. |
| `hooks/scripts/action_authority_gate.py` | `denied_gate_error` | Use the authority path set in config for this operation and session. |
| `hooks/scripts/lib/hook_state.py` | `hook_state_unreadable` | Put the owned hook status file back. Then retry. |
| `hooks/scripts/lib/hook_state.py` | `nudge_first` | The hook recorded the first nudge. Continue the required workflow. |
| `hooks/scripts/lib/hook_state.py` | `nudge_suppressed` | The earlier nudge applies. Check the loop status. |
| `hooks/scripts/action_authority_gate.py` | `receipt_consumed` | Use the authority path set in config for this operation and session. |
| `hooks/scripts/loop_stall_guard.py` | `stale_stop_row` | Record the required stop and complete unresolved graph work. |
| `packages/codex/hooks/scripts/graph_completion_guard.py` | `stop_row_missing` | Record the current Stop result before the loop completes. |
| `hooks/scripts/check_verify_loop.py` | `verify_loop_missing` | Complete the verification section and mark each unresolved check. |
| memory | `bad_record` | The record has an error in its type, scope, tag, date, claim text, or loop ID. A claim must have text, and loop scope must have a loop ID. |
| memory | `cite_bad_approval` | the approval must be a short user prompt (80 chars or fewer) that directly follows the reply it answers. |
| memory | `cite_not_own_session` | The ref points to a different session. Only a user prompt from the calling session (`--session`) can authorize the write. |
| memory | `cite_not_user` | The citation must point to a user prompt. Cite the owner's words or use the approved-reply syntax. |
| memory | `cite_too_short` | A quote-only citation must have 12 to 300 characters. Use more text from the user's prompt or cite the approval with its reply. |
| memory | `cite_unresolved` | The ref did not occur in `muninn session <root>`, or the approval has no preceding reply. Check the ref. |
| memory | `decision_blank_decision` | A decision must have text. The command did not write a record. |
| memory | `decision_blank_phase` | a decision needs a non-blank phase (for example 2.5). |
| memory | `decision_invalid_chain` | The decision chain has damage. Examine and preserve the loop data before you sync again. |
| memory | `decision_state_error` | The command could not read, check, or lock the loop data. It did not write a record. |
| memory | `decision_sync_unknown` | Muninn can have received the decision. Examine the store before you retry by hand. |
| memory | `decision_wrong_loop` | The loop changed after the caller read it. Read the current loop ID before you record the decision. |
| memory | `decision_wrong_revision` | The graph changed after the caller read it. Read the current revision before you record the decision. |
| memory | `decision_wrong_session` | The loop belongs to a different session. Record the decision only from the session that owns the loop. |
| memory | `graph_unavailable` | `graph.py summarize` or `graph.py inspect` did not succeed for this graph. The done and next-step lists are empty. Run the command by hand and read stderr. |
| memory | `handoff_state_unreadable` | `handoff_derive` could not read the loop's `progress.json`. Supply the path to that file. |
| memory | `handwritten_protected` | The target has no generator marker and is hand-written. Write the view to a new path. |
| memory | `learning_conditional_use_unsupported` | The Note has conditions for use or expiry. Legacy dispatch, promotion, and render cannot check those conditions. Keep the metadata. Do not use the Note unconditionally. |
| memory | `learning_evidence_mismatch` | The saved record identity, selector, scope, or source window differs from the binding. |
| memory | `learning_form_unsupported` | This reader reads Notes only. It cannot use Guides. |
| memory | `learning_no_change` | The saved task ended without a change to knowledge. No Note was written. |
| memory | `learning_no_matching_record` | The completed task gave no active Note for this task and text. Examine the receipt and Notes. |
| memory | `learning_pending` | Muninn accepted the learning task. Keep its R_ ID and use it to check the same task again. |
| memory | `learning_project_unavailable` | The calling project directory is unavailable. Do not use the graph key. |
| memory | `learning_quote_mismatch` | The saved excerpt differs from the source in the public quote check. Do not cite it. |
| memory | `learning_read_limit` | The read exceeded a time, reply, record, or source limit. It did not give all results. |
| memory | `learning_receipt_unavailable` | The learning task has no committed receipt that this reader can use. Muninn can accept the task without writing a Note. |
| memory | `learning_record_ambiguous` | More than one receipt matches this K-id and revision. No learning task was selected. |
| memory | `learning_record_changed` | Listed and shown current revisions differ. Read again with the same binding. |
| memory | `learning_record_expired` | The current Note reached its expiry time. Do not use it. |
| memory | `learning_request_failed` | The saved Muninn task did not finish successfully, or it was cancelled. Examine it with `muninn learn show R_ID`. |
| memory | `learning_request_mismatch` | The binding and the learning task differ in project, task, source window, or receipt identity. |
| memory | `learning_request_unknown` | Muninn can accept a learning task without giving its R_ ID. Examine `muninn learn list`. Do not send the task again. |
| memory | `learning_selection_unavailable` | An E-id, ref, hash, or excerpt is necessary but unavailable. Do not cite this Note. |
| memory | `learning_source_authority` | Use only live, primary, unflagged, unredacted prompts directly from the owner as sources. Current Muninn has no `normal` or `restricted` classes. Do not infer a class. |
| memory | `learning_source_changed` | A physical source or its saved provenance changed. Do not cite it. |
| memory | `learning_source_unavailable` | A necessary live source file is unavailable. Do not cite it. |
| memory | `legacy_missing` | There is no hand-written `standing-orders.md` to import. The file may not be there, may have no text, or may come from a generator. |
| memory | `legacy_parse_error` | The local legacy input has an entry with missing data, an ambiguous meaning, or a collision. Correct that entry and run `import-legacy` again. Keep the initial file. |
| memory | `legacy_uncited` | The legacy import has no saved selection for the current learning task. Keep it uncited. |
| memory | `lesson_not_current` | The saved learning task has no current Note that meets its rules. Examine its saved receipt. A caller quote cannot give it authority. |
| memory | `memory_backend_invalid` | Set `memory.backend` to `muninn` or `off` in `.coderails/workflow.config.yaml`. |
| memory | `memory_backend_off` | The workflow config sets `memory.backend` to `off`. To write typed memory, set it to `muninn` or remove the key. |
| memory | `muninn_absent` | Install `muninn` and put it on `PATH`. The Markdown path cannot serve as a fallback. |
| memory | `muninn_bad_output` | The Muninn reply does not agree with the learning task or the current Note rules. Examine the output. |
| memory | `muninn_error` | Muninn gave a nonzero exit code or JSON that cannot be read. Run the same `muninn know ...` command again and read stderr. |
| memory | `muninn_old_ledger` | The installed Muninn command has no learning tasks, or this record has only an earlier K-id. Legacy bindings cannot establish the source of the current learning task. |
| memory | `muninn_schema_incomplete` | The D4 adapter expects retired v2 columns or tables. Examine the current store with `muninn doctor`. Then redesign the adapter. |
| memory | `muninn_schema_old` | The D4 adapter expects retired schema v2. Current Muninn uses schema v1. Do not migrate the store to v2. |
| memory | `muninn_store_missing` | There is no Muninn store at `$MUNINN_HOME` or `~/.local/share/muninn`. Run `muninn ingest` one time. |
| memory | `muninn_timeout` | Muninn took more than 10 seconds. Run `muninn know list` by hand and check the store locks. |
| memory | `no_user_cite` | The local diagnostic has no checked citation from the current owner. A caller quote cannot prove the learning task. |
| memory | `order_already_ticked` | The tick skipped this session and logical loop because the count includes them. |
| memory | `order_bad_id` | Use the format `[a-z0-9][a-z0-9_-]{0,119}` for the standing instruction ID. |
| memory | `order_blank_field` | A standing instruction must have text for the problem and the lesson. The command did not write an entry. |
| memory | `order_chain_broken` | Someone edited `orders.json` by hand. The hash chain names the entry. Use a saved copy or examine the named entry. To seal the entry again, record it with `orders.py`. |
| memory | `order_id_collision` | That ID names a different problem or scope. Use the ID for this entry or make a new one. |
| memory | `order_lesson_too_long` | The collapsed lesson has more than 500 characters. Write a shorter complete claim. Do not truncate it. |
| memory | `order_loop_ineligible` | The owned graph or work units did not finish or have stopped. Complete the required work. |
| memory | `order_loop_unknown` | There is no source at `<repo-key dir>/<session>/progress.json`. Supply the `--session` that owns it and the logical `--loop`. |
| memory | `order_not_complete` | The prepared data is for future use. Apply recurrence or aging only after the owned `progress.json` records `complete`. |
| memory | `order_not_found` | There is no entry with that ID in `orders.json`. Check the ID with `orders.py lessons`. |
| memory | `order_pending_teardown` | The saved loop is complete, but the local update or its observation did not succeed. Retry `tick` with the same source binding. |
| memory | `order_retro_validator_unavailable` | Schema 3 retros use the matching `retro_check` validator. Install it before graduation. |
| memory | `order_source_invalid` | The `progress.json` file, prepared data, or observations have a format error. Put the correct checked source files back. |
| memory | `order_source_mismatch` | The prepared source or hash is out of date. Before the loop ends, run `prepare --refresh-from-sha256` with its current `evidence_sha256`. |
| memory | `order_state_error` | The command could not read, lock, or write the standing instructions, prepared data, or receipt. Check the repo-key directory, `orders.lock`, and `teardown.jsonl.lock`. |
| memory | `order_wrong_session` | The source directory, session, or logical loop does not belong to this operation. Use the directory and IDs that own it. |
| memory | `refused_approval_needs_reply` | For a short approval, also cite the reply it answers. Use `--approval REF`. |
| memory | `refused_bad_contradicts` | There is no K-id for the contradiction. |
| memory | `refused_bad_kind` | Muninn does not accept this record type. |
| memory | `refused_bad_loop_scope` | The loop ID has an error, or the caller used `--global` with loop scope. |
| memory | `refused_bad_supersedes` | There is no K-id to supersede, or the K-id is out of date or has a different scope. |
| memory | `refused_bad_tags` | Use tags with the format `[a-z0-9_-]{1,32}`. |
| memory | `refused_bad_valid_until` | valid_until must be a future ISO date. |
| memory | `refused_no_caller_session` | quote-only writes need CLAUDE_CODE_SESSION_ID or CODEX_SESSION_ID in the environment. |
| memory | `refused_not_citable` | The citation points to a subagent thread. Only the orchestrator session can write typed records. |
| memory | `refused_not_found` | The ref does not resolve. Run `muninn ingest` and check the ref. |
| memory | `refused_other` | Muninn refused the write with a code this catalog does not list. Read `refused_<code>` and the Muninn docs. |
| memory | `refused_preference_needs_user` | a preference must cite a user prompt. |
| memory | `refused_quote_length` | A quote must have 12 to 300 characters. A shorter quote must be the full approval prompt. |
| memory | `refused_quote_not_found` | The quote differs from the cited text. Copy the source text verbatim. |
| memory | `refused_text_length` | the claim must be 1 to 500 characters. |
| memory | `refused_uncited` | Muninn got no citation. Supply `--cite` and `--quote`. |
| memory | `restricted_refused` | The adapter does not write restricted records. Write a normal-sensitivity claim. |
| memory | `retro_decisions_chain_broken` | The `verify_chain` check rejected `decisions_absorbed`. The message gives the sequence number. Put the rows back. Record decisions only with `graph.py record-decision`. Then assemble again. |
| memory | `retro_free_invalid` | `--free-file` must contain one JSON object. The command did not assemble a retro. |
| memory | `retro_not_assembled` | `retro.json` has a schema version below 3 or has no `source_hashes`. Run `python3 scripts/lib/retro.py assemble <state-dir> --session <session_id>`. |
| memory | `retro_source_mismatch` | A hashed source changed after assembly. The message names it. Run `retro.py assemble` again when the source files are complete. |
| memory | `retro_state_error` | The command could not read `progress.json`. It did not assemble a retro. |
| memory | `retro_steps_missing` | Check `teardown.jsonl` for a missing step or an incorrect sequence. Run `proof.py run --all` or `proof.py disposition`. Then flush decisions. Next run `orders.py prepare`. Last, run `retro.py assemble`. |
| memory | `retro_wrong_session` | The loop belongs to a different session. Assemble only from the session that owns it. |
| memory | `uncited_write` | Supply a verbatim `--quote` and `--cite ref`. The adapter cannot write a record without a quote. |
<!-- hook-reasons:end -->

## Hook diagnostics

- <a id="no-trace-rows-appear"></a>[No diagnostic log entries](RUNBOOK-HOOKS.md#no-trace-rows-appear)
- <a id="gate-seems-off-config-key-or-wiki-schema"></a>[Config or wiki schema does not activate a gate](RUNBOOK-HOOKS.md#gate-seems-off-config-key-or-wiki-schema)
- <a id="guarded-action-denied-config_rejected-or-wiki-schema-fail-closed"></a>[Config or wiki schema blocks an operation](RUNBOOK-HOOKS.md#guarded-action-denied-config_rejected-or-wiki-schema-fail-closed)
- <a id="discipline-lint-advisories-climbing"></a>[Discipline advisories increase](RUNBOOK-HOOKS.md#discipline-lint-advisories-climbing)
- <a id="reviewerscout-bash-command-denied"></a>[Reviewer or scout Bash denial](RUNBOOK-HOOKS.md#reviewerscout-bash-command-denied)
- <a id="subagent-bash-denied-for-absent-agent_type"></a>[Subagent Bash denial without agent type](RUNBOOK-HOOKS.md#subagent-bash-denied-for-absent-agent_type)
- <a id="guarded-role-has-no-tools-or-no-shell"></a>[Role has no tools or shell](RUNBOOK-HOOKS.md#guarded-role-has-no-tools-or-no-shell)
- <a id="capability-tool-refused-or-denied"></a>[Tool refusal](RUNBOOK-HOOKS.md#capability-tool-refused-or-denied)
- <a id="capability-mcp-server-refused-a-call-or-will-not-start"></a>[MCP server refusal](RUNBOOK-HOOKS.md#capability-mcp-server-refused-a-call-or-will-not-start)
- <a id="authority-object-refused-or-changed"></a>[Authority object refusal or change](RUNBOOK-HOOKS.md#authority-object-refused-or-changed)
- <a id="manifest-says-no-loop-or-the-wrong-loop"></a>[Manifest cannot find the loop](RUNBOOK-HOOKS.md#manifest-says-no-loop-or-the-wrong-loop)
- <a id="autonomous-input-denial-is-wrong"></a>[Autonomy and input denial](RUNBOOK-HOOKS.md#autonomous-input-denial-is-wrong)

The manifest codes are `manifest_ok`, `manifest_graph_invalid`, `manifest_no_session`, `manifest_state_unreadable`, `manifest_payload_malformed`, `manifest_error`, `route_match`, `route_payload_malformed`, and `route_none`.

## Memory degraded (Muninn authoritative)

- Symptom: a typed lesson, decision, or handoff operation gives `{"degraded": "<reason_code>"}` and exits with code 3.
  Muninn is the only typed-memory store. On degradation, the command shows its code and does not write Markdown.
  To run without Muninn, explicitly set `memory.backend: off`. The command logs `memory_backend_off`.

- Query: Run `python3 scripts/measure_graph_alignment.py --root . --json | python3 -c "import sys,json;print(json.load(sys.stdin)['memory'])"`.
  Read `rows`, `by_reason_code`, and `by_command`. The counter deduplicates by `event_id`.
  Commands are `memory.*`, `decision.*`, `order.*`, `lesson.*`, `proof.*`, `retro.*`, `teardown.*`, and `handoff.*`.
  To read the diagnostic log directly, use `grep '"command": "memory\.' <agentic-loop dir>/<session_id>/trace.jsonl`.

  A session ID that fails the safety check produces no entry.
  With an unset or empty session ID (CLI without `CLAUDE_SESSION_ID` or `--session`), the command uses `memory-adapter-nosession`.
  A Muninn refusal keeps its initial code in `refused_<code>`.

- Remediation: Use the code to select a procedure. The code source is `scripts/lib/memory_reasons.py`.

| Code | Remediation |
|------|-------------|
| `memory_backend_off` | The config sets `memory.backend` to `off`. To write typed memory, set it to `muninn` or remove the key. |
| `memory_backend_invalid` | Set `memory.backend` to `muninn` or `off` in `.coderails/workflow.config.yaml`. |
| `muninn_absent` | Install `muninn` and put it on PATH. There is no Markdown fallback. |
| `muninn_old_ledger` | Current consumers use task calls and saved R-id bindings. The standalone legacy CLI uses retired schema-v2 flags. |
| `muninn_timeout` | Muninn gave no result in 10 seconds. Run `muninn know list` by hand and check store locks. |
| `muninn_error` | Muninn gave a nonzero exit code or JSON that cannot be read. Run the same `muninn know ...` command again and read stderr. |
| `muninn_bad_output` | The public task, receipt, or current Note response does not agree with the expected model. Examine the saved task. |
| `learning_pending` | Muninn accepted the task. Keep its R_ ID and check that task again. |
| `learning_request_unknown` | Muninn may have accepted the task without giving its R_ ID. Examine `muninn learn list`. Do not send the task again. |
| `learning_request_failed` | The saved Muninn task did not succeed or was cancelled. Examine it with `muninn learn show R_ID`. |
| `learning_no_matching_record` | The completed task has no eligible current Note or has more than one for this task and text. Examine its receipt and Notes. |
| `learning_no_change` | The saved task finished without a change to knowledge. It wrote no Note. |
| `learning_request_mismatch` | The task and binding differ in project, task, source window, or receipt identity. |
| `learning_receipt_unavailable` | The task has no committed receipt that the reader can use. Muninn can accept a task without writing a Note. |
| `learning_record_changed` | Listed and shown current revisions are different. Read again with the same binding. |
| `learning_record_expired` | The current Note reached its expiry time. Do not use it. |
| `learning_record_ambiguous` | More than one receipt matches this K-id and revision. The reader selected no task identity. |
| `learning_form_unsupported` | This reader reads Notes only. It cannot use Guides. |
| `learning_conditional_use_unsupported` | The Note has conditions for use or expiry. Legacy dispatch, promotion, and render cannot check those conditions. Keep the metadata. Do not use the Note unconditionally. |
| `learning_selection_unavailable` | An E-id, ref, hash, or selected excerpt is necessary but unavailable. Do not cite the Note. |
| `learning_evidence_mismatch` | The saved record identity, selector, scope, or source window does not agree with the binding. |
| `learning_source_changed` | A physical source or its saved provenance changed. Do not cite it. |
| `learning_source_unavailable` | A necessary live physical source is unavailable. Do not cite it. |
| `learning_source_authority` | All sources must be live, primary, unflagged, unredacted user prompts from the owner. Current Muninn has no `normal` or `restricted` class. Do not infer a class. |
| `learning_quote_mismatch` | The public quote check refused a selected excerpt. Do not cite it. |
| `learning_read_limit` | The read went above a time, reply, record, or source limit. It did not give all results. |
| `learning_project_unavailable` | The caller's project directory is unavailable. Do not use the graph key. |
| `muninn_store_missing` | There is no Muninn store at `$MUNINN_HOME` or `~/.local/share/muninn`. Run `muninn ingest` one time. |
| `muninn_schema_old` | The D4 adapter expects retired schema v2. Current Muninn uses schema v1. Do not migrate the store to v2. |
| `muninn_schema_incomplete` | The D4 adapter expects retired v2 columns or tables. Examine the current store with `muninn doctor`. Then redesign the adapter. |
| `uncited_write` | Supply a verbatim `--quote` and `--cite ref`. The adapter cannot write a record without a quote. |
| `restricted_refused` | The adapter does not write restricted records. Write a normal-sensitivity claim. |
| `bad_record` | The record has an error in its type, scope, tag, date, claim text, or loop ID. A claim must have text, and loop scope must have a loop ID. |
| `handwritten_protected` | The hand-written target has no generator marker. Write the view to a new path. |
| `cite_not_user` | The cite must point to a user prompt. Cite the owner's words or use the approved-reply syntax. |
| `cite_too_short` | A quote-only cite must have 12 to 300 characters. Use more of the user's prompt or cite an approval with its reply. |
| `cite_unresolved` | The cite ref or quote-only text did not occur in `muninn session <root>`. This also applies if the approval has no preceding reply or the caller gave no session ID. Check the ref. |
| `cite_not_own_session` | The ref points to a different session. Only a user prompt from the calling session (`--session`) can authorize the write. |
| `cite_bad_approval` | The approval must be a short user prompt (80 chars or fewer) that directly follows the reply it answers. |
| `refused_uncited` | Muninn got no citation. Supply `--cite` and `--quote`. |
| `refused_not_found` | The ref does not resolve. Run `muninn ingest` and check the ref. |
| `refused_not_citable` | The citation points to a subagent thread. Only the orchestrator session can write typed records. |
| `refused_quote_length` | A quote must have 12 to 300 characters. A shorter quote must be the full approval prompt. |
| `refused_quote_not_found` | The quote differs from the cited text. Copy the source text verbatim. |
| `refused_approval_needs_reply` | For a short approval, also cite the reply it answers. Use `--approval REF`. |
| `refused_preference_needs_user` | A preference must cite a user prompt. |
| `refused_bad_supersedes` | There is no K-id to supersede, or the K-id is out of date or has a different scope. |
| `refused_bad_contradicts` | There is no K-id for the contradiction. |
| `refused_bad_valid_until` | The `valid_until` field must be a future ISO date. |
| `refused_bad_tags` | Use tags with the format `[a-z0-9_-]{1,32}`. |
| `refused_bad_loop_scope` | The loop ID has an error, or the caller used `--global` with loop scope. |
| `refused_bad_kind` | Muninn does not accept this record type. |
| `refused_text_length` | The claim must be 1 to 500 characters. |
| `refused_no_caller_session` | The environment must have `CLAUDE_CODE_SESSION_ID` or `CODEX_SESSION_ID` for quote-only writes. |
| `refused_other` | Muninn refused the write with a code this table does not list. Read `refused_<code>` and the Muninn docs. |
| `decision_wrong_session` | The loop belongs to a different session. Record the decision only from the session that owns the loop. |
| `decision_wrong_loop` | The loop changed after the caller read it. Read the current loop ID before you record the decision. |
| `decision_wrong_revision` | The graph changed after the caller read it. Read the current revision before you record the decision. |
| `decision_blank_phase` | A decision must give a phase, for example 2.5. |
| `decision_blank_decision` | A decision must have text. The command did not write a record. |
| `decision_invalid_chain` | The decision chain has damage. Examine and keep the loop data before you sync again. |
| `decision_sync_unknown` | Muninn may have received the decision. Examine the store before you retry by hand. |
| `decision_state_error` | The command could not read, check, or lock the loop data. It did not write a record. |
| `order_chain_broken` | Someone edited `orders.json` by hand. The hash chain names the entry. Use a saved copy or examine the named entry. To seal the entry again, record it with `orders.py`. |
| `order_blank_field` | A standing instruction must have text for the problem and the lesson. The command did not write an entry. |
| `order_lesson_too_long` | The collapsed lesson has more than 500 characters. Write a shorter complete claim. Do not truncate it. |
| `order_bad_id` | Use the format `[a-z0-9][a-z0-9_-]{0,119}` for the standing instruction ID. |
| `order_id_collision` | That ID names a different problem or scope. Use the ID for this entry or make a new one. |
| `order_not_found` | There is no entry with that ID in `orders.json`. Check the ID with `orders.py lessons`. |
| `order_state_error` | The command could not read, lock, or write the instructions, prepared data, or receipt. Check the repo-key directory, `orders.lock`, and the durable `teardown.jsonl.lock`. |
| `order_loop_unknown` | There is no source at `<repo-key dir>/<session>/progress.json`. Supply the `--session` that owns it and the logical `--loop`. |
| `order_wrong_session` | The source directory, session, or logical loop does not belong to this operation. Use the directory and IDs that own it. |
| `order_source_invalid` | The `progress.json` file, prepared data, or observations have a format error. Put the correct checked source files back. |
| `order_source_mismatch` | The prepared source or hash is out of date. Before the loop ends, run `prepare --refresh-from-sha256` with its current `evidence_sha256`. |
| `order_loop_ineligible` | The owned graph or work units did not finish or have stopped. Complete the necessary work. |
| `order_not_complete` | The prepared data is for future use. Apply recurrence or aging only after the owned `progress.json` records `complete` durably. |
| `order_pending_teardown` | The saved loop is complete, but the local update or its observation did not succeed. Retry `tick` with the same source binding. |
| `order_retro_validator_unavailable` | Schema 3 retros use the corresponding `retro_check.py` validator. Make the validator available before graduation. |
| `order_already_ticked` | The tick skipped this session and logical loop because the count includes them. |
| `no_user_cite` | The local diagnostic has no checked citation from the current owner. A caller quote cannot prove the task provenance. |
| `legacy_uncited` | The legacy import has no saved selection for the current task. Keep it uncited. |
| `legacy_parse_error` | The local legacy input has an entry with missing data, an ambiguous meaning, or a collision. Correct the entry and keep the initial file. |
| `legacy_missing` | There is no hand-written `standing-orders.md` to import. The file may not be there, may have no text, or may come from a generator. |
| `lesson_not_current` | The saved task has no current Note that satisfies its conditions. Examine its saved receipt. A caller quote cannot give it authority. |
| `retro_not_assembled` | For a new loop, run `retro.py assemble` for schema-3 `retro.json` after the last Stop and the steps that prepare standing instructions. Keep the source artifacts. See the recovery rule below for a previous completed loop. |
| `retro_source_mismatch` | A named source changed after assembly. Finish that source and assemble again. |
| `retro_decisions_chain_broken` | Put back the damaged decision row. Record decisions through the graph CLI. |
| `retro_steps_missing` | Run the missing proof, flush decisions, or prepare standing instructions as needed. Then assemble again. |
| `decisions_not_flushed` | Flush decisions before the last Stop and before you prepare standing instructions. If an unfinished loop has stale prepared data, use `prepare --refresh-from-sha256` after the last source update. Then assemble the retro. |
| `retro_state_error` | Put the readable, owned `progress.json` back before assembly. |
| `retro_wrong_session` | Use the session that owns `progress.json`. |
| `retro_free_invalid` | Supply one JSON object in the free-file. |
| `handoff_state_unreadable` | Give the readable, owned `progress.json` to `handoff_derive`. |
| `graph_unavailable` | Run `graph.py summarize` and `graph.py inspect` to find why the graph is unavailable. |

Schema-1 and schema-2 retros are historical records. This version checks loop end with schema 3.
A historical completed loop may have no proof results or receipts for standing instructions that schema 3 uses.
Do not rewrite its retro or claim that an install upgrades it.
For a historical check at loop end or a teardown retry, use the previous plugin version in an isolated checkout.
Start a new session and loop for new work, and use the current teardown sequence.

A code rollback to the previous proof-only version cannot validate a schema-3 retro after this version writes it.
Its command for standing instructions can refuse graduation with `order_retro_validator_unavailable`.
Keep a corresponding version with `retro_check.py` in an isolated checkout to check loop end or retry standing instructions for that loop.
Keep its loop data, proof, retro, and receipts for standing instructions together. A code rollback does not change those records.

Only the orchestrator session can write because subagent threads cannot supply a cite. The cite must point to a user prompt.
The hash-chained ledgers are a cooperating-agent safeguard. The same user can change the files.

Compare `by_reason_code` before and after a change. Look for an increase in `muninn_absent` or `refused_approval_needs_reply`.
See `docs/decisions/2026-10-05-memory-authoritative.md`.

## Memory operations

- <a id="current-request-and-citation-boundary"></a>[Task and citation rules](RUNBOOK-MEMORY.md#current-request-and-citation-boundary)
- <a id="decision-recorded-locally-but-muninn-sync-degraded"></a>[Local decision with degraded Muninn sync](RUNBOOK-MEMORY.md#decision-recorded-locally-but-muninn-sync-degraded)
- <a id="standing-order-stored-without-a-cite-or-a-lesson-missing-from-dispatch"></a>[Standing instructions and missing lessons](RUNBOOK-MEMORY.md#standing-order-stored-without-a-cite-or-a-lesson-missing-from-dispatch)

## Stop, scheduled runs, and proof checks

- <a id="a-stop-has-no-recorded-row"></a>[Missing Stop row](RUNBOOK-STOP-AND-PROOF.md#a-stop-has-no-recorded-row)
- <a id="host-resource-errors-or-bounded-stop-checks"></a>[Host resource errors and Stop checks](RUNBOOK-STOP-AND-PROOF.md#host-resource-errors-or-bounded-stop-checks)
- <a id="a-routine-run-ended-incomplete-aborted-or-refused"></a>[Unfinished or refused scheduled run](RUNBOOK-STOP-AND-PROOF.md#a-routine-run-ended-incomplete-aborted-or-refused)
- <a id="proof-gate-blocked-a-complete-declaration"></a>[Proof gate denial](RUNBOOK-STOP-AND-PROOF.md#proof-gate-blocked-a-complete-declaration)

Proof codes:

- `proof_unexecuted`, `proof_failed`, `proof_expect_mismatch`, `proof_stale_cmd`, `proof_stale_head`.
- `proof_chain_broken`, `proof_cmd_destructive`, `proof_sandbox_unavailable`, `proof_output_limit`, `proof_no_proofs`.
- `proof_disposition_no_reason`, `proof_disposition_legacy`, `proof_withdrawn_unobserved`.

## Publication checks

- <a id="diff-manifest-check-warned-or-refused"></a>[Diff-manifest warning or refusal](RUNBOOK-PUBLICATION.md#diff-manifest-check-warned-or-refused)
- <a id="required-review-passes-refused-a-merge"></a>[Mandatory inspection pass refusal](RUNBOOK-PUBLICATION.md#required-review-passes-refused-a-merge)
- <a id="standalone-wiki-security-applicability"></a>[Standalone wiki applicability](RUNBOOK-PUBLICATION.md#standalone-wiki-security-applicability)
- <a id="eval-level-or-suite-integrity-refused-a-merge"></a>[Eval level or suite integrity refusal](RUNBOOK-PUBLICATION.md#eval-level-or-suite-integrity-refused-a-merge)

## Shell checks and receipt authority

- <a id="commit-push-or-ceiling-gate-behaves-differently-than-the-text-suggests-argv-classifier"></a>[Shell classifier and ceiling checks](RUNBOOK-SHELL-AND-AUTHORITY.md#commit-push-or-ceiling-gate-behaves-differently-than-the-text-suggests-argv-classifier)
- <a id="action-authority-hook-denied-a-merge-or-push-or-warned-in-advisory"></a>[Receipt authority for merges and pushes](RUNBOOK-SHELL-AND-AUTHORITY.md#action-authority-hook-denied-a-merge-or-push-or-warned-in-advisory)

## Graph operations and recovery

- <a id="typed-state-verdicts-and-attestation-merge-blocked-by-attest_-eval-verdict-hook-state"></a>[Typed records, eval verdicts, and attestation](RUNBOOK-DISPATCH.md#typed-state-verdicts-and-attestation-merge-blocked-by-attest_-eval-verdict-hook-state)
- <a id="graph-refused-with-spec_-or-instantiate-refused"></a>[Spec and instantiate refusal](RUNBOOK-GRAPH-SPEC.md)
- <a id="a-procedure-script-wiki_lint-verify_merged-merge---describe-memory_dir-detect_test_command-check---json-answered-unexpectedly"></a>[Procedure script results](RUNBOOK-DISPATCH.md#a-procedure-script-wiki_lint-verify_merged-merge---describe-memory_dir-detect_test_command-check---json-answered-unexpectedly)
- <a id="source-bound-dispatch-upgrade-and-rollback"></a>[Upgrade and rollback for source-bound dispatch](RUNBOOK-DISPATCH.md#source-bound-dispatch-upgrade-and-rollback)
- <a id="dispatch-refused-dispatch_-or-role_mismatch"></a>[Dispatch or role refusal](RUNBOOK-DISPATCH.md#dispatch-refused-dispatch_-or-role_mismatch)
- <a id="disposition-refused-compat-findings-blocked-a-merge-or-a-worker-status-stopped-the-loop"></a>[Retirement decision, compatibility, and worker status](RUNBOOK-DISPATCH.md#disposition-refused-compat-findings-blocked-a-merge-or-a-worker-status-stopped-the-loop)
