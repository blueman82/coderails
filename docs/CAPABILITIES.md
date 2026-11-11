# Capability profiles

The `capabilities/profiles.json` file lists tools for each agent type.
The `scripts/capability_profiles_validate.py` validator fails if the file disagrees with `agents/*.md` frontmatter or `packages/codex/agents/*.toml`.
The `scripts/tests/capability_profiles_test.py` test runs the validator.

The `security-reviewer` role holds only `repo.inspect` and `diff.read`.
The Codex role launcher and the MCP server for each provider refuse to start the role if its settings grant more tools.
These checks use the installed source.

The available tools include `repo.inspect`, `diff.read`, `tests.run`, and `pr.comment` through `scripts/capability.py <tool>`.
The `worktree.write` setting uses Write and Edit or a writable Codex sandbox. The `shell.raw` setting gives raw Bash.
An agent with a declared tool and no `shell.raw` is "guarded". The Bash allowlist hook reads this file to find those agents.

## What each harness can enforce

| Property | Claude Code | Codex |
|---|---|---|
| No Write or Edit | The harness applies frontmatter `tools` and `disallowedTools`. | The sandbox applies `sandbox_mode = "read-only"`. |
| Shell control | Six agent files have no `Bash`. An earlier live probe tested five roles. The installed `security-reviewer` needs a probe. The `reviewer_bash_allowlist.py` hook covers installations with Bash in an agent file. The `subagent_identity_gate.py` hook denies Bash without `agent_type` in a graph-bound session. | Each controlled role TOML has `[features] shell_tool = false` and `sandbox_mode = "read-only"`. The sandbox mode alone does not control a child. Codex PreToolUse has no `agent_type` or `agent_id`, so it has no identity gate or Bash hook for individual agents. |
| Typed MCP tools | The `tools:` list contains only `mcp__plugin_coderails_cap-<role>__<tool>`. The `preflight-scout` role also has `Skill`. The `mcpServers` key in `.claude-plugin/plugin.json` points to `capabilities/mcp.json`. | The `scripts/codex_role_session.py` script starts a `codex exec` session with only that role's server. Native children inherit the parent's servers. The Codex plugin manifest declares no server for an individual role. |
| `tests.run` | Only `source-auditor` can use it. It runs declared argv lists with limits and can write files. | It uses the same script. The read-only sandbox can block its cache writes (inferred). |

Claude agents with these controls use typed MCP tools and have no Bash. See Role binding below.
The Bash-path hook also checks installations with Bash in an agent file.
It refuses interpreters such as `python`, `node`, and `bash -c` for these agents. Use a declared name in the `tests` section of `profiles.json`.

The hook accepts a call only if the role settings grant its tool.
Its refusal codes are `capability_denied_<tool>`, `capability_unknown_tool`, and `capability_bad_argv`.
It skips an `agent_type` without an entry in `profiles.json`, for example `general-purpose`.

Give the agent the absolute script path. The hook does not expand `$CLAUDE_PLUGIN_ROOT`.
If the hook cannot find or parse `profiles.json`, the hook uses its hardcoded set. The allowlist stays on and rejects these tool calls as ordinary Bash.

The `tests.run` tool executes repo code at the user's privilege level.
On macOS, `sandbox-exec` blocks network access. It limits writes to the repo, a temporary HOME, and tmp.
It blocks reads of the user's `.ssh`, `.config/gh`, `.aws`, and `.gnupg`.
On other systems it refuses with `capability_sandbox_unavailable` unless `CAPABILITY_TESTS_UNSANDBOXED=1`, which runs without containment.
A temporary `$HOME` alone cannot protect secrets because Python and ssh can get the actual home directory from the passwd entry.

The validator refuses an agent file without an inline `tools:` line because the harness then grants all tools.
It refuses an agent with these controls if its tools differ from the derived MCP names. The only added tool is `Skill` for `preflight-scout`.
A source-auditor call as `general-purpose` has full Bash and these rules do not apply to it.
Use `subagent_type: source-auditor` for the tighter allowlist.

## Per-role MCP server

The command `scripts/capability_mcp.py --role <agent>` starts a stdio MCP server.
Its newline-delimited JSON-RPC methods are `initialize`, `notifications/initialized`, `ping`, `tools/list`, and `tools/call`.
It offers only the tools the role gets in `capabilities/profiles.json` and uses `scripts/capability.py` without starting a child.

