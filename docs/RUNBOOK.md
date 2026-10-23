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
  trace), but the guarded actions below fail closed. `wiki_schema_legacy` means a vault still has only
  `AGENTS-wiki-schema.md`: policing continues from its Page types table; add `wiki.schema.json` to retire the fallback.

## Guarded action denied: config_rejected or wiki schema fail-closed

- Symptom: `gh pr merge` or `git push` to main (action-authority hook), `push.py`/`merge.py` (diff-manifest check) or a
  write inside the wiki vault is denied with `config_rejected` ("did you mean ..."), `wiki_schema_missing` or
  `wiki_schema_invalid`.
- Query: trace rows `action_authority/denied/config_rejected`, `diff-manifest/refused/config_rejected`,
  `wiki_taxonomy_gate/failed_closed/<config_rejected|wiki_schema_missing|wiki_schema_invalid>`; counts via
  `python3 scripts/lib/config_counters.py` (`config_rejected`, `config_bad_value`, `wiki_schema_fail_closed`).
- Remediation: run `python3 scripts/lib/config.py resolve-config --json`, fix each finding (typo'd key, wrong type, value
  outside the enum), or restore `wiki.schema.json` (`page_types` non-empty list of directory names). Only the guarded
  action is denied; every other command and tool passes. With NO config file nothing is read and every gate stays inert
  (repos not using coderails), and an ambiguous wiki identity (no `wiki_path`, other repository, vault not a directory)
  still allows.
- Limit: the controls are only as strong as the config file. A same-user agent can `mv` it away (every gate goes inert)
  or edit a control to `off` in place; no hook guards `.coderails/workflow.config.yaml`. Review config diffs like code
  (the diff-manifest policy can list it as a protected path). `evals.require_signatures` fails closed: only an
  explicit `false` turns it off. Malformed lines and duplicate keys are `config_unparseable_line` /
  `config_duplicate_key` findings.
