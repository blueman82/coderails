# Hook diagnostics

[Runbook](RUNBOOK.md).

## No trace rows appear

- Symptom: `trace.rows` is 0 and `gate_blocks` has nonzero counts.

- Query: Run the [log counter command](RUNBOOK.md). Then run `ls ${CLAUDE_AGENTIC_LOOP_DIR:-~/.coderails/agentic-loop}/<session_id>/trace.jsonl`.

- Remediation: Check the directory and session ID. The writer silently drops rows if it cannot write to the directory. It also drops rows if the session ID is empty or contains `/` or `..`.
  Correct the directory permissions. The gate must continue to work if it cannot write a log entry.

## Gate seems off (config key or wiki schema)

- Symptom: A configured gate for wiki taxonomy, wiki debt, integrity, or eval signing does nothing. The reader may ignore a config key.

- Query: Run `python3 scripts/lib/config.py resolve-config --json | jq .unknown_keys` and also read `.findings`.
  Run `python3 scripts/lib/config_counters.py` for `config_unknown_key`, `config_bad_type`, `config_bad_value`, `config_unreadable`, `wiki_schema_missing`, `wiki_schema_invalid`, and `wiki_schema_legacy`.
  Use `--since 2026-10-05T00:00:00` to limit the count by date.
  The same entries appear in `trace.by_reason` from `measure_graph_alignment.py --json`.
  The keys are `config/warned/<code>` and `wiki_taxonomy_gate/failed_closed/<code>`.

- Remediation: Correct the key or its value. The result can suggest a key name.
  The `resolve-config --json` command gives `valid:false` and exits 1 if there is an error.
  Ordinary gates warn and log. The operations in the next section fail closed.
  The code `wiki_schema_legacy` identifies a previous vault record. Put back `wiki.schema.json` before you write in a known vault.

## Guarded action denied: config_rejected or wiki schema fail-closed

- Symptom: A command or write gives `config_rejected` ("did you mean ..."), `wiki_schema_missing`, or `wiki_schema_invalid`.
  The affected commands are `gh pr merge` and `git push` to `main` for the authority hook, and `push.py` or `merge.py` for diff-manifest.
  The gate also checks writes in the wiki vault.

- Query: Look for `action_authority/denied/config_rejected`, `diff-manifest/refused/config_rejected`, or `wiki_taxonomy_gate/failed_closed/<config_rejected|wiki_schema_missing|wiki_schema_invalid>`.
  Run `python3 scripts/lib/config_counters.py` for `config_rejected`, `config_bad_value`, and `wiki_schema_fail_closed`.

- Remediation: Run `python3 scripts/lib/config.py resolve-config --json`. Correct each key typo, incorrect type, or value that the enum does not include.
  Put back `wiki.schema.json` with a nonempty `page_types` list of directory names. Only the checked operation stops. Other commands and tools can continue.

  Gates that need a config file do not run without one. The diff-manifest check continues to use its default policy.
  An ambiguous wiki identity does not block a write. This can mean no `wiki_path`, a different repository, or a path that is not a vault.

- Limits: An agent with the same user ID can remove the config file or set a control to `off`. No hook guards `.coderails/workflow.config.yaml`.
  Removal does not disable the default diff-manifest check. Examine config diffs as you examine code.
  The diff-manifest policy can list the config file as a protected path.

  Only an explicit `false` turns off `evals.require_signatures`. Malformed lines and duplicate keys give `config_unparseable_line` or `config_duplicate_key`.

- Defaults: The diff-manifest check uses `enforce` mode and `policy/diff-policy.default.json` with or without a config file.
  A config with no other keys sets `sandbox_workers: true` and `evals.require_signatures: true`.
  The `action_authority` setting defaults to `enforce` with or without a config file. Example and init settings also use `enforce`.

  The explicit `advisory` setting warns about missing receipts. The explicit `off` setting disables the receipt gate.
  An incorrect config causes the gate to refuse operations it checks. Keep intentional project settings when you migrate.

## Discipline lint advisories climbing

- Symptom: The `confidence_labels` or `verify_loop` advisory count increases.
  A user override made the two hooks advisory. See `docs/decisions/2026-10-04-not-in-gate-demotion.md`. The earlier `blocked` series is historical.

- Query: Read `trace.by_reason` for `check_confidence_labels/demoted/confidence_label_missing` and `check_verify_loop/demoted/verify_loop_missing`.
  The tally key is `command/outcome/reason_code`. The `blocked` and `warned` entries come from the previous series.
  Read `demoted` or `would_block` in `gate_blocks.claude.gates.<gate>`.
  The `blocked / decisions` ratio falls to about 0 after demotion. Compare `demoted / decisions`.

- Remediation: An increase in `demoted` means the model skips labels or DNV tags. Correct the prompt or instructions.

