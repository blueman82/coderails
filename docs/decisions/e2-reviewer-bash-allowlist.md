# E2: reviewer and scout Bash allowlist

Hook: `hooks/scripts/reviewer_bash_allowlist.py` (PreToolUse, `Bash`).
It is last in the Bash group, after `destructive_bash_gate`, `enforce_pr_workflow`, `test_gate`, and `verification_volume_ceiling`.
The sequence stays the same.

## Which agents

These Claude agents keep `Bash` and are read-only by contract: `deploy-safety-reviewer`, `design-scout`, `disposition-scout`, `preflight-scout`, and `source-auditor`.
Their `agents/*.md` files use `tools: Read, Grep, Glob, Bash` with `disallowedTools: Write, Edit, NotebookEdit`.
The `spec-reviewer` has no Bash. The `docs-auditor`, `loop-worker`, `wiki-writer`, and `proof-author` can write and are not subject to this hook.

## What is and is not enforced

The hook uses `agent_type` from the payload to identify agents on its list. It accepts only one Bash command.
The allowed argv prefixes are `ls`, `cat`, `head`, `tail`, `wc`, `grep`, `rg`, and `sha256sum`. The list also includes `git status|log|diff|show|blame` and `gh pr view|list ... --json`.

It refuses `;` `|` `&`, backtick, `$(`, `>`, `<`, newlines, and `git -c`.
It refuses commands not on the list. Examples are `find -exec/-delete`, `sed -i`, and `python`/`python3`/`node`/`bash -c`.
It also refuses `--output`, `--pre`, `--pre-glob`, `--ext-diff`, `--textconv`, and `--hostname-bin`.
For `rg`, the hook uses an allowlist of flags because the command has flags that can change its behavior. It refuses unknown long flags and `-z`.

The hook removes the plugin namespace before it checks `agent_type`, for example `coderails:design-scout`.
Use of the namespaced value is inferred. No live payload showed it.
Each refusal writes a log line and a diagnostic log entry with `reason_code=bash_allowlist_deny_{meta,flag,parse,argv}`.

The hook does nothing if it has no known `agent_type`, the tool is not Bash, or the payload is malformed.
Top-level calls have no `agent_type`. See AGENTS.md and the `agent_only_gate` probe on Claude Code 2.1.220.
Thus the hook does not limit the orchestrator.

- The `docs-auditor` has Bash plus Edit/Task and can write. The hook also skips Bash for agents it does not list.

- An allowlisted `git`, `grep`, `rg`, or `cat` can read secrets in files that Bash can read.
  The hook limits writes and command execution. It accepts `$VAR` expansion.

- The frontmatter `disallowedTools` setting blocks `Write` and `Edit`. This hook limits Bash.

- The live probe used a plain session. It did not check `claude --agent <name>`.

- Claude frontmatter has no command-level Bash control (inferred: none found). A hook can apply this control.

- The `source-auditor` instructions say "run the thing" to calculate numbers again, for example from a test suite or coverage script.
  The hook blocks test runs for agents on its list. An interpreter can write files, so the decision to change the list belongs to a human.

- **Codex** keeps `sandbox_mode = "read-only"` on `deploy-safety-reviewer`, `design-scout`, `disposition-scout`, `preflight-scout`, `source-auditor`, and `spec-reviewer`.
  See `grep sandbox_mode packages/codex/agents/*.toml`. No per-command setting was found (inferred).
  The shell read limit is in the instructions only. The Codex TOML files stay unchanged.

## Addendum: capability tools close the "Known cost" without widening Bash

The `source-auditor` has the `tests.run` tool in `capabilities/profiles.json`.
It uses `<abs>/scripts/capability.py tests.run --json-args '{"name":"<declared>"}'`.
The hook accepts this command only with the specified absolute path and if the caller's configuration grants the tool.
If the configuration denies it, the hook gives `capability_denied_<tool>`. The hook skips an `agent_type` with no entry in the config.
It continues to refuse `python3 -c`, `bash -c`, and `python3 <script>`.

The test is `hooks/scripts/tests/capability_hook_test.py::test_e2_known_cost_closed_without_widening_bash`.

The `tests.run` tool executes repo code with declared argv lists, a timeout, and a filtered environment.
A declared suite can write caches in the repo. The tool checks a typed argument schema and the path in Bash argv.
A harness-level typed tool would use an MCP server, which this addendum does not supply.

Codex has no Bash hook for individual agents. It ships the same script in `packages/codex/scripts`.
The Codex controls for each agent are `sandbox_mode` and instruction text. A read-only sandbox may block suite cache writes (inferred).
See `docs/CAPABILITIES.md`.

## Addendum: Bash removed from the guarded agents; this hook is defence in depth

The five Claude agents on the list no longer have `Bash` in `tools:`. The files list only the MCP tools for each role.
The tool name is `mcp__plugin_coderails_cap-<role>__<tool>`. The `preflight-scout` also has `Skill`.
Decision D4 also removed native `Read`, `Grep`, and `Glob`.

A measurement used the actual CLI with a loopback API fixture. See `hooks/scripts/tests/reviewer_tools_probe_test.py`.
The `tools` array that the CLI sends does not list Bash, Write, Edit, NotebookEdit, Agent, or Read.
The agents use `tests_run` or `cmd_run` for these operations. They do not use Bash argv.

The hook stays registered and continues to check an installation if the agent file lists Bash.
This can occur with a previous copy of the file or if someone adds the tool again.
In a graph-bound session, `subagent_identity_gate.py` catches a payload with an `agent_id` and no `agent_type`.

Each Codex role on the list uses `[features] shell_tool = false` in TOML and uses `scripts/codex_role_session.py`.
Codex has no Bash hook for this check because its PreToolUse payload has no `agent_type`.
See the Role binding section of `docs/CAPABILITIES.md`.