The server calculates `tools/list` from the file at launch. A change to the file changes that list at the next launch.
The `scripts/capability_profiles_validate.py` validator continues to flag differences in frontmatter and Codex files.
The Codex package has the same bytes for `capability.py`, `capability_mcp.py`, `lib/capability_extra.py`, and `profiles.json`.
The `packages/tests/test_codex_capability_parity.py` test checks them.

- **Tool names.** MCP names cannot have dots. The names `repo.inspect`, `diff.read`, `tests.run`, `pr.comment`, and `cmd.run` use underscores in MCP.
  The MCP names are `repo_inspect`, `diff_read`, `tests_run`, `pr_comment`, and `cmd_run`.

  The roles `deploy-safety-reviewer`, `design-scout`, `disposition-scout`, `preflight-scout`, and `security-reviewer` get `repo_inspect` and `diff_read`.
  The `source-auditor` also gets `tests_run` and `cmd_run`. The two read tools set `readOnlyHint: true`.
  The execution tools set `readOnlyHint: false` and can run repo code.

- **Role selection.** The launcher sets the role. The `inputSchema` has no `role` property.
  The `capability.check` function refuses unknown keys, so a `role` argument gives `capability_args_invalid`.

  The server exits 2 with stderr if the role has no entry or no tool in `profiles.json`, or a flag is unknown.
  It tries to log `capability_mcp_refused`.
  A `tools/call` for a tool that the role does not have gives a JSON-RPC error and tries to log `capability_wrong_role`.
  It does not run the tool.

- **cwd and `worktree`.** The server uses the session's cwd. It does not automatically use a subagent's worktree.
  Each repo tool accepts an optional `worktree` if that path is in `git worktree list` for the server's repo.
  Other paths give `capability_path_denied`.

- **More `repo.inspect` operations.** These use `safe_path` or `REF`: `show` (`spec` = `<ref>:<path>`), `blame`, `wc`, and `sha256`.
  They also include `glob` with a `git ls-files` pathspec for tracked files only, and `offset` on `read`.

- **`cmd.run`.** Only `source-auditor` gets this tool. It runs one entry from `named_commands` in `profiles.json`.
  The names are `git-rev-count {ref}`, `file-lines {path}`, and `file-sha256 {path}`.
  The argv templates use typed placeholders `repo_path` and `ref` with specified argument keys. Substitution replaces a full token and uses no shell.

  The tool runs through `capability.sandboxed()` like `tests.run`. It has no network, limits writes, and uses a filtered environment.
  An unknown name, missing key, or key not in the schema gives `capability_args_invalid`.
  The value `..` or an absolute path gives `capability_path_denied`. An incorrect ref gives `capability_bad_ref`.

- **Diagnostic log.** Each call and refusal tries to append a `capability` entry with hashes of `{tool, role, via: mcp}`.
  An unavailable log library or write error gives no entry. A response for a known tool sets `traced: false` in that condition.
  Startup and role errors have no `traced` field.
  Run `python3 scripts/lib/capability_counters.py [--since <ISO ts>]`. It reads `CLAUDE_AGENTIC_LOOP_DIR` and counts only written entries.

- **Cost.** At session start, the installed plugin launches one Python server for each role. This is six servers in a session.

The `cmd.run` and `pr.comment` tools offer no network command. Reviewers use `diff.read` and PR metadata from the dispatcher.
The server does not offer `gh pr view`. Containment for `tests.run` and `cmd.run` uses `sandbox-exec`.
If it is unavailable, the usual refusal is `capability_sandbox_unavailable`. See the opt-out for tests above.

The server cannot stop an agent that has a raw shell from bypassing it. Removing Bash applies that control.
Policy files are agent-writable because the agent has the same user ID. The files are a cooperating-agent safeguard.

The `cmd.run` and `tests.run` tools read `capabilities/profiles.json` on each call.
The sandbox for `tests.run` can write the repo. Repo code can thus edit the command table during the session.
The server sets `tools/list` at launch, but it reads the command tables again.

The `worktree` argument accepts each path from `git worktree list` in the same repo.
A role can read a different agent's worktree. With `tests.run` or `cmd.run`, it can also run code there.