## Reviewer/scout Bash command denied

- Symptom: A read-only reviewer or scout reports a denied Bash call.

- Query: Look in `trace.by_reason` for `reviewer_bash_allowlist/denied/bash_allowlist_deny_<cause>`.
  The causes are `meta` for chaining or redirection and `flag` for a dangerous or unknown rg flag. The cause `parse` marks incorrect quoting. The cause `argv` marks a command off the list.
  The discipline log line has `agent_type`, `argv0`, and a 12-char SHA of the command.

- Remediation: Run the inspection again with one allowlisted read-only command, without chaining, redirection, or interpreters.
  If the allowlist does not include a permitted command, add its full argv prefix with a test.

## Subagent Bash denied for absent agent_type

- Symptom: The hook denies a subagent's Bash call with `bash_agent_type_absent`.

- Query: Read `trace.by_reason` for `subagent_identity_gate/denied/bash_agent_type_absent`.
  The discipline log line `hook=subagent_identity_gate` names the session. For counts, run `python3 scripts/measure_graph_alignment.py --root . --json`.

- Remediation: Use the role's `subagent_type`, for example `coderails:design-scout`, so the payload has `agent_type`.
  The roles that the hook checks use their MCP tools and have no Bash.
  The check applies only to `agent_id` without `agent_type` in a graph-bound session. Codex has no `agent_type` at PreToolUse.

## Guarded role has no tools or no shell

- Symptom: A reviewer or scout cannot run a command or read a file, or a skill step is UNSUPPORTED.

- Cause: The six roles use only `mcp__plugin_coderails_cap-<role>__*` tools. The `preflight-scout` also has `Skill`.
  If the tools are unavailable, `.claude-plugin/plugin.json` may have no `mcpServers`, or `capabilities/mcp.json` may be out of date.
  Run `python3 scripts/capability_profiles_validate.py --check` and use `--write-mcp` to build the MCP config again.

- For Codex, launch the role with `scripts/codex_role_session.py`. A native Codex child of a role that the hook checks has no shell or role tools.
  The launcher refuses a cwd in a project `.codex/` directory. Move the audit to a different directory or remove that project directory.
  The `subagent_identity_gate: off` setting disables the identity gate. The default is ON.

## Capability tool refused or denied

- Symptom: The hook refuses a `scripts/capability.py` call for a reviewer or scout. This usually occurs for `source-auditor` with `tests.run`.

- Query: Read `trace.by_reason` for `reviewer_bash_allowlist/denied/capability_denied_<tool>`, `capability_unknown_tool`, or `capability_bad_argv`.
  The hook writes one row for each decision. Its `reviewer_bash_allowlist/allowed/capability_allowed_<tool>` entries count grants.
  The script writes `capability/refused/capability_*` with `args_invalid`, `path_denied`, `bad_ref`, `no_repo`, `tests_unknown_name`, `sandbox_unavailable`, or `io_error`.
  Read matching entries with `python3 scripts/measure_graph_alignment.py --root . --json | jq '.trace.by_reason | with_entries(select(.key|test("capability")))'`.

  Hook entries use the payload `session_id`. Script entries use `CLAUDE_SESSION_ID` or `CODEX_THREAD_ID` (unverified that the harness sets it).
  Without an ID, the script uses the `unattributed` session directory.
  The value `"traced": false` means only that the log library or disk gave an error.
  The hook also logs `denied=1 reason_code=...`. An empty query cannot prove there were no refusals.

- Remediation: The `capability_denied_*` code means the agent's tool settings do not grant the tool.
  Change `capabilities/profiles.json` deliberately. The validator checks frontmatter and Codex sandboxes against it. Keep the Bash allowlist as it is.
  The `bad_argv` code means the call differs from `<abs path>/scripts/capability.py <tool> --json-args '<json>'`. The path must be absolute.
  The `tests_unknown_name` code means the name is not in `profiles.json` in the `tests` section.

## Capability MCP server refused a call or will not start

- Symptom: The role's `capability_mcp.py` exits 2 at launch, or `tools/call` gives an error or `isError`.

- Query: Run `python3 scripts/lib/capability_counters.py` to count codes across `CLAUDE_AGENTIC_LOOP_DIR`.
  In `trace.by_reason`, `capability/refused/capability_mcp_refused` marks startup refusal and `capability_wrong_role` marks a tool denied for the role.
  The `capability_args_invalid|path_denied|bad_ref` codes mark argument errors. The `capability/ok/<tool>` entries count grants.

  Entries hash `{tool, role, via: mcp}`. MCP servers try `CLAUDE_SESSION_ID`, `CLAUDE_CODE_SESSION_ID`, and `CODEX_THREAD_ID` in that sequence.
  With no ID, they use the `unattributed` directory.

