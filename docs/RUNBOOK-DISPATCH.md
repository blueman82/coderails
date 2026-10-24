# Dispatch and worker-status troubleshooting

## Dispatch refused: `dispatch_*` or `role_mismatch`

- Symptom: `loop_dispatch_guard` (Claude `Agent`, Codex `spawn_agent`) denies a spawn in a graph-bound session, or
  `begin-wave` / `graph.py authorize-dispatch` fails. The hook message names the failure; the reason code is a row in the
  loop's `recovery-trace.jsonl` (`authorize-dispatch/refused/<code>`, allowed spawns are `authorized/dispatch_authorized`).
- Query: `python3 scripts/lib/dispatch_counters.py [--since <ISO ts>]` counts `dispatch_authorized` and every refusal code.
- Codes and fixes: `dispatch_missing_envelope` (no/old/garbled first-line `CODERAILS_GRAPH_DISPATCH` envelope: paste the
  `prompt_prefix` from `plan` or `begin-wave`; on Codex this includes a spawn with any `task_name` and no envelope),
  `dispatch_unknown_id` (the id was never issued: run `begin-wave`), `dispatch_foreign` (session, loop, node, wave or Codex
  `task_name` is not the record's), `dispatch_stale_revision` (the envelope predates the graph's current revision:
  re-run `begin-wave` after `recover-wave`), `dispatch_replayed` (the id was already used: one spawn per id; a retry needs a
  new wave), `dispatch_contract_altered` (the stored contract no longer matches its digest or lost a field: the state was
  edited, restart the wave via `recover-wave`), `dispatch_sections_missing` (the pasted contract block was edited or left
  out: paste `prompt_sections` verbatim), `role_mismatch` (dispatch a guarded scout as `coderails:<role>` / Codex
  `agent_type: <role>`; other roles accept their own type or `general-purpose` on Claude, and their own type or omitted
  `agent_type` on Codex; a different named native role such as `explorer` is refused),
  `dispatch_state_unconverted` (`state_minor` < 2 or a malformed current-minor contract cutoff: run
  `graph.py convert --check` then `convert` for old state; inspect malformed current state without editing frozen evidence;
  conversion refuses while a wave is open, `convert_refused_active_wave_in_flight`),
  `dispatch_publication_mismatch` (the stored unit worker command names a different unit, push script or progress path:
  use the exact `publication_command` returned by `begin-wave`), `dispatch_unauthorized` (Claude
  `record-wave` / completion found a bound spawn whose record the PreToolUse guard never consumed, i.e. a spawn the hook did
  not see: re-dispatch it through the guard via `recover-wave`). A Claude graph-bound `Agent` call with no
  `subagent_type` is refused as `role_mismatch` before native dispatch.
- Off-switch: `CODERAILS_GRAPH_DISPATCH=off` (also `0` or `false`) in the hooks and graph CLI bypasses the contract hash,
  rendered sections, role and single-use checks. A graph-bound spawn still needs the current v2 envelope issued by
  `begin-wave`, the recorded task name on Codex, and frozen evals; native evidence still binds its node, wave and attempt.
  An absent or v1 envelope is refused. Claude graph-bound Agent calls must include a nonblank `subagent_type`, including
  `general-purpose` for unguarded roles; a missing type cannot be bound to native evidence. An ordinary Agent outside a
  graph is unaffected. Each allowed spawn leaves an
  `authorize-dispatch/reported/dispatch_check_off` trace row. Default ON; unset to re-enable. Use it only to rescue a
  loop wedged by a bad contract or an uninstalled plugin agent.
- Codex evidence rollout: `CODERAILS_A6_EVIDENCE_WRITE` defaults OFF. While OFF, the new reader can validate old and new
  references, `reject-invalid-dispatch --report-only` works, and attempts to persist invalid-dispatch or encrypted-message
  evidence fail without changing `progress.json`; the dispatch off-switch also keeps its old no-receipt behavior. After
  installing and trusting this reader, check active old graphs with
  `inspect` and completed ones with `verify-completion` before setting the variable to `on` for new writes. Once either
  new reference shape is stored, turn writing OFF to stop further new records, but keep this reader installed for later
  completion and verification. The prior plugin reader cannot verify those histories, even after a loop is complete;
  reinstalling it is not a rollback path. The owner must accept that permanent reader pin before enabling writes.
- Bad `add-unit --model-role` is `add_unit_refused_bad_field` (allowed: `fast-mechanical`, `default`, `frontier`).
- Limits: a plugin agent that is not installed in the session cannot run a guarded scout (refused, never downgraded); the
  sandboxed Bash launcher carries no agent type, so the role is asserted on the `Agent` and `spawn_agent` routes only
  (handoff H3); single use is keyed on the PreToolUse `tool_use_id` when the payload has one (unverified) and otherwise on
  a consumed flag, so a hook retried without an id reads as a replay; Codex role containment (no shell, per-role MCP) is
  not asserted, only `agent_type == role`; `progress.json` and the sections are plain same-user data, so this is drift and
  substitution detection for a cooperating agent, not tamper evidence.
