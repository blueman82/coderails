# Runbook: hook and trace observability

Trace rows are NON-AUTHORITATIVE: fail-open, append-only, one `event_id` per event, written by
`hooks/scripts/lib/trace_row.py` to `<agentic-loop dir>/<session_id>/trace.jsonl` (the same per-session directory
`crack_on_gate.py` uses, with or without a loop). Rows hold `schema_version`, `event_id`, `session_id`, `loop_id`
(null outside a loop), `ts`, `command`, `outcome`, `reason_code` and sha256-hashed `inputs`. No gate decision
reads them. Counters dedupe by `event_id`, skip torn lines, and key tallies as `command/outcome/reason_code`.

Query every entry below with:

```
python3 scripts/measure_graph_alignment.py --root . --json | python3 -c "import sys,json;print(json.load(sys.stdin)['trace'])"
```

## No trace rows appear

- Symptom: `trace.rows` is 0 although gates fired (`gate_blocks` counts are nonzero).
- Query: the command above; then `ls ${CLAUDE_AGENTIC_LOOP_DIR:-~/.coderails/agentic-loop}/<session_id>/trace.jsonl`.
- Remediation: the writer fails open, so an unwritable directory or an unsafe session id (contains `/` or `..`,
  or is empty) silently drops rows. Fix the directory permissions; do not make the gate depend on the write.

## Gate seems off (config key or wiki schema)

- Symptom: a configured gate (wiki taxonomy, wiki-debt, integrity, eval signing) does nothing, or a config key seems ignored.
- Query: `python3 scripts/lib/config.py resolve-config --json | jq .unknown_keys` (also `.findings`); counts via
  `python3 scripts/lib/config_counters.py` for `config_unknown_key`, `config_bad_type`, `config_bad_value`, `config_unreadable`,
  `wiki_schema_missing`, `wiki_schema_invalid`, `wiki_schema_legacy` (scope with `--since 2026-10-05T00:00:00`; the same rows
  also appear in `measure_graph_alignment.py --json` under `trace.by_reason`; trace rows: `config/warned/<code>`, `wiki_taxonomy_gate/failed_closed/<code>`).
- Remediation: fix the key (the finding carries a did-you-mean hint) or the value; `resolve-config --json` prints
  `valid:false` and exits 1 while any finding remains. Reading is non-authoritative for ordinary gates (they warn and
  trace), but the guarded actions below fail closed. `wiki_schema_legacy` identifies an older vault record. The wiki
  gate requires `wiki.schema.json`; restore that file to allow writes in an identified vault.

## Guarded action denied: config_rejected or wiki schema fail-closed

- Symptom: `gh pr merge` or `git push` to main (action-authority hook), `push.py`/`merge.py` (diff-manifest check) or a
  write inside the wiki vault is denied with `config_rejected` ("did you mean ..."), `wiki_schema_missing` or
  `wiki_schema_invalid`.
- Query: trace rows `action_authority/denied/config_rejected`, `diff-manifest/refused/config_rejected`,
  `wiki_taxonomy_gate/failed_closed/<config_rejected|wiki_schema_missing|wiki_schema_invalid>`; counts via
  `python3 scripts/lib/config_counters.py` (`config_rejected`, `config_bad_value`, `wiki_schema_fail_closed`).
- Remediation: run `python3 scripts/lib/config.py resolve-config --json`, fix each finding (typo'd key, wrong type, value
  outside the enum), or restore `wiki.schema.json` (`page_types` non-empty list of directory names). Only the guarded
  action is denied; other commands and tools can continue. Without a config file, config-dependent gates do not run.
  The diff-manifest check still uses its shipped policy. An ambiguous wiki identity (no `wiki_path`, another repository,
  or a path that is not a vault) does not block a write.
- Limit: a same-user agent can remove the config file or set a control to `off`; no hook guards
  `.coderails/workflow.config.yaml`. Removing the file does not disable the default diff-manifest check. Review config
  diffs like code. The diff-manifest policy can list the config file as a protected path. `evals.require_signatures`
  fails closed: only an explicit `false` turns it off. Malformed lines and duplicate keys are
  `config_unparseable_line` / `config_duplicate_key` findings.
- Defaults: the diff-manifest check uses `enforce` mode and `policy/diff-policy.default.json` even without a config file.
  An existing config with no other keys enables `sandbox_workers: true` and `evals.require_signatures: true`.
  `action_authority` defaults to `off`. The shipped config sets it to `advisory`, which warns about missing receipts
  without a passphrase. Set `enforce` only when signed receipts are required.

## Discipline lint advisories climbing

- Symptom: `confidence_labels` or `verify_loop` advisories climb. These two hooks no longer block (demoted by user
  override, `docs/decisions/2026-10-04-not-in-gate-demotion.md`); the pre-demotion `blocked` series is history.
- Query: `trace.by_reason` for `check_confidence_labels/demoted/confidence_label_missing` and
  `check_verify_loop/demoted/verify_loop_missing` (keys are `command/outcome/reason_code`; `blocked` and `warned`
  rows are the older series and are separate); `gate_blocks.claude.gates.<gate>` for `demoted`/`would_block`.
  `blocked / decisions` now falls to about 0 by construction; compare `demoted / decisions` instead.
- Remediation: a rising `demoted` count means the model is skipping labels or DNV tags, not that a gate is stuck.
  Fix the prompt or instruction text; there is nothing to unblock.

## Reviewer/scout Bash command denied

- Symptom: a read-only reviewer or scout reports a denied Bash call.
- Query: `trace.by_reason` for `reviewer_bash_allowlist/denied/bash_allowlist_deny_<cause>`, cause one of `meta`
  (chaining/redirection), `flag` (dangerous or unknown rg flag), `parse` (bad quoting), `argv` (command not on the list).
  The discipline log line carries `agent_type`, `argv0` and a 12-char sha of the command.
- Remediation: rerun the inspection with a single allowlisted read-only command (no chaining, redirection or
  interpreters). If a legitimate command is missing, add its exact argv prefix to the allowlist with a test.

## Subagent Bash denied for absent agent_type

- Symptom: a subagent's Bash call is denied with `bash_agent_type_absent`.
- Query: `trace.by_reason` for `subagent_identity_gate/denied/bash_agent_type_absent`; the discipline log line
  `hook=subagent_identity_gate` carries the session. Counters: `python3 scripts/measure_graph_alignment.py --root . --json`.
- Remediation: dispatch the role by its `subagent_type` (for example `coderails:design-scout`) so the payload carries an
  `agent_type`; guarded roles act through their MCP tools and have no Bash. Do not widen the hook: it denies only
  `agent_id` without `agent_type` in a graph-bound session. Codex has no counterpart (no `agent_type` at PreToolUse).

## Guarded role has no tools or no shell

- Symptom: a reviewer/scout reports it cannot run a command or read a file, or a skill step is UNSUPPORTED.
- Cause: by design the six guarded agents hold only `mcp__plugin_coderails_cap-<role>__*` tools (+`Skill` for
  preflight-scout). If the tools are missing entirely, `.claude-plugin/plugin.json` lacks `mcpServers` or
  `capabilities/mcp.json` is stale: run `python3 scripts/capability_profiles_validate.py --check`, and `--write-mcp` to
  regenerate. Codex: launch the role with `scripts/codex_role_session.py`; a native Codex child of a guarded role has no
  shell and no capability tools. The launcher refuses a cwd under a project `.codex/` directory
  (move the audit elsewhere or remove it). Set `subagent_identity_gate: off` in the repo config to disable the
  identity gate (default ON).

## Capability tool refused or denied