## Role binding: tools, generated config, identity gate, Codex role sessions

### Claude

The `.claude-plugin/plugin.json` file declares `"mcpServers": "./capabilities/mcp.json"`.
Run `python3 scripts/capability_profiles_validate.py --write-mcp` to build the config from `profiles.json`.
It adds one `cap-<role>` server for each role with controls. The command is `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/capability_mcp.py --role <role>`.
The default `--check` fails if the file has edits or if there is no role server or if a server has no matching entry.

The role's frontmatter `tools:` uses the derived `mcp__plugin_coderails_cap-<role>__<tool>` names.
The `preflight-scout` role also gets `Skill`. The `disallowedTools` setting stays.

The validator refuses `Bash`, `Write`, `Edit`, `NotebookEdit`, and `Agent` for these roles. It also refuses `Task`, `WebFetch`, `Read`, `Grep`, and `Glob`.
It also refuses a stale or unlisted MCP name, or a full tool name above the API limit of 64 characters.
The longest name, `cap-deploy-safety-reviewer`, has 62.

### Claude tool probe

The `hooks/scripts/tests/reviewer_tools_probe_test.py` test runs the actual `claude` CLI against a loopback API fixture with no billing.
It uses `--agent coderails:<role>` and an Agent-tool call with `subagent_type`.
For the five installed roles it tested, the model's `tools` array had only the derived names. It had none of Bash, Write, Edit, NotebookEdit, Agent, or Read.

Source has a sixth role, `security-reviewer`. No installed probe has tested its tool list.
The `design-scout` list has none of the `source-auditor` server tools.
The live servers refuse `tests_run` for `design-scout` and refuse a `cmd_run` name with no entry in `profiles.json`.
A control agent with Bash shows Bash in the same array, so the test can find a difference.

### Decision D4

A role with these controls uses MCP tools only, without native Read, Grep, or Glob.
The `repo_inspect` tool gives `read` with `offset`. It also gives `list`, `grep`, `glob`, `status`, `log`, `show`, `blame`, `wc`, and `sha256`.
If the reviewer cannot work, the native read tools can be put back because they are not a shell.
Change `EXTRA_TOOLS` or `FORBIDDEN_TOOLS` in `scripts/lib/capability_validation.py` and the agent files.

The `preflight-scout` skills can use shell commands, for example wiki-query.
With no Bash, the agent instructions say to report that step as UNSUPPORTED. The role gets no shell.
Measure the frequency with `capability/refused` and agent reports before adding tools.

### Identity gate

The `hooks/scripts/subagent_identity_gate.py` hook runs immediately after `reviewer_bash_allowlist`.
It denies Bash in a graph-bound session if the payload has `agent_id` and has no `agent_type` value.
The code is `bash_agent_type_absent`. This is its own Claude hook. The change does not edit `loop_dispatch_guard.py`.

The hook relies on the harness to give `agent_id`. It skips sessions with no `progress.json`.
It also skips a missing or `?` session ID, an unreadable `progress.json`, or one with no `graph`.
It skips calls without `agent_id` or to a tool other than Bash. Its denial applies only to the condition above.

The check accepts a payload with `agent_type`. This includes `general-purpose`, which keeps Bash.
Use `subagent_type` to select the role for dispatch. Lane A's `loop_dispatch_guard` checks that in graph work and is unchanged here.
An orchestrator without that check must follow the role instructions.

### Codex

Each role TOML has `[features]` and `shell_tool = false` after the instruction string, so the table does not contain `developer_instructions`.
It also has `sandbox_mode = "read-only"`. The validator checks the two settings.
A native child inherits the parent's permissions and MCP configuration. The sandbox mode alone cannot change that.

The command `scripts/codex_role_session.py --role <agent> --prompt-file <file> [--cwd <dir>]` uses a copy with the same bytes in the Codex package.
It launches `codex exec --ignore-user-config -s read-only -c features.shell_tool=false -c features.multi_agent=false -c mcp_servers.cap-<role>=... -`.
It sets up only that role's server and reads the file through stdin.
The environment allowlist is PATH, HOME, CODEX_HOME, LANG, LC_ALL, TERM, and TMPDIR. It sends no tokens.