- Defaults: an existing config with no other keys turns the controls ON (`sandbox_workers: true`,
  `evals.require_signatures: true`, `diff_manifest: enforce`, inert until `diff_manifest_policy` names a file); each is a
  one-line opt-out. `action_authority: enforce` is also ON by default now that both providers ship the owner-run receipt
  CLI; explicit `off` opts out and `advisory` warns without blocking.

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
- Cause: by design the five guarded agents hold only `mcp__plugin_coderails_cap-<role>__*` tools (+`Skill` for
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

## Memory silently using Markdown

- Symptom: retro lessons or handoffs never appear as typed records; `memory_adapter.py probe` exits 3.
- Query: `python3 scripts/measure_graph_alignment.py --root . --json | python3 -c "import sys,json;print(json.load(sys.stdin)['memory'])"`
  (`by_reason_code`, deduped by `event_id`), or `grep '"command": "memory\.' <agentic-loop dir>/<session_id>/trace.jsonl`.
  Codes: `muninn_absent`, `muninn_old_ledger`, `muninn_timeout`, `muninn_error`, `uncited_write`, `restricted_refused`,
  `bad_record`, `handwritten_protected`. An unsafe session id writes no row; an unset or empty session id
  (CLI without `CLAUDE_SESSION_ID` or `--session`) writes rows under the fixed id `memory-adapter-nosession`.
- Remediation: `muninn_absent`/`muninn_old_ledger`: install a muninn release with the typed-ledger flags (Part A, muninn
  PR #9); the Markdown path keeps working meanwhile. `uncited_write`: pass `--cite` and a verbatim `--quote`.
  `handwritten_protected`: the target is hand-written; render to a new path. `muninn_timeout`: muninn hung past 10s;
  run `muninn know list` by hand and check ledger locks. `muninn_error`: muninn exited nonzero or returned unparseable
  JSON on add/list; run the same `muninn know ...` command by hand and read its stderr. `bad_record`: the typed record
  failed validation (type, scope, tag, date or missing loop id). A help probe that exits nonzero is reported as
  `muninn_old_ledger`, not `muninn_error`.

## Stop declared in text instead of recorded, or a stop released unexpectedly

- Symptom: the Stop hook releases or blocks a loop and the model says it recorded nothing; or `progress.json`
  `loop_stop_counts` disagrees with the declared turn category. Stops are model-written intent rows
  (`progress.stops[]`, written by `graph.py stop`); `loop_stop_counts` stays the hook-owned count of consumed stops.
- Query: `python3 scripts/graph_alignment_stops.py --json` gives `stops_recorded`, `stops_consumed`,
  `stop_row_missing` (a Stop blocked because no recorded row existed; trace `loop_stall_guard/blocked/stop_row_missing`
  or `graph_completion_guard/blocked/stop_row_missing`), `stale_stop_row`, and the history-only `legacy_text_parse`
  (final text is no longer read, so it is no longer emitted) and `legacy_log_parse` (history only: no longer emitted; absent-state grace now reads `hook_state.json` alone and a
  missing or torn file is `hook_state_unreadable`, never a log fallback). Inspect one loop with `python3 -c "import json;print(json.load(open('<progress.json>')).get('stops'))"`.
- Remediation: a high `stop_row_missing` against `stops_consumed` means agents are ending turns without running
  `graph.py stop`: fix the prompt (the block message names the exact command); there is no text parse left to tighten. An unconsumed row at the current
  revision releases the next Stop once, and only when the row's own `at` time is not before the last user prompt's transcript timestamp (an older row is
  ignored with trace `stale_stop_row`, so recording a stop early cannot excuse later undeclared turns); a row at an older revision is ignored by design. A refused `graph.py stop`
  prints the refusal on stderr (foreign session, unknown category or reason code, `complete` while the graph is
  unresolved); fix the argument, never edit `stops` by hand. Codex releases on the same `hard-stop`, `approval-gate` and `awaiting-input` rows
  (`consume-stop`, once each, no `graph.hard_stop` needed); a `complete` row is never consumed there and goes through
  `complete` / `verify-completion`. Both providers import one vocabulary file (`graph_vocab.py`).
  Limit (same-user boundary): stop rows are self-attested. Claude binds a row to its turn by timestamp, but Codex has no
  per-turn binding: a Codex agent can record a row (including `approval-gate` or `awaiting-input`) and have the next Stop
  released without a human request, and rows recorded early at an unchanged revision stay releasable until a state change bumps
  the revision. Each row is released once and is visible in `progress.stops` and the `stops_recorded`/`stops_consumed`
  counters; this is an audit boundary, not a privilege boundary.

## progress.json is older than the tools (convert, or a never-dispatched loop cannot complete)

- Symptom: completion fails with `native wave history must be an object` (state written before `wave_history`
  existed), or `graph.py convert` prints `convert_refused_<code>`.
- Query: `python3 scripts/lib/stop_counters.py [--since <ISO ts>]` counts `convert_ok`, `convert_refused_<code>`,
  `stop_row_missing` and `stale_stop_row`. Preview with `graph.py convert <state> --session <id> --check` (never writes).
- Remediation: run `graph.py convert <state> --session <id>`; it writes `progress.json.pre-convert` once and a second
  run is a no-op. Refusals are deliberate and leave the file untouched: `active_wave_ambiguous` (record or recover the
  wave first), `minor_future` (upgrade the tool), `malformed_stops` / `malformed_work_units` / `graph_not_object`
  (repair by hand), `backup_exists` (inspect and move the old backup yourself; convert never deletes).
- Limit: absent `wave_history` reads as `{}` only for a graph that never dispatched; a node holding bound
  evidence refs with no history entry still fails completion by design.

## Diff-manifest check warned or refused

- Symptom: `push.py` or `merge.py` prints `! diff_manifest <code>: <path>`, or refuses with `diff_manifest:<code>`
  (config `diff_manifest: enforce`). `scripts/diff_manifest.py --policy FILE` shows the same verdict without hooks.
- Query: `trace.by_reason` for `diff-manifest/ok/diff_manifest_ok`, `diff-manifest/warned|refused/<code>` (rows are keyed by
  `<repo>@<branch>` or `<repo>@pr-<N>`), plus `diff-manifest/failed_open/manifest_unreadable`,
  `diff-manifest/legacy/manifest_legacy_absent` (policy file without a manifest key; also written by the gate) and `diff-manifest/refused/foreign_session`. Tally them with
  `python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/manifest_counters.py`.
- Codes: `out_of_manifest`, `denied_path`, `docs_sync_deny`, `docs_sync_deletion`, `not_linked_worktree`, `special_file_type` (type change, symlink or gitlink).
- Remediation: a real violation means the diff left its declared scope; fix the diff, or widen `unit.manifest`
  (re-register with `add-unit --manifest`) or the policy file on purpose. `manifest_unreadable` means the policy file,
  progress.json or diff could not be read (fails open when advisory; refuses under enforce); fix the path. Set
  `diff_manifest: off` to disable.

## Action-authority hook denied a merge or push (or warned in advisory)

- Symptom: `gh pr merge` or `git push` to main/master is denied with "needs an action receipt (<code>)" (enforce), or a
  stderr "action_authority (advisory)" warning appears. ON by default: absent config, no config file, or no key means
  `enforce`; only an explicit valid `off` silences it, and `advisory` warns without blocking. Any invalid config is
  refused for guarded actions with `config_rejected`.
- Query: `jq -r 'select(.command=="action_authority" or .command=="action_receipt") | [.outcome,.reason_code]|@tsv' <loop dir>/<session>/trace.jsonl`,
  or `trace.receipts.by_reason_code` from `python3 scripts/measure_graph_alignment.py --root . --json` (deduped by
  event_id). Codes: `denied_<code>` / `advisory_<code>` where `<code>` is one of `no_receipt`, `hash_mismatch`,
  `repository_mismatch`, `ref_mismatch`, `sha_mismatch`, `signature_missing`, `signature_invalid`, `signer_unknown`, `trust_root_missing`, `binding_unknown` (repository+ref+sha not computable: fail closed), `state_mutated_before_guard` (a ref/HEAD/remote-moving step precedes the guarded one in the same command), `expired`, `revoked`, `consumed`, `foreign_session`, `foreign_loop`, `kind_mismatch`, `no_session` (payload had no session_id; traced under session dir `_no_session`), `malformed`;
  `receipt_consumed` (allowed); `trust_root_user_tier` (an allow that rested on the agent-writable trust root: cooperating-agent safeguard); `action_authority_failed_open` (the hook itself errored and allowed);
  `receipt_approved` / `receipt_revoked` / `receipt_refused_no_tty` (CLI); `config_rejected` (strict workflow config).
  Authority codes (also from `enforce_pr_workflow`, which denies before consuming anything): `denied_authority_denied` (the session's authority lists the category in `denied`; a receipt cannot override it),
  `denied_max_prs_exceeded` (executed merges in the session, counted from `.executed` markers of every merge receipt whatever its `authority_id`, reached `max_prs`; 0 = none; narrow/grant again with `authority.py`), `approval_requirement_missing` (a guarded action's permit verdict omitted its required approval; refused before consuming a receipt), `authority_denied_destructive_shell` (destructive gate, force-with-lease family),
  `action_authority_bad_mode` (legacy/untyped fallback; guarded hooks now reject invalid config as `config_rejected`). `scripts/merge.py` rows are `merge_py_<code>` (refused: `no_receipt`, `no_session`, `binding_unknown`, `sha_mismatch`, `consumed`, ...)
  and `merge_py_receipt_executed` (allowed). Counters: `scripts/lib/receipt_counters.py` `gate_summary(by_reason)` (the CLI below prints it as `gate`; wiring it into `measure_graph_alignment.py` itself is a handoff to the lane that owns that file).
  Owner mint command for a merge: `python3 scripts/action_receipt_cli.py approve-action --session <id> --kind merge --command 'python3 scripts/merge.py <N>' --cwd <repo dir>`;
  `gh pr merge <N>` works the same with that exact command text. `max_prs` counts every executed merge receipt in the session, including one minted before the authority was granted.
- `action_authority_failed_open`: the row carries `inputs.error_class` (sha256 of the exception class name; compare with
  `printf ZeroDivisionError | shasum -a 256`) and `loop_id` when known; the hook's stderr (hook log) prints
  `action_authority failed open: <Class>: <message>`. A session-less failure is traced under `_no_session`.
- Remediation (OWNER, at a terminal; an agent cannot): one-time `python3 scripts/authority_keys.py init` (passphrase-protected
  key; `install-root` prints the sudo commands for the real root-owned trust root; `show` prints fingerprints), then mint for the exact command:
  `python3 scripts/action_receipt_cli.py approve-action --session <id> --kind merge|git_push --command '<exact command>' --cwd <directory it runs in>`
  (single-use, 1h by default; the CLI computes repository+ref+SHA itself, signs, and refuses without a tty with
  `receipt_refused_no_tty`; `inspect-receipt` / `revoke-receipt` take `--receipt-id`). `signer_unknown` / `trust_root_missing`
  mean the signers file does not list the key that signed (or does not exist). `hash_mismatch` means args, cwd or branch differ from the minted
  command; `sha_mismatch` means HEAD (push source) or the PR head moved since minting: re-mint. `git push origin feature:main` binds
  the sha of `feature`, not HEAD. `foreign_session` means the receipt was minted for a different `session_id`: subagents share their parent's `session_id`, so mint under the session the hook reports. Or set `action_authority: off` in `.coderails/workflow.config.yaml`.
- Scope of one receipt: each guarded segment of a chained command (`a && b`) needs its own receipt; a leading
  `cd <dir>` moves the directory the hash binds (mint with `--cwd` set to where the command really runs). The binding comes from
  `scripts/lib/action_binding.py` (push: refspec source sha and destination ref; merge: live PR head via `gh pr view`, 4s timeout);
  unknowable means `binding_unknown`, fail closed. Bindable forms only: `git [-C dir] push <remote> <ref>` (no env prefix,
  `-c`, `--git-dir`; bare `git push` is `binding_unknown`; `HEAD` alone means the current branch; the repository is the push url) and
  `gh pr merge <n> --match-head-commit <live head sha>` (or `gh api .../merge -f sha=<sha>`; `scripts/merge.py` pins the sha its gates
  verified). Run ref-moving steps (`commit`, `branch -f`, `reset`, `config`, ...) as separate commands before the guarded one.
- Counters: `python3 scripts/measure_graph_alignment.py --root . | python3 scripts/lib/receipt_counters.py` prints `receipts`,
  `trust` (signature, trust-root, binding and `state_mutated_before_guard` counts) and `gate` (`authority_denied`, `approval_requirement_missing`, `max_prs_exceeded`, `action_authority_bad_mode`, `authority_denied_destructive_shell`, `no_receipt`, `merge_py_receipt_executed`; see "Gate counters" in docs/graph-alignment-measurement.md). Measurement: one hook run is well under 1 s
  with one receipt (single run, not a benchmark; 50 receipts could approach the 10 s hook timeout).
- Residuals (docs/decisions/p3-human-only-minting.md): `.consumed`/`.revoked` markers are agent-writable files, so unlinking one
  replays or un-revokes a receipt until it expires; junk files can crowd the 50-receipt cap (deny, not allow); the hook fails open on
  its own exceptions. A same-user agent can also write a deeply nested file (`[` x 7000) into `authority.json` or `receipts/`: it is read
  as malformed (`RecursionError` is caught in `read_receipt`/`read_authority`), so it denies rather than crashing the hook open; it is the
  same same-user class as the markers above.
- Unmatched merge routes (Limits): `gh api` merge forms are matched with the endpoint anywhere in argv and the GraphQL
  `mergePullRequest`/`enablePullRequestAutoMerge` mutations (unbindable, so always denied); other routes (the web UI, `git merge` into main via
  a script, a tool that calls the API directly) are not seen by any command hook.
- Codex: the hook imports the byte-identical mirrored libs and the package ships `scripts/action_receipt_cli.py` and
  `scripts/authority_keys.py` (same owner-run rules).
- Limits: the trust root has two tiers. The root tier (`/Library/Application Support/Coderails/receipt_signers`, uid 0, not group/other
  writable, owner-installed with sudo, not installed by this repo) is the real boundary; the user tier (`~/.coderails/keys/receipt_signers`)
  is agent-writable, so it is a cooperating-agent safeguard. An agent with Accessibility or control of the owner's terminal is out of scope
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

See [graph specification recovery](RUNBOOK-GRAPH-SPEC.md).

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
  `dispatch_state_unconverted` (`state_minor` < 2: run `graph.py convert --check` then `convert`; it refuses while a wave
  is open, `convert_refused_active_wave_in_flight`, so finish or `recover-wave` first), `dispatch_unauthorized` (Claude
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
  `spawn_agent` function-call message with its v2 record, role and consumed authorization; a task-name-only legacy event
  cannot bind a contract-era wave. Claude matches a non-null hook `tool_use_id` to the native Agent call; when the hook
  supplies no id, it retains the consumed flag and one-spawn-per-id check without claiming call-id proof. Historical
  pre-contract attempts retain their original evidence rules. Claude hooks can still fail open if the hook times out
  (10 s in `hooks.json`) before it denies.