- Symptom: a reviewer/scout (usually `source-auditor` running `tests.run`) is refused a `scripts/capability.py` call.
- Query: `trace.by_reason` for `reviewer_bash_allowlist/denied/capability_denied_<tool>`,
  `capability_unknown_tool` or `capability_bad_argv` (hook side, one row per decision;
  `reviewer_bash_allowlist/allowed/capability_allowed_<tool>` counts grants), and `capability/refused/capability_*`
  (script side: `args_invalid`, `path_denied`, `bad_ref`, `no_repo`, `tests_unknown_name`, `sandbox_unavailable`, `io_error`). Narrow with
  `python3 scripts/measure_graph_alignment.py --root . --json | jq '.trace.by_reason | with_entries(select(.key|test("capability")))'`.
  Hook rows need a session id (payload `session_id`); script rows use env `CLAUDE_SESSION_ID` or `CODEX_THREAD_ID`
  (unverified that the harness sets it) and otherwise land under the `unattributed` session directory. `"traced": false`
  now means only that the trace library or disk failed; the hook also logs `denied=1 reason_code=...` to its log, so an empty query is not proof
  of no refusals.
- Remediation: `capability_denied_*` means the agent's profile lacks the tool; change `capabilities/profiles.json`
  deliberately (the validator test keeps frontmatter and Codex sandboxes in step), never widen Bash. `bad_argv` means
  the call was not exactly `<abs path>/scripts/capability.py <tool> --json-args '<json>'`; the path must be absolute.
  `tests_unknown_name` means the name is not in `profiles.json` `tests`.

## Capability MCP server refused a call or will not start