The launcher loads `developer_instructions` from the tracked role TOML.
The Codex cite-check, merge, workflow, post-review, workflow-audit, and docs-sync skills use it with a worktree at the specified head.
For `source-auditor`, it sets `approval_mode="approve"` on that server's `cmd_run` and `tests_run` only.
The settings let those two sandboxed tools run with Codex `approval=never`. Other tools and roles get no approval from this setting.

The [Codex configuration guide](https://learn.chatgpt.com/docs/config-file/config-reference) gives the settings for a server and its tools.
The MCP server checks the role, arguments, named command or test, and execution sandbox.
Repo code can edit files that the same user owns. This is a cooperating-agent safeguard.

Use the launcher for `source-auditor` so native children do not inherit `tests_run` and `cmd_run`.
The launcher refuses a role without an entry that has the required controls.
The Codex manifest declares no `mcpServers`, which native children would inherit. This work could not test that manifest behavior offline.
A native child of a role with controls has no shell or role tools and must report file or history checks as UNSUPPORTED.
Use the role session for those checks.

The change does not edit `scripts/installer/codex.py`. The launcher is the only Codex path to the typed tools.
The plan's installer-managed read-only reviewer `mcp_servers` block would pass tools to native children, so the installer does not add it.
The role TOML `[features]` block is a config claim without a live native child test.

The installer and agent flow make launcher use optional.
An orchestrator can start a native Codex child or plain `codex exec`. Codex PreToolUse has no `agent_type` for a hook check.
The plan accepts "separate contained sessions where a sandbox/MCP boundary is required". The installer adds no per-role `mcpServers` block.

The `--ignore-user-config` option skips only `$CODEX_HOME/config.toml`.
Codex also reads project `.codex/` from the cwd to the repo root. The launcher refuses a `--cwd` or working directory with `.codex` in that tree.
The resolved config then has one `mcp_servers` entry. The live test checks the tools array at the repo cwd only.
Project `AGENTS.md` gives instructions without granting tools.

The `subagent_identity_gate` defaults to ON. Set `subagent_identity_gate: off` in `.coderails/workflow.config.yaml` to disable it.
All other values keep it on. The `subagent_identity_gate/denied/bash_agent_type_absent` entry records a denial.

The `preflight-scout` keeps `Skill`. Skills such as `engineering-principles-*` have `allowed-tools` with Bash, Write, and Edit.
It is UNVERIFIED if a skill can grant a tool the subagent does not list. No probe lists tools after a Skill call.
If a skill can grant them, the remaining controls are `reviewer_bash_allowlist` for a known `agent_type` and `subagent_identity_gate`.
The initial probe is the only observation for "no shell for preflight-scout".

### Codex observation

The `scripts/tests/codex_role_session_live_test.py` test runs the actual `codex exec` with the launcher argv.
A loopback Responses fixture replies with `exec_command`.
The `tools` array has no `exec_command` or `write_stdin`, and the call gives `unsupported call: exec_command`.
The array has only the named role's server tools.

The test covered five roles with controls. Source has six. Check the installed `security-reviewer` list in a new run.
Without `features.multi_agent=false`, the control run offers `spawn_agent`.
Without `features.shell_tool=false`, the control run offers the shell and runs the command.

These tests check the launcher's argv. They do not spawn a native child to check the TOML `[features]` block.

One OAuth check ran the launcher with `approval=never` and a read-only Codex sandbox.
The `design-scout` completed `repo_inspect`. The `source-auditor` completed `cmd_run(file-lines)` and `tests_run(reviewer-allowlist)`.
Before the read-only hint and two tool approval settings, Codex offered the tools and refused calls that needed approval.

### Counters

For roles that follow the instructions, counts for `capability_wrong_role`, `capability_args_invalid`, `capability_path_denied`, and `capability_bad_ref` stay near zero.
The `ok` count increases after agents connect to servers.
A sustained `capability_wrong_role` count means a prompt or tool setting names a tool the role does not have.

The `subagent_identity_gate/denied/bash_agent_type_absent` count should stay at zero for well-formed dispatches.
A count above zero means a subagent reached Bash without a typed identity.
The `codex_role_session/refused/*` entries count launcher refusals.
If `capability/refused/capability_wrong_role` increases after binding, a prompt names a tool the role does not have.