- Limits, coverage: (1) the contract is advisory to the worker: the envelope proves the dispatch was authorized and the
  rendered block is present as a substring, not that the rest of the prompt is faithful; text before, after or around the
  block is unconstrained and `write_scope` is prompt text only, not enforced. (2) Only the five capability-guarded roles
  (`deploy-safety-reviewer`, `design-scout`, `disposition-scout`, `preflight-scout`, `source-auditor`) are role-contained;
  `spec-reviewer` (empty capability list), the `shell.raw` roles (`docs-auditor`, `wiki-writer`, `proof-author`) and nodes
  with no `agent_role` (default `loop-worker`) may run as explicit `general-purpose` on Claude, or with omitted or exact
  role `agent_type` on Codex, with full tools. (3) Re-entry is not covered: the matchers are `Agent` and `spawn_agent` only, so `SendMessage` on
  Claude and resume / `send_input` on Codex can give a finished or running worker a fresh prompt outside any envelope.
  (4) Both providers re-check current-wave dispatches at `record-wave` and completion. Codex requires a native
  `spawn_agent` function-call message with its v2 record, role and consumed authorization; encrypted messages also require
  the PreToolUse `tool_use_id` to equal the native function-call id, so off-mode receipts cannot bind them. A task-name-only legacy event
  cannot bind a contract-era wave. Claude matches a non-null hook `tool_use_id` to the native Agent call; when the hook
  supplies no id, it retains the consumed flag and one-spawn-per-id check without claiming call-id proof. Historical
  pre-contract attempts retain their original evidence rules. Claude hooks can still fail open if the hook times out
  (10 s in `hooks.json`) before it denies.

## Disposition refused, compat findings blocked a merge, or a worker status stopped the loop

- `add-unit` says `add_unit_refused_disposition`: `--disposition preserve-compat` needs both a non-blank `--named-blocker`
  and `--removal-ticket`; `--disposition clean-break` takes neither; either flag without `--disposition` is refused. The
  unit is stored as `work_units[u].disposition = {kind, named_blocker?, removal_ticket?}` and is what the dispatch
  contract carries. `graph.py disposition-audit <state>` prints every unit's kind and exits 1 on a hand-edited unit that
  broke the rule; `complete` / `verify-completion` refuse the same unit on both providers (default ON, no switch).
- `/coderails:merge` says `compat_findings_nonzero`: the posted review artifact carries a second line
  `<!-- coderails-compat-findings v1 pr=N head_sha=S count=K disposition=D -->` (built by
  `post_review.py compat-line <pr> <sha> --count K --disposition D`) with `disposition=clean-break` and `K > 0`. Remove the
  retained compatibility code, creating a new head SHA, and post a fresh review; or register the unit `preserve-compat`
  with a blocker and ticket. Posting a passing review on the same SHA cannot override an earlier refusing compat line.
  `compat_findings_malformed` means a line with that prefix is not exactly the typed form. `compat_findings_missing`
  means no line matches this PR and head; post a fresh artifact including the line, even for a zero count.
  The v1 review marker the root-owned integrity daemon matches is unchanged. Any refusing line for the
  head wins; the merge refusal is a stderr reason code, not a trace row (merge.py has no loop session).
- Limits: `K` and `D` are the reviewer's own judgement, not a measurement, and a same-user agent can write any line, so
  this is drift detection for a cooperating reviewer, not tamper evidence. The gate reads the PR's artifact only; it does
  not cross-check `D` against `work_units[u].disposition`.
- `record-wave` says `worker_status_<code>` (`not_an_object`, `unknown_status`, `missing_field`, `unknown_field`,
  `bad_field`): a result carrying a `status` key is not a valid typed worker status, so the WHOLE report was rejected and
  `progress.json` is byte-identical; fix the worker's result (the schema is in `scripts/worker_status.py`) and record
  again. `final_report_invalid`: a `done` result for a dispatch with `final_report_required` lacks a valid
  `final_report {claims: [{text, label, source?}], did_not_verify: [{item, tag, reason}]}` (non-empty claims, a `verified`
  claim cites a source, tags `resolved|unverifiable`). Both leave a `record-wave/refused/<code>` trace row.
- A valid typed status is recorded, not refused: `worker_statuses[]` gets a `decision_pending` row, the node is recorded
  as a failed attempt; at the retry limit the terminal slot stays available behind that pending decision, so an answer
  can resume the node. ONE typed
  stop row is written in the same save (`awaiting-input/needs_human_input` for `NEEDS_DECISION`, `approval-gate/needs_approval`
  for `OUTSIDE_SCOPE` and `IRREVERSIBLE_ACTION`; approval outranks input when a wave returns both). The Stop guard releases
  that row once. Ask the human with `to_decision_request()`, then log the answer with `graph.py record-decision <state>
  --session S --phase P --decision D --chosen C [--flip-condition F] --worker-status-seq <seq>`: it appends one typed row
  to `decisions_absorbed` and marks that status resolved. `python3 scripts/lib/worker_counters.py` reports
  `pending_statuses` (rows still `decision_pending`) and `decision_recorded`.
- `record-decision` says `record_decision_refused_<foreign|field|state|status|chosen|human>`: the session does not own the
  graph, a flag is blank, `decisions_absorbed` is not an array of objects, `--worker-status-seq` names no pending status
  (unknown, already resolved, duplicated, or malformed), `--chosen` is not one of a `NEEDS_DECISION` status's options,
  or the status is an approval gate (`OUTSIDE_SCOPE`, `IRREVERSIBLE_ACTION`) and `--human-answer` was not passed. Nothing is written. It does
  not bump the revision. Limits: `phase`, `decision` and `chosen` are free text outside a status-linked answer (no enum,
  no check against the graph); hand-appended `{phase, decision}` rows stay valid and unnumbered. There is no caller
  authentication: `--session` and `--human-answer` are self-asserted, so a same-user agent can still forge a human
  answer (or write any row); the flag makes that a deliberate act, not tamper evidence. Only the orchestrator should
  pass `--human-answer`, and only after the human replied.
- Limits: shape is checked, truth is not (a worker can write any claim); only results of dispatches with a begin-wave
  record require the report, so a pre-conversion state behaves as before; `check_confidence_labels` and
  `check_verify_loop` stay advisory lints on the orchestrator's own text.