- Symptom: a role's `capability_mcp.py` exits 2 at launch, or a `tools/call` returns an error or `isError`.
- Query: `python3 scripts/lib/capability_counters.py` (counts per reason code over `CLAUDE_AGENTIC_LOOP_DIR`), or
  `trace.by_reason` for `capability/refused/capability_mcp_refused` (startup), `capability_wrong_role` (a tool outside the
  role's profile), `capability_args_invalid|path_denied|bad_ref` (arguments) and `capability/ok/<tool>` (grants). Rows carry
  hashed inputs `{tool, role, via: mcp}`; MCP servers read the session id from `CLAUDE_SESSION_ID`, then
  `CLAUDE_CODE_SESSION_ID`, then `CODEX_THREAD_ID`, else the `unattributed` directory.
- Remediation: `capability_mcp_refused` means the `--role` is missing from `capabilities/profiles.json`, holds no capability
  tool, or the flags are wrong (stderr names which). `capability_wrong_role` means the profile does not grant that tool;
  change the profile deliberately (the validator keeps agent files in step). `path_denied` on a `worktree` argument means
  the path is not in `git worktree list` of the server's cwd repo. `cmd.run` only runs `named_commands` entries.

## Authority object refused or changed

- Symptom: `authority.py` refuses a command, or an object disappeared.
- Query: `trace.by_reason` for `authority/created|narrowed|revoked` and `authority/refused/authority_refused_<cause>`, cause one of `exists`,
  `widen_scope`, `widen_max_prs`, `narrow_empty`, `not_revocable`, `missing`, `expired`, `malformed`, `invalid`,
  `create_invalid`, `write_failed`, `foreign` (an unsafe session id cannot be traced; stderr only).
- Remediation: inspect with `python3 scripts/authority.py inspect --session <exact id>`. A foreign-session refusal
  means the id did not match exactly; ids are never sanitised.

## Manifest says no loop, or the wrong loop

- Symptom: the SessionStart manifest shows `loop: none` or `loop: unknown` although a loop is running, or the
  session injected the static fallback.
- Query: `python3 scripts/measure_graph_alignment.py --root . --json | python3 -c "import sys,json;print(json.load(sys.stdin)['context'])"`,
  or `jq 'select(.command|startswith("context_"))|.reason_code' ${CLAUDE_AGENTIC_LOOP_DIR:-~/.coderails/agentic-loop}/<session_id>/trace.jsonl`.
  Reason codes: `manifest_ok`, `manifest_graph_invalid`, `manifest_no_session`, `manifest_state_unreadable`,
  `manifest_payload_malformed`, `manifest_error`, `route_match`, `route_payload_malformed`, `route_none`
  (an unrouted prompt: no row is written). Events with a missing or unsafe session id are filed under
  `<loop dir>/_unattributed/trace.jsonl`.
- Remediation: `loop: none` for a foreign or unsafe session id is correct (ids match exactly, never sanitised). For
  `manifest_state_unreadable` repair progress.json; for `manifest_graph_invalid` run `graph.py inspect <state>`.
  Check `CLAUDE_AGENTIC_LOOP_DIR` (wins) versus `CODERAILS_AGENTIC_LOOP_DIR`. Routes are advisory text only.

## Crack-on denial wrong (stuck on, or off too early)

- Symptom: `AskUserQuestion` / `request_user_input` is denied when the user no longer wants autonomy, or is allowed
  right after "crack on" (the phrase grants nothing: only `/coderails:authorize` or `authority.py grant` does).
- Query: `trace.by_reason` for `authority/granted/authority_granted_command` (the typed grant),
  `crack_on/ignored/authority_phrase_ignored` (the phrase was seen and ignored; the hint with the grant command was shown),
  `crack_on/blocked/authority_deny`,
  `crack_on/allowed/authority_expired_allow`, `crack_on/blocked/crack_on_legacy_flag`,
  `crack_on/ignored/authority_corrupt_ignored` (authority.json unparseable: treated as none; legacy flag still honoured),
  `authority/refused/authority_refused_write_failed` (the grant could not write, so nothing is suppressed),
  `authority/refused/authority_refused_foreign`. Inspect with
  `python3 scripts/authority.py inspect --session <exact id>`.
- Remediation: revoke with `python3 scripts/authority.py revoke --session <id>` (also deletes any legacy flag). An old flag
  (`crack_on_legacy_flag`) is cleared with `rm <loop dir>/<id>/crack_on_active` (Codex:
  `$PLUGIN_DATA/sessions/<id>/crack_on_active`). Allowed right after "crack on": by design, the phrase only prints the grant command
  (`authority_phrase_ignored`); type `/coderails:authorize` (fixed defaults, `max_prs` 0; Codex: `$coderails-codex:authorize`) or run
  `python3 <abs>/scripts/authority.py grant --session <id> --max-prs N` to grant. `authority_expired_allow` shows the 24h object lapsed;
  grant again (an expired file is replaced; a live one is refused `authority_refused_exists`). `authority_refused_unsafe_session` also
  means `/coderails:authorize` got an empty or unsubstituted (`${...}`) session id: the substitution in the command file is not
  live-probed (see `docs/decisions/e3-authority-object.md`), so run `authority.py grant --session <id>` yourself. Objects written before this change have no `granted_by`
  (read as `legacy_phrase`) and are honoured until expiry. Limit: an agent with shell access can also run `grant`
  (cooperating-agent safeguard against accidental or pasted-text grants, not a hostile same-user agent). Same-user boundary: `granted_by` is an unsigned, self-asserted label. Besides running `grant`, an agent can write `authority.json` directly (Write or a shell redirect, with any `granted_by` or none) or touch the legacy `crack_on_active` flag (no expiry, still honoured), and nothing guards those paths; the crack-on hint tells agents not to grant.
- Baseline note: the old 103 fires / 5 blocks figure (`docs/graph-alignment-measurement.md`) came from discipline-log
  telemetry; after-numbers come from trace rows, so they are not comparable. Reproduce:
  `python3 scripts/measure_graph_alignment.py --root . --json`.

## Memory degraded (Muninn authoritative)

- Symptom: a typed lesson, decision or handoff read/write printed `{"degraded": "<reason_code>"}` and exited 3.
  Muninn is the only typed-memory store. There is NO Markdown fallback: a degrade is reported with its reason code,
  never skipped and never replaced by hand-written Markdown. `memory.backend: off` is the one explicit way to run
  without it (reason `memory_backend_off`, traced).
- Query: `python3 scripts/measure_graph_alignment.py --root . --json | python3 -c "import sys,json;print(json.load(sys.stdin)['memory'])"`
  (`rows`, `by_reason_code`, `by_command`; deduped by `event_id`; commands `memory.*`, `decision.*`, `order.*`,
  `lesson.*`, `proof.*`, `retro.*`, `teardown.*`, `handoff.*`), or
  `grep '"command": "memory\.' <agentic-loop dir>/<session_id>/trace.jsonl`. An unsafe session id writes no row; an unset
  or empty session id (CLI without `CLAUDE_SESSION_ID` or `--session`) writes rows under the fixed id
  `memory-adapter-nosession`. A muninn refusal keeps its original code in the reason (`refused_<code>`).
- Remediation (reason code: one-line fix, single source `scripts/lib/memory_reasons.py`):

| Code | Remediation |
|------|-------------|
| `memory_backend_off` | memory.backend is off in the workflow config; set it to muninn (or remove the key) to write typed memory. |
| `memory_backend_invalid` | memory.backend must be muninn or off; fix the value in .coderails/workflow.config.yaml. |
| `muninn_absent` | muninn is not on PATH; install it (the Markdown path is not a fallback). |
| `muninn_old_ledger` | the D4 adapter expects retired Muninn flags. Keep the result degraded until a current request-bound adapter is designed. |
| `muninn_timeout` | muninn hung past 10s; run `muninn know list` by hand and check store locks. |
| `muninn_error` | muninn exited nonzero or returned unparseable JSON; rerun the same `muninn know ...` command and read stderr. |
| `muninn_bad_output` | the retired D4 write protocol returned no numeric K-id. Inspect current Muninn records without a legacy scope flag. |
| `muninn_store_missing` | no Muninn store at $MUNINN_HOME (or ~/.local/share/muninn); run `muninn ingest` once. |
| `muninn_schema_old` | the D4 adapter expects retired schema v2; current Muninn uses schema v1. Do not migrate the store to v2. |
| `muninn_schema_incomplete` | the D4 adapter expects retired v2 columns or tables. Inspect the current store with `muninn doctor`, then redesign the adapter. |
| `uncited_write` | give a verbatim --quote (and --cite ref); a record without a quote is never written. |
| `restricted_refused` | restricted records are never written by the adapter; write a normal-sensitivity claim. |
| `bad_record` | the record failed validation (type, scope, tag, date, empty claim, or loop scope without a loop id). |
| `handwritten_protected` | the render target is hand-written (no generator marker); render to a new path. |
| `cite_not_user` | the cite must anchor in a user prompt; cite the owner's own words or use the approved-reply form. |
| `cite_too_short` | a quote-only cite needs 12 to 300 characters; quote more of the user's prompt or cite an approval with its reply. |
| `cite_unresolved` | the cite ref (or the quote, for a quote-only cite) was not found in `muninn session <root>`, or the approval has no reply before it, or no session id was given; check the ref. |
| `cite_not_own_session` | the cite ref belongs to another session; only a prompt of the caller's own session (--session) can anchor a write. |
| `cite_bad_approval` | the approval must be a short user prompt (80 chars or fewer) that directly follows the reply it answers. |
| `refused_uncited` | muninn got no citation; pass --cite/--quote. |
| `refused_not_found` | the cite ref does not resolve; run `muninn ingest` and check the ref. |
| `refused_not_citable` | the cited event is a subagent thread; only the orchestrator session can write typed records. |
| `refused_quote_length` | the quote must be 12 to 300 characters (a shorter one is valid only as a whole approval prompt). |
| `refused_quote_not_found` | the quote is not verbatim in the cited event; copy it exactly. |
| `refused_approval_needs_reply` | a short approval needs the reply it answers cited too; use the approved-reply form (--approval REF). |
| `refused_preference_needs_user` | a preference must cite a user prompt. |
| `refused_bad_supersedes` | the superseded K-id is missing, not current, or in another scope. |
| `refused_bad_contradicts` | the contradicted K-id does not exist. |
| `refused_bad_valid_until` | valid_until must be a future ISO date. |
| `refused_bad_tags` | tags must match [a-z0-9_-]{1,32}. |
| `refused_bad_loop_scope` | the loop id is invalid, or --global was combined with a loop scope. |
| `refused_bad_kind` | the record kind is not one muninn accepts. |
| `refused_text_length` | the claim must be 1 to 500 characters. |
| `refused_no_caller_session` | quote-only writes need CLAUDE_CODE_SESSION_ID or CODEX_SESSION_ID in the environment. |
| `refused_other` | muninn refused with a code not listed here; the reason is `refused_<code>`, read it and the muninn docs. |
| `decision_wrong_session` | the loop state belongs to another session; record only from the owning session. |
| `decision_wrong_loop` | the loop changed after the caller read it; read the current loop ID before recording. |
| `decision_wrong_revision` | the graph changed after the caller read it; read the current revision before recording. |
| `decision_blank_phase` | a decision needs a non-blank phase (for example 2.5). |
| `decision_blank_decision` | a decision needs a non-blank decision text; nothing was written. |
| `decision_invalid_chain` | the decision chain is damaged; inspect and preserve the loop state before any further sync. |
| `decision_sync_unknown` | a decision sync may have reached Muninn; inspect the store before any manual retry. |
| `decision_state_error` | the loop state could not be read, validated or locked; nothing was written. |
| `order_chain_broken` | orders.json was edited by hand (the hash chain names the order); restore it from backup or review the named order, then re-seal by recording through orders.py. |
| `order_blank_field` | an order needs a non-blank failure mode and lesson; nothing was written. |
| `order_lesson_too_long` | the collapsed lesson exceeds 500 characters; provide a shorter complete claim, never truncate it. |
| `order_bad_id` | an explicit order id must match [a-z0-9][a-z0-9_-]{0,119}; use a canonical id. |
| `order_id_collision` | that id names another failure mode or scope; use its real identity or a distinct id. |
| `order_not_found` | no order with that id in orders.json; check the id with `orders.py lessons`. |
| `order_state_error` | orders, preparation or receipt could not be read, locked or written; check the repo-key dir, orders.lock and persistent teardown.jsonl.lock. |
| `order_loop_unknown` | no source at <repo-key dir>/<session>/progress.json; pass its owning --session and separate logical --loop. |
| `order_wrong_session` | the source directory, session or logical loop is foreign; use the owning directory and identifiers. |
| `order_source_invalid` | progress, preparation or observations are malformed; restore genuine validated source artifacts. |
| `order_source_mismatch` | the prepared source/hash is stale; before completion use `prepare --refresh-from-sha256` with its CURRENT `evidence_sha256`. |
| `order_loop_ineligible` | graph or work units are incomplete or stopped; finish the existing completion requirements. |
| `order_not_complete` | preparation is prospective; durably save owned progress complete before recurrence or aging. |
| `order_pending_teardown` | completion saved but local apply or observation failed; retry tick with the same bound source. |
| `order_retro_validator_unavailable` | schema3 retros need the matching retro_check.py validator; reconcile that source dependency before graduation. |
| `order_already_ticked` | this session and logical loop were already counted; the tick was skipped (informational). |
| `no_user_cite` | the order was stored without a user quote; attach it with `orders.py cite <id> --quote <verbatim owner prompt text>`. |
| `legacy_uncited` | an imported hand-written order has no cite yet; attach one with `orders.py cite <id> --quote`. |
| `legacy_parse_error` | the local legacy input has an incomplete, ambiguous or colliding entry; fix it while preserving the original. |
| `legacy_missing` | there is no hand-written standing-orders.md to import (absent, empty or already generated). |
| `lesson_not_current` | no unambiguous current cited claim exists; inspect conflicting current evidence, or explicitly re-record a retracted/expired lesson with a fresh quote. |

- Limits: only the orchestrator session can write (subagent threads are not citable); cites must anchor in a user
  prompt; the hash-chained ledgers are a cooperating-agent safeguard, not a security boundary. Measurement note: compare
  `by_reason_code` before and after a change; a rising `muninn_absent` or `refused_approval_needs_reply` is the signal.
  See `docs/decisions/2026-10-05-memory-authoritative.md`.

## Decision recorded locally but Muninn sync degraded

- Symptom: `graph.py record-decision` printed `"exit_code": 3` and a `muninn.reason_code`. The decision was appended
  to `progress.json` `decisions_absorbed` before the sync attempt. For `unknown` or `syncing`, the Muninn copy may
  already exist; inspect both stores before any recovery. A loop restarted during sync may no longer contain that row.
  Trace rows: `decision.record/recorded/ok`, then `decision.sync/<written|degraded|disabled>/<reason_code>`.
- Query: `python3 -c "import json;[print(r['seq'],r['muninn']) for r in json.load(open('progress.json'))['decisions_absorbed']]"`,
  or `grep '"command": "decision\.' <agentic-loop dir>/<session_id>/trace.jsonl`. Chain check:
  `python3 -c "import json,sys;sys.path.insert(0,'.');from scripts.lib import decision_record as d;print(d.verify_chain(json.load(open('progress.json'))['decisions_absorbed']))"`.
- Fix: read the reason in the table above. An authorising prompt of "yes" (`cite_too_short`) is expected to degrade: at
  teardown run `flush_pending(path, session, transition=..., cite_quote="<a substantive sentence the owner typed>")`;
  the same `seq` is patched to `written`. Rows are never deleted or rewritten to clear a degrade.
- Limits: the chain is a cooperating-agent safeguard (a same-user agent can rewrite file and chain), and dropping the
  last row is detected only by the in-file head anchor, which the same agent can also rewrite. Measurement note: `docs/typed-records-measurement.md`.

## Standing order stored without a cite, or a lesson missing from dispatch

- Symptom: `orders.py record` exited 3 with `muninn.reason_code` (`no_user_cite`, `muninn_absent`, `cite_*`), or
  `lessons.py query` / `orders.py lessons` exited 3 with `{"degraded": ...}`, or an order you recorded is absent from the
  list. Before completion, `record` stages bound inputs and syncs the cited claim without lifecycle effects. After
  owned progress is durably complete, local apply records recurrence and aging in `orders.json`. A degraded store
  result retains any prior K-id. `lessons` never prints ledger text when Muninn is down (`memory.backend: off` is the
  explicit switch). Trace rows: `order.record|prepare|tick|render|import|cite`, `lesson.query|predicate`.
- Query: `python3 scripts/lib/lessons.py --dir <repo-key dir> --session <known native caller id> query --format contract`
  reads current cited lessons. Diagnostic `orders.py ... lessons` also returns an `excluded` list naming entries
  is retracted, expired or superseded, reason `lesson_not_current`), or
  `grep -E '"command": "(order|lesson)\.' <agentic-loop dir>/<session_id>/trace.jsonl`. A hand edit of `orders.json` is
  refused with `order_chain_broken` naming the order.