- Remediation: Check `--role`, its tools in `capabilities/profiles.json`, and the flags. A problem in one of these gives `capability_mcp_refused`.
  Read stderr for the cause. The `capability_wrong_role` code means the role settings do not grant that tool.
  Change those settings deliberately. The validator checks that the agent files agree.

  The `path_denied` code for a `worktree` argument means the path is not in `git worktree list` for the server's cwd repo.
  The `cmd.run` tool runs only `named_commands` entries.

## Authority object refused or changed

- Symptom: The `authority.py` command refuses an operation or an object disappears.

- Query: Read `trace.by_reason` for `authority/created|narrowed|revoked` and `authority/refused/authority_refused_<cause>`.
  Grant and scope causes include `exists`, `widen_scope`, `widen_max_prs`, `narrow_empty`, and `not_revocable`. Other causes are `missing`, `expired`, `malformed`, `invalid`, `create_invalid`, `write_failed`, and `foreign`.
  A session ID that fails the safety check produces stderr only.

- Remediation: Run `python3 scripts/authority.py inspect --session <exact id>`.
  A refusal for a different session means the ID differs. The tool does not rewrite IDs.

## Manifest says no loop, or the wrong loop

- Symptom: The SessionStart manifest shows `loop: none` or `loop: unknown` while a loop is active, or the session adds the static fallback.

- Query: Run `python3 scripts/measure_graph_alignment.py --root . --json | python3 -c "import sys,json;print(json.load(sys.stdin)['context'])"`.
  Or run `jq 'select(.command|startswith("context_"))|.reason_code' ${CLAUDE_AGENTIC_LOOP_DIR:-~/.coderails/agentic-loop}/<session_id>/trace.jsonl`.

  The codes are `manifest_ok`, `manifest_graph_invalid`, `manifest_no_session`, `manifest_state_unreadable`, `manifest_payload_malformed`, `manifest_error`, `route_match`, `route_payload_malformed`, and `route_none`.
  The `route_none` outcome writes no entry. If the session ID is unavailable or fails the safety check, the writer uses `<loop dir>/_unattributed/trace.jsonl`.

- Remediation: The `loop: none` result is correct if the session ID differs or fails the safety check. The lookup uses IDs without changes.
  For `manifest_state_unreadable`, repair `progress.json`. For `manifest_graph_invalid`, run `graph.py inspect <state>`.
  Check `CLAUDE_AGENTIC_LOOP_DIR` first, then `CODERAILS_AGENTIC_LOOP_DIR`.

  Routing lines are advisory. The `route_meta` counters give mandatory, offered, recorded, and dropped skill selections in the four-skill budget.
  The counts do not prove that the agent read or used a skill. The active graph contract supplies mandatory skill selections before keyword matches.

## Autonomous input denial is wrong

- Symptom: The gate denies `AskUserQuestion` or `request_user_input` after the user asks to stop autonomy.
  It can accept the tool after "autonomous". That word grants nothing. Use the installed `authorise` command or skill.

- Query: Read `trace.by_reason` for `authority/granted/authority_granted_command` for the typed grant.
  The `autonomous/ignored/authority_phrase_ignored` entry means the hook showed the grant command and ignored the phrase.
  Check `autonomous/blocked/authority_deny` and `autonomous/allowed/authority_expired_allow`.

  The `autonomous/ignored/authority_corrupt_ignored` entry means the hook cannot read `authority.json`. It grants nothing.
  The `authority/refused/authority_refused_write_failed` entry means the grant could not write, so the hook does not suppress a question.
  The `authority/refused/authority_refused_foreign` entry marks a different session.
  Run `python3 scripts/authority.py inspect --session <exact id>`.

- Remediation: Revoke with `python3 scripts/authority.py revoke --session <id>`.
  Previous `crack_on_active` files stay on disk and have no effect.
  The word "autonomous" only shows the grant command (`authority_phrase_ignored`).
  To grant with fixed defaults and `max_prs` 0, type `/coderails:authorise` or use `$coderails-codex:authorise` in Codex.

  The `authority_expired_allow` entry means the 24h object expired. Grant again.
  The command can replace an expired or incorrect object. It refuses a live object with `authority_refused_exists`.

  The `authority_refused_unsafe_session` entry can mean that `/coderails:authorise` got an empty session ID or a literal `${...}`.
  No live probe checked the substitution in the command file. See `docs/decisions/e3-authority-object.md`.
  Check the session ID, then try the command again.

  An object without `granted_by: command` grants nothing.
  An agent with file access can write the unsigned `granted_by: command` label directly. The hint tells agents that only the user can grant authority.

- Baseline: The earlier 103 calls and 5 blocks in `docs/graph-alignment-measurement.md` come from the discipline log.
  The subsequent counts come from the diagnostic log, so the two sets are not comparable.
  Run `python3 scripts/measure_graph_alignment.py --root . --json`.