- Fix: read the reason in the table above. For `no_user_cite` / `legacy_uncited` run
  `orders.py --dir <repo-key dir> cite <id> --quote "<verbatim words the owner typed>"` from the owning session. To
  adopt the old hand-written file run `orders.py import-legacy`. It archives an exact byte copy under the next free
  `standing-orders.legacy*.md` name and retains the source (`archived_to`, `source_retained: true`). Check the ledger
  and archive; retire the hand-written `standing-orders.md` before `orders.py render`. Use typed orders thereafter.
- Apply contract: use `--dir <repo-key dir> --session <provider session>` with the separate logical `--loop` copied
  from `<repo-key dir>/<session>/progress.json`. Stage `record` inputs before completion. The native `graph.py
  complete` command prepares orders before the progress lock, rechecks the prepared source under that lock, saves
  completion, then ticks and renders after it releases the lock. Claude `mark-complete` uses this same path and also
  stamps the invocation marker. Preparation ages nothing. The tick holds the orders lock and records `orders_ticked`
  after its ledger save. A failed completion save ages nothing. Repeat the native completion command to resume a
  pending tick or render without a second age change; do not edit `progress.json`.
  Render holds the orders lock while it writes both views. The receipt checks the ledger and both view hashes under
  that lock. If they differ, completion stays pending; repeat the native completion command to render again.
  The Claude Stop guard and Codex `verify-completion` block when the tick or bound generated views are incomplete.
  If render fails on the installed Muninn API, the pending result and later verifier show its actual reason code.
  The installed Muninn uses a current request-bound API that this D4 adapter does not support. Treat live lesson
  activation as pending; do not use ledger text as a substitute for a current cited claim.
- Pre-D4 complete loop: review its retained evidence before the exact-hash admission. The receipt then follows only
  completion bookkeeping; other graph changes still block. See `docs/decisions/2026-10-05-orders-vs-muninn-overlap.md`.
- Completed text replacement: when this session/loop observation already exists, explicit `record` captures
  `replaces_source` in the prepared row. The canonical `lesson_source` hashes owned binding, authored fields and that
  predecessor, excluding mutable store observations, and is sealed/saved with the lesson. Ordinary tick recovers only
  the accepted row while preserving counters and evidence; an equal published token needs no replay. A later authored
  source is preserved. Without an exact validated success receipt for this preparation, a conflicting retry stays
  pending and emits no false completion receipt. Older absent predecessor fields are never retroactively invented;
  a captured null is distinct and cannot authorize delayed replacement without its own published source or exact
  validated acknowledgement, even if no later edit occurred. Direct completed explicit record remains available.
  Publication, receipt loss and then a later replacement can remain pending because these
  two retained facts do not prove historical application. Unbound pure-model record updates clear an old source token.
- Preparation recovery: changed sources are refused by default. Before completion, use
  `prepare --loop <logical loop> --refresh-from-sha256 <CURRENT evidence_sha256>` only with the canonical hash returned
  by the current preparation. Comparison happens under the same orders lock. Resolved directories, session and
  logical loop must match; revision cannot roll back, and no matching local tick or recurrence may already exist.
  Staged records are preserved, with no lifecycle effects. Wrong/stale hashes, invalid/foreign/complete sources and
  prior application refuse unchanged. A durably saved replacement with a failed preparation receipt leaves progress
  incomplete; ordinary unchanged `prepare` repairs the receipt without another replacement or duplicate observation.
  After durable completion, retry `tick` only. Flush and reload pending source updates before final prepare/refresh.
- Receipt publication: D4 refuses linked preparation, receipt and persistent sidecar paths before read/open/create.
  It holds orders.lock, then `teardown.jsonl.lock`, and validates every prior physical LF JSONL object, finite JSON
  number and terminal newline before deduplication, preserves prior bytes, and atomically publishes a complete
  fsynced sibling. Short writes make progress until complete; a zero write or partial-write exception leaves canonical
  evidence untouched. An ambiguous error after replacement needs an ordinary prepare/tick retry, without duplicate
  lifecycle effects. Pre-existing malformed or newline-less evidence is refused untouched; restore genuine evidence,
  never truncate or skip a tail. Other teardown publishers must adopt the same sidecar/framing/atomic publication
  contract to preserve concurrent events. D6 adoption remains pending; its latest-step dedupe policy is separate.
- Shared identity: an id binds failure mode and scope across the ledger and every valid retained preparation before
  record/cite sync or local application. Historical preparations still constrain identity after progress advances;
  they establish no present eligibility, currentness, citation or lifecycle effect. Same identities in other sessions
  are accepted recurrences; conflicts and foreign/malformed stored bindings refuse before superseding a store claim.
- Current citation: explicit `record` alone may replace lesson text. `cite` reconciles the current tagged claim even
  when the ledger holds older text, without a knowledge write. A formerly cited id without a current replacement
  refuses; a genuinely uncited first attachment still validates the owner's quote. Distinct simultaneous current
  claims refuse as `lesson_not_current`. Tick performs current reads without knowledge writes; outages retain saved
  K-ids over stale preparation metadata and return explicit degradation. Idempotent tick retry may refresh metadata
  without repeating lifecycle effects. Promotion uses the current cited join, independent of cached write state.
- Limits: the one same-user orders lock covers currentness, reconciliation, bounded sync and direct atomic ledger
  save; it provides no exactly-once network guarantee. Current tagged claims are reconciled even for degraded/pending
  local records. Only a new completed session+loop recurrence resets a counter or revives a tombstone; replaying the
  same observation cannot rejuvenate it. Authoritative dispatch, promotion and views use current, normal, live,
  verified user-cited claims. Diagnostic `orders.py lessons` may show uncited rows (`cited: false`); contract queries,
  promotion and views exclude them. Owner-cited lesson text is legitimate typed memory; advisory transcript
  observations remain metadata only. Failed reads exit 3, with no ledger-text fallback. A fresh cited claim can
  supersede prior text. Legacy import retains full source text and first-seen provenance, preserves decayed counters,
  and refuses incomplete/colliding entries or an external source path without changing the original.
- Legacy retry: each row seals the SHA-256 of the exact source bytes. `import-legacy` skips a complete cohort only
  when saved rows, timestamp and source hash match. It reuses only an exact archive, else publishes a new copy without
  replacing an occupied name. Mixed or divergent rows refuse. Archive publication precedes ledger save. A failed or
  uncertain save keeps source and archive; success requires a canonical ledger equal to the expected sealed rows.
- Graduation still requires >=10 distinct completed source-bound retros, recurrence and decay. Schema2 records need
  complete typed fields and their genuine completed progress hash. Schema3 delegates to `retro_check.check`; an absent
  validator returns `order_retro_validator_unavailable`, rather than a known zero count. Both ledger and source hashes
  remain a cooperating-agent safeguard: the same user can rewrite and recompute them.
  Measurement note: `docs/typed-records-measurement.md`; overlap decision:
  `docs/decisions/2026-10-05-orders-vs-muninn-overlap.md`.
- Lesson attribution: pass the known native caller id with `--session`. The CLI also recognizes CLAUDE_SESSION_ID,
  CLAUDE_CODE_SESSION_ID, CODEX_THREAD_ID and CODEX_SESSION_ID, in that order; explicit input wins. Joined reads carry
  that id through query, predicate, diagnostic lessons and render to underlying degraded adapter traces. Environment
  support in source and private fixtures does not prove a variable is exported in an installed provider session.

## A stop has no recorded row

- Symptom: the Stop hook blocks with `stop_row_missing`. Final text cannot release it. Run `graph.py stop` in the
  current turn with a valid category, reason code, reason, state path, and session. The command writes `stops[]`.
- Query: run `python3 scripts/graph_alignment_stops.py --json` for `stops_recorded`, `stops_consumed`, and
  `stop_row_missing`. Run `python3 scripts/lib/stop_counters.py` for refusal codes. A stale row reports
  `stale_stop_row`. The hook owns `loop_stop_counts`; never edit it or `stops[]` by hand.
- Remediation: use the refusal code from `graph.py stop`. A foreign session, unknown category or reason code, or
  unresolved graph on `complete` needs a source correction. A valid row is consumed once. Codex can release an
  `awaiting-input` or `approval-gate` row while graph work is pending. `complete` needs a resolved graph and its evidence.
  See `docs/graph-alignment-measurement.md` for limits and commands.

## Diff-manifest check warned or refused

- Symptom: `push.py`, `merge.py`, a direct `gh pr merge` (Claude `enforce_pr_workflow`, Codex `pr_publication_gate`)
  refuses with `diff_manifest:<code>` and prints `! diff_manifest <code>: <path>` on stderr. The check is ON by default
  (`diff_manifest: enforce`, no config file needed, shipped policy `policy/diff-policy.default.json`); `off` and
  `advisory` (warn only) are the explicit switches. `scripts/diff_manifest.py [--policy FILE]` is a diagnostic verdict
  reader: it reports unreadable inputs with exit 0; the publication callers refuse them under enforce.
- Query: `trace.by_reason` for `diff-manifest/ok/diff_manifest_ok`, `diff-manifest/warned|refused/<code>` (rows are keyed by
  `<repo>@<branch>` or `<repo>@pr-<N>`), `publication/refused/diff_manifest:<code>` (one row per refusal from the single
  publication gate, every path), plus `diff-manifest/failed_open/manifest_unreadable` (advisory only),
  `diff-manifest/legacy/manifest_legacy_absent` (policy file without a manifest key; also written by the gate) and `diff-manifest/refused/foreign_session`. Tally them with
  `python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/workflow_gate_counters.py`
  (`manifest_counters.py` still tallies only `diff-manifest`). See `docs/workflow-gates-measurement.md`.
- Codes: `out_of_manifest`, `denied_path`, `docs_sync_deny`, `docs_sync_deletion`, `not_linked_worktree`, `special_file_type` (type change, symlink or gitlink), `mode_change`, `status_not_allowed` (policy `statuses`), `too_many_paths` (policy `max_paths`), `manifest_unreadable`, `manifest_internal_error`, `diff_manifest_mode_invalid` (unknown mode, treated as enforce).
- Remediation: a real violation means the diff left its declared scope; fix the diff, or widen `unit.manifest`
  (re-register with `add-unit --manifest`) or the policy file on purpose. `push.py`/`merge.py --unit N --progress PATH`
  bound the diff to that unit's manifest. `manifest_unreadable` means the policy file, progress.json or diff (or an
  unresolved PR head) could not be read: it refuses under enforce (fails open only under advisory); fix the path.
  `manifest_internal_error` refuses under enforce; advisory records `failed_open` and continues, including when repository
  metadata lookup fails. Set `diff_manifest: off` to disable. Invalid modes, including an empty mode, enforce and report
  `diff_manifest_mode_invalid`. A null policy value selects the shipped default; the typed config grammar also coerces
  an empty nullable scalar to null.
- Limits: a cooperating-agent safeguard. A same-user agent can edit the config to `off`; direct hooks only see merges
  `guarded_segments` can match; Codex hooks need `/hooks` trust before they run. Claude checks the manifest even without
  config or a transcript; its review/eval sequence still needs both.
- Hardening notes: `mode_change` refuses a chmod (100644 to 100755). The default denylist is best-effort secret shapes
  (`.env*`, `*.pem`, `*.key`, `*.p12`, `credentials*.json`, `.npmrc`, `.netrc`, `.git-credentials`, `id_rsa|dsa|ecdsa|ed25519*`)
  and the gate's own files (`.coderails/workflow.config.yaml`, `policy/diff-policy*.json`, the Codex copy), so a PR that
  edits or deletes them is refused; deleting a secret-shaped path is allowed. It cannot catch a secret under another name. The gate reads config
  and policy from the local checkout: a same-user boundary, not a defence against someone who controls that checkout.
  `--unit` without `--progress` (or the reverse) refuses `manifest_unreadable`. Both separated and `--unit=N`/`--progress=PATH`
  forms are supported; empty or repeated flag values refuse. A requested unit must exist and carry a string-list `manifest`
  and a nonblank absolute `worktree` whose real path equals the current Git repository root. The progress object must carry
  nonblank string `session_id` and `loop_id` fields. Missing, malformed or mismatched metadata refuses `manifest_unreadable`;
  `manifest: []` allows no changed paths. A session that owns a graph unit in this worktree must supply both flags.
  Without a matching graph unit, standalone publication uses the policy alone. Unit and policy
  manifests both apply, so a unit cannot widen policy scope. Custom policies retain the default denylist. An unreadable config
  refuses `manifest_internal_error` and emits its refusal trace. Direct-merge hooks parse
  the target with `scripts/lib/merge_target.py` (flag values skipped, URL and branch resolved through gh); `-R/--repo`, another
  repo's URL, multiple targets or an unknown branch deny `pr_number_invalid`; `GH_REPO` retargeting denies `pr_repo_override`.
  A same-call `gh pr edit` or `gh api .../pulls/N` plus merge denies `pr_base_mutation`; make the edit in a separate call so the next check sees
  the new base.
  The diff uses the PR's live `baseRefOid` and checked head, not the local default branch. `merge.py` accepts one number, URL or branch
  and pins all gates and the merge to the same head
  with `--match-head-commit`; a hook
  cannot pin the agent's own `gh pr merge`, so a push or out-of-band base retarget between the hook check and that merge
  is a known gap. Unit metadata
  is a shape and worktree check, not publisher authentication: a same-user actor can forge owner fields for the same
  worktree. It does not compare a worker's session with its parent's. Raw Git operations and unseen aliases remain
  outside this manifest arm.

## Required review passes refused a merge

- Symptom: `merge.py`, a direct `gh pr merge` (Claude `enforce_pr_workflow`, Codex `pr_publication_gate`) refuses with
  `required_review_missing:<name>`, `required_review_failed:<name>`, `review_passes_malformed`,
  `review_artifact_missing` or `review_policy_unreadable`. The check is the second entry of the single publication gate
  (`scripts/lib/publication_gate.py`), ON by default with no config. The required names come only from
  `policy/review_policy.json` (`review-pr` always; `security-review` for `hooks/`, `scripts/`, `install.py`,
  `uninstall.py`, `.claude-plugin/`, `packages/codex/hooks/`, `packages/codex/scripts/`, and the control files
  `policy/`, `capabilities/`, `agents/`, `commands/`, `AGENTS.md`, `workflow.config.yaml`, `.coderails/`, their Codex
  copies and the Codex post-review/merge skills; `deploy-safety` for `launchd/`,
  `scripts/integrity-gate/`, `scripts/installer/`, `.github/workflows/`, `skills/dashboard/runner/`), matched against
  the PR diff from its live `baseRefOid` to the checked head (renames count both sides). Config `review_passes: off` skips the check (absent or any other value
  enforces; `diff_manifest: off` does not touch it). The policy file is the control, and deleting or corrupting it
  refuses (`review_policy_unreadable`), it does not allow.
- Artifact: line 1 is the unchanged v1 marker; line 2 is `<!-- coderails-review-passes v1 {"head_sha":...,"passes":[...]} -->`
  with `{name, verdict, blocking, summary_sha256}` per pass. `post_review.py post <PR> --summary FILE [--pass NAME=FILE ...]`
  validates each summary, derives each verdict from the text (a bullet under `## Critical` is `fail`) and posts it. A v1
  artifact with no passes line counts as no passes: `review-pr` is satisfied by the marker, but a `hooks/` PR is refused
  until it is re-posted. A passes line naming another `head_sha` is ignored.
- Query: `trace.by_reason` for `review-passes/ok/review_passes_ok` and `review-passes/refused/<code>`, plus
  `publication/refused/<code>`. Tally with `python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/workflow_gate_counters.py`.
- Remediation: spawn the missing reviewer (`security-reviewer`, `deploy-safety-reviewer`; both providers ship them),
  write its findings to a file in the post-review grammar, re-run `post_review.py post` with `--pass NAME=FILE`. A
  `failed` pass needs the Critical finding fixed and the artifact re-posted for the new head. `review_artifact_missing`
  also covers a failed trusted-comment fetch (identity, permission, comments): retry or check `gh auth`.
- Limits: the gate re-derives each pass from the posted sections (hash and verdict; a mismatch is
  `review_passes_malformed`), so a hand-posted passes line without its text is refused. A pass still proves only that a
  summary was posted for that name, not that a reviewer wrote it or that the review was substantive: `post_review.py`
  takes any file for any pass, so the PR author can self-issue a `## No findings` security-review or deploy-safety
  pass. The same user can write any summary, so this is a cooperating-agent safeguard. `blocking` is derived and never waives a
  required pass. The Codex hook only sees merges `guarded_segments` can match and needs `/hooks` trust. Row-9 wording in
  the closure matrix (`.json` policy file) is not recorded in this repo: the matrix lives outside it.

## Action-authority hook denied a merge or push (or warned in advisory)

- Symptom: `gh pr merge` or `git push` to main/master is denied with "needs an action receipt (<code>)" (enforce), or a
  stderr "action_authority (advisory)" warning appears. The gate is off unless config explicitly sets
  `action_authority: enforce` or `action_authority: advisory`.
- Query: `jq -r 'select(.command=="action_authority" or .command=="action_receipt") | [.outcome,.reason_code]|@tsv' <loop dir>/<session>/trace.jsonl`,
  or `trace.receipts.by_reason_code` from `python3 scripts/measure_graph_alignment.py --root . --json` (deduped by
  event_id). Codes: `denied_<code>` / `advisory_<code>` where `<code>` is one of `no_receipt`, `hash_mismatch`,
  `repository_mismatch`, `ref_mismatch`, `sha_mismatch`, `signature_missing`, `signature_invalid`, `signer_unknown`, `trust_root_missing`, `binding_unknown` (repository+ref+sha not computable: fail closed), `state_mutated_before_guard` (a ref/HEAD/remote-moving step precedes the guarded one in the same command), `expired`, `revoked`, `consumed`, `foreign_session`, `foreign_loop`, `kind_mismatch`, `no_session` (payload had no session_id; traced under session dir `_no_session`), `malformed`;
  `receipt_consumed` (allowed); `trust_root_user_tier` (an allow that rested on the agent-writable trust root: cooperating-agent safeguard); `action_authority_failed_open` (advisory without loaded live authority errored and allowed); `denied_gate_error` (unexpected error under enforce or loaded live authority); `denied_budget_lock_unavailable` / `denied_budget_release_failed` (merge budget lock or cleanup failed; ambiguous reservation remains spent);
  `receipt_approved` / `receipt_revoked` / `receipt_refused_no_tty` (CLI).
  Authority codes (also from `enforce_pr_workflow`, which denies before consuming anything): `denied_authority_denied` (the session's authority lists the category in `denied`; a receipt cannot override it),
  `denied_max_prs_exceeded` (executed merges in the session, counted from `.executed` markers of every merge receipt whatever its `authority_id`, reached `max_prs`; 0 = none; narrow/grant again with `authority.py`), `approval_requirement_missing` (a guarded action's permit verdict omitted its required approval; refused before consuming a receipt), `authority_denied_destructive_shell` (destructive gate, force-with-lease family),
  `scripts/merge.py` rows are `merge_py_<code>` (refused: `no_receipt`, `no_session`, `binding_unknown`, `sha_mismatch`, `consumed`, ...)
  and `merge_py_receipt_executed` (allowed). Counters: `scripts/lib/receipt_counters.py` `gate_summary(by_reason)` (the CLI below prints it as `gate`; wiring it into `measure_graph_alignment.py` itself is a handoff to the lane that owns that file).
  Optional enforce-mode mint command for a merge: `python3 scripts/action_receipt_cli.py approve-action --session <id> --kind merge --command 'python3 <absolute merge.py path> <N> --expected-head <40-hex PR head>' --cwd <repo dir>`;
  `gh pr merge <N> --match-head-commit <40-hex PR head>` works with its own exact command text. `max_prs` counts every executed merge receipt in the session, including one minted before the authority was granted.
- In advisory mode, a live authority reserves a budget slot before a plain `gh pr merge` runs. The hook cannot read
  that command's result. A failed command can leave a pending entry in `<loop dir>/<session>/merges/` and block a
  later merge. Check the exact PR and head on GitHub. If the merge did not happen and the PR is still open, an
  operator can release only that pending entry with `scripts.lib.merge_budget.settle(path, False)` while holding
  `merge_budget.lock(session)`. Keep completed entries; they record used budget.
- If reservation cleanup or lock teardown fails, the hook denies the command. It keeps any reservation whose
  release is uncertain. Check the PR and head before releasing a pending entry by the procedure above.
- `action_authority_failed_open`: the row carries `inputs.error_class` (sha256 of the exception class name; compare with
  `printf ZeroDivisionError | shasum -a 256`) and `loop_id` when known; the hook's stderr (hook log) prints
  `action_authority failed open: <Class>: <message>`. A session-less failure is traced under `_no_session`.
- `marker_write_failed` or `executed_marker_unavailable`: a receipt note or execution marker failed. The hook
  denies the command and rolls back only this batch's new markers while holding its claim lock.
  `marker_cleanup_failed` means cleanup failed: consumed markers stay in place if execution state is uncertain.
  Fix the file fault and mint a new receipt. A killed hook can leave a partial spend; confirm the command did not
  run before any manual recovery.
- Remediation for optional enforce mode: one-time `python3 scripts/authority_keys.py init` (passphrase-protected
  key; `show` prints fingerprints), then mint for the exact command:
  `python3 scripts/action_receipt_cli.py approve-action --session <id> --kind merge|git_push --command '<exact command>' --cwd <directory it runs in>`
  (single-use, 1h by default; the CLI computes repository+ref+SHA itself, signs, and refuses without a tty with
  `receipt_refused_no_tty`; add `--loop <loop id>` when the session authority has a loop; `inspect-receipt` /
  `revoke-receipt` take `--receipt-id`). `signer_unknown` / `trust_root_missing`
  mean the signers file does not list the key that signed (or does not exist). `hash_mismatch` means args, cwd or branch differ from the minted
  command; `sha_mismatch` means HEAD (push source) or the PR head moved since minting: re-mint. `git push origin feature:main` binds
  the sha of `feature`, not HEAD. `foreign_session` means the receipt was minted for a different `session_id`: subagents share their parent's `session_id`, so mint under the session the hook reports. Or set `action_authority: off` in `.coderails/workflow.config.yaml`.
- Scope of one receipt: each guarded segment of a chained command (`a && b`) needs its own receipt; a leading
  `cd <dir>` moves the directory the hash binds (mint with `--cwd` set to where the command really runs). The binding comes from
  `scripts/lib/action_binding.py` (push: refspec source sha and destination ref; merge: live PR head via `gh pr view`, 4s timeout);
  unknowable means `binding_unknown`, fail closed. Bindable forms only: `git [-C dir] push <remote> <ref>` (no env prefix,
  `-c`, `--git-dir`; a push without an explicit refspec is guarded but is `binding_unknown`; `HEAD` alone means the current branch; the repository is the push url) and
  `gh pr merge <n> --match-head-commit <live head sha>` (or `gh api .../merge -f sha=<sha>`).
  `scripts/merge.py <n> --expected-head <live head sha>` binds a helper receipt. Bare `scripts/merge.py <n>` is
  unbindable under receipt enforcement because it fetches the head after the hook. The receipt must name the same
  helper path that runs. For Codex this is the absolute `packages/codex/scripts/merge.py` path.
  Use `python3 <absolute helper path>` for enforce mode. Direct executable invocation is unsupported because it has
  a different command hash.
  `gh api --method PUT .../pulls/<n>/merge-async -f sha=<sha>` is guarded but unbindable: GitHub may merge open
  downstack requests too, so one receipt or budget slot cannot cover its effects. Enforce mode and advisory mode
  with a live authority deny it. Advisory mode without live authority warns and permits it.
  Run ref-moving steps (`commit`, `branch -f`, `reset`, `config`, ...) as separate commands before the guarded one.
- Counters: `python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/receipt_counters.py` prints `receipts`
  and `trust` (signature, trust-root, binding and `state_mutated_before_guard` counts). Measurement: one hook run is well under 1 s
  with one receipt (single run, not a benchmark; 50 receipts could approach the 10 s hook timeout).
- Residuals (docs/decisions/p3-human-only-minting.md): `.consumed`/`.revoked` markers are agent-writable files, so unlinking one
  replays or un-revokes a receipt until it expires; junk files can crowd the 50-receipt cap (deny, not allow);
  unexpected errors deny under enforce or loaded live authority, and fail open in advisory without live authority.
  An unreadable authority file appears absent in advisory mode. A same-user agent can also write a deeply nested file (`[` x 7000) into `authority.json` or `receipts/`: it is read
  as malformed (`RecursionError` is caught in `read_receipt`/`read_authority`), so it denies rather than crashing the hook open; it is the
  same same-user class as the markers above.
- Unmatched merge routes (Limits): `gh api` merge forms are matched with the endpoint anywhere in argv and the GraphQL
  `mergePullRequest`/`enablePullRequestAutoMerge` mutations (unbindable, so always denied); other routes (the web UI, `git merge` into main via
  a script, a tool that calls the API directly) are not seen by any command hook.
- Codex: the hook imports the byte-identical mirrored libs and the package ships `scripts/action_receipt_cli.py` and
  `scripts/authority_keys.py` (same owner-run rules).
- Limits: the user-tier trust root (`~/.coderails/keys/receipt_signers`) is agent-writable, so it is a
  cooperating-agent safeguard. An agent with Accessibility or control of the owner's terminal is out of scope
  (docs/decisions/p3-human-only-minting.md). The hash covers only the command text the hook sees, not aliases, functions, eval/xargs or scripts that
  push (sudo/time/subshell/`bash -c`/`gh api .../merge` wrappers are unwrapped; an env assignment prefix is kept and makes the command unbindable). Limits: scope 500 chars, 8 KB per receipt,
  50 receipts per session (`receipt_refused_scope_too_long`, `receipt_refused_too_many`). Protected branches are main and master only.

## Typed state, verdicts and attestation (merge blocked by `attest_*`, eval verdict, hook state)

- Symptom: `gh pr merge` or `merge.py` is refused with `attest_missing`, `attest_not_success`, `attest_wrong_creator`
  or `attest_not_bound`. One parser (`scripts/lib/integrity_attestation.py`, mirrored byte-identically into
  `packages/codex/scripts/lib/`) is the only code that knows `integrity=pass` / `sha=`; `integrity_status.py` (merge.py)
  and `pr_merge_gate.py` (hook) fetch with `gh` and render the message from its closed code.
- Query: `python3 scripts/lib/state_counters.py [--since <ISO ts>]` counts `attest_*` (trace `pr_merge_gate/denied/<code>`,
  written when the hook payload carries a session id), `hook_state_unreadable`, `nudge_first`/`nudge_suppressed` and
  `eval_verdict_<status>`.
- Remediation: `attest_missing`/`attest_not_success` mean the root-owned daemon has not attested this head yet (wait or
  push a fresh head); `attest_wrong_creator` means `integrity_review.machine_user` disagrees with the status poster;
  `attest_not_bound` means the description is not exactly `integrity=pass sha=<head>` as whole tokens. Never bypass.
- Limit: the daemon (`scripts/integrity-gate`, root-installed separately) does not import the parser; a test asserts the
  daemon's real success description parses. Codex has no PreToolUse merge hook; only `integrity_status.py` applies there.
- Eval verdicts: `loop_evals.read_loop_evals()` returns a frozen `EvalVerdict{status, tamper_code}` (`status` is one of
  GO, VERIFICATION_LEVEL0, FROZEN, NO-GO, ABSENT, UNJUSTIFIED, UNSTAMPED, STALE, TAMPERED); callers match on the fields,
  never on `TAMPERED:<code>` text. A blocked completion writes trace `loop_state_guard/blocked/eval_verdict_<status>`.
  The cost line in the retro is a `CostReport{state, message}` whose state is logged as `cost_report=<state>`.
- Readiness: `graph_readiness.py <progress.json> <node>` prints JSON `{"ready": bool, "reason_code": ...}` (exit 0 iff
  ready): `ready`, `predecessor_pending`, `node_unknown`, `node_not_pending`, `graph_blocked`,
  `join_not_dispatchable`, `state_unreadable`. A missing script or non-JSON output is a
  resolution failure, not a not-ready verdict. Not-ready verdicts on a readable state write trace
  `graph_readiness/not_ready/<code>`; `state_unreadable` has no session to trace under. Every `progress.json` write now
  carries `updated_at` (Claude `atomic_progress_update`, Codex `graph_io.write`); a refused transition leaves bytes unchanged.
- Hook state: `<loop dir>/<session>/hook_state.json` `{schema_version, ordinals{absent_blocked}, arms[{hook,ordinal}],
  nudged{<hook>:true}}` is the only source for absent-state grace and `offload_push_guard` / `unregistered_loop_guard`
  nudge dedupe (exact session directory, so session `ab` never matches `abc`). `discipline.log` is audit output and is
  never read for these decisions. A missing or torn file never releases grace and is traced
  `hook_state_unreadable` (outcome `missing` on the first Stop of a session, which is expected once; `torn` is a fault).
  A torn file also suppresses the nudge, traced the same way: an advisory must not repeat unrecorded. Nudges trace
  `nudge_first` / `nudge_suppressed`. Remediation for `torn`: delete the file by hand (the hook will not repair it).
  Limit (same-user boundary): `hook_state.json` is a plain file owned by the session user, so state is advisory, not
  tamper-evident. An agent with Bash/Write can pre-create it (an `ordinals.absent_blocked` equal to the current
  invocation count releases absent-state grace with no prior block) or set `nudged.<hook>=true` to silence a nudge.
  Grace and nudge dedupe are guard-rails against accident, not a defence against a hostile same-user agent.
- Limits: Codex has no corresponding hooks (`hooks.json` carries no `loop_state_guard`, `offload_push_guard` or
  `unregistered_loop_guard`), so hook state, `EvalVerdict` and `CostReport` are Claude-side; Codex gets the shared
  attestation parser and the `updated_at` stamp. `mine_hook_blocks` still counts the log's exact `session=` token;
  moving it to trace rows needs every gate to emit rows (Phase 6).

## Graph refused with `spec_*`, or `instantiate` refused

- Symptom: any graph command (`inspect`, `begin-wave`, `add-unit`, `complete`, ...) fails with `spec_edge_missing`,
  `spec_unknown_node`, `spec_node_missing` or `spec_hash_mismatch`; or `graph.py instantiate` fails with
  `instantiate_refused_<foreign|state|nonempty|bad_id>`.
- Query: `python3 scripts/lib/spec_counters.py [--since <ISO ts>]` counts those codes plus `instantiate_ok`,
  `instantiate_noop` and `skip_when_met` (one count per `plan` call in which a node's skip predicate held). Each refused
  load also leaves a `load/refused/<code>` row in the loop's `recovery-trace.jsonl`.
- Remediation: `spec_edge_missing` names the missing edge (for example `J2.8 -> U3[2]`): the spec requires it whenever both
  nodes exist, so add the edge by registering units with `graph.py add-unit` (which wires it) rather than editing
  `progress.json`. For a graph stamped by `instantiate`: `spec_hash_mismatch` means `graph-spec.yaml` changed after the
  graph was built (finish that loop on the old spec checkout, or start a new loop); `spec_unknown_node` /
  `spec_node_missing` mean nodes were added or removed by hand. `instantiate` builds only into an empty started loop
  (`instantiate_refused_nonempty` otherwise); a re-run with the same profile and units is `instantiate_noop`.
- Edit the graph structure in `packages/graph-semantics/graph-spec.yaml` / `policy.yaml` (JSON syntax) and run
  `python3 scripts/gen_graph_docs.py`; `scripts/tests/gen_graph_docs_test.py` fails the run when the generated tables drift.
  The installer materializes both files next to `graph_spec.py` in each provider's `agentic-loop/scripts`.
- Off-switch: `CODERAILS_GRAPH_SPEC=off` (also `0` or `false`) in the environment skips the whole spec check on load
  (default ON; unset to re-enable). Use it only to rescue a loop whose graph a spec change has stranded, then rebuild it.
  `spec_join_inputs` (a stamped graph's join is missing or lacks a unit's input) and `spec_profile_downgrade` (the stamp is
  below `policy.yaml` `graph.profile`) are the other refusal codes.
- Limits: `policy.yaml` default `graph.profile` is `full`. Every spec node must belong to FULL; a spec
  that removes one from FULL is refused with `spec_profile` before instantiate. `instantiate --profile units-only`
  requires the owner to lower the policy floor to `units-only` first; the flag alone is refused. Spec edges are
  enforced only between nodes that exist, so an unstamped (hand-built or `start`-built) graph that never creates `J2.8` or
  the prep nodes is not refused: making `start` stamp via `instantiate`, or having `plan`/`begin-wave` refuse an unstamped
  graph once `full` is chosen, is an open owner decision. Join inputs are enforced on stamped graphs only. Downgrade path:
  a hand-editing agent can delete `graph.spec_sha256` (back to the weaker unstamped check) or rewrite `spec_profile` and drop
  the extra nodes, edges and joins; the policy profile floor refuses the second only while `policy.yaml` says `full`.
  `loop_evals_min_units` is documented but not read by any hook yet. Judgement skip rules (irreversible-surface triggers,
  `no PR` units) stay prose: `skip_when_met` is only the machine predicate and is a hint, not a recorded skip. Same-user
  boundary: the spec, policy and `progress.json` are plain files the session user can edit; this is drift detection for a
  cooperating agent, not tamper evidence.
