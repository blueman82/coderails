# Capability profiles

`capabilities/profiles.json` is the single source for what each agent type may reach. `scripts/capability_profiles_validate.py`
(run by `scripts/tests/capability_profiles_test.py`) fails when it disagrees with `agents/*.md` frontmatter or
`packages/codex/agents/*.toml`.

Capabilities: `repo.inspect`, `diff.read`, `tests.run`, `pr.comment` (reached through `scripts/capability.py <tool>`),
plus `worktree.write` (Write/Edit, or a non-read-only Codex sandbox) and `shell.raw` (unrestricted Bash). An agent with
a capability tool but no `shell.raw` is "guarded": the Bash allowlist hook derives its guarded set from this file.

## What each harness can enforce

| Property | Claude Code | Codex |
|---|---|---|
| Write/Edit withheld | frontmatter `tools`/`disallowedTools` (harness-enforced) | `sandbox_mode = "read-only"` (sandbox-enforced) |
| Bash narrowed to capability tools | **Bash removed**: the five guarded agent files list no `Bash` (probe-observed, see below). `reviewer_bash_allowlist.py` stays as defence in depth for an install whose agent file still lists Bash; `subagent_identity_gate.py` denies Bash from a subagent with no `agent_type` in a graph-bound session | **shell switched off**: each guarded role TOML carries `[features] shell_tool = false` (plus `sandbox_mode = "read-only"`, which alone does NOT bind a child). No per-agent Bash hook exists: Codex PreToolUse carries no `agent_type`/`agent_id`, so there is no Codex counterpart of the identity gate |
| Typed first-class tools | agent `tools:` are exactly `mcp__plugin_coderails_cap-<role>__<tool>` (+`Skill` for preflight-scout); servers declared by `.claude-plugin/plugin.json` `mcpServers` -> generated `capabilities/mcp.json` | `scripts/codex_role_session.py` launches a role as its own `codex exec` with exactly that role's server; native children inherit the parent's MCP servers, so no per-role server is registered in the Codex plugin manifest |
| `tests.run` | allowed for `source-auditor` only; bounded execution of declared argv lists, NOT read-only | same script; the read-only sandbox may block its cache writes (inferred) |

On Claude the guarded agents now reach the capability tools as harness-level typed MCP tools and hold no Bash (see Role
binding below). The paragraph that follows describes the Bash-path hook, which remains as defence in depth for an install whose
agent file still lists Bash. Interpreters (`python`, `node`, `bash -c`) stay denied for guarded agents; execution is only via
a declared name in `profiles.json` `tests`. The hook allows the call only when the caller's profile grants that tool, and refuses with
`capability_denied_<tool>`, `capability_unknown_tool` or `capability_bad_argv`. An `agent_type` absent from `profiles.json` (including `general-purpose`) is not this hook's concern and passes through unchanged.

Known gaps: the agent must be handed the absolute script path (the hook does not expand `$CLAUDE_PLUGIN_ROOT`); a
missing or malformed `profiles.json` makes the hook fall back to the original hard-coded guarded set (allowlist stays on, capability calls then deny as plain Bash). `tests.run` executes repo code: that is user-level code execution unless confined. On macOS it runs under `sandbox-exec` (no network, writes only to the repo, a throwaway HOME and tmp, real-home `.ssh`/`.config/gh`/`.aws`/`.gnupg` unreadable); elsewhere it refuses with `capability_sandbox_unavailable` unless `CAPABILITY_TESTS_UNSANDBOXED=1` (then it is NOT contained). A throwaway `$HOME` alone does not protect secrets: Python and ssh resolve the real home via the passwd entry. The validator also fails an agent file with no inline `tools:` line (the harness then grants all tools) and a guarded agent whose tools differ from the derived MCP names (only preflight-scout's `Skill` is added). The documented `general-purpose` source-auditor dispatch is not gated by profiles (it already has full Bash), so only a dispatch as `subagent_type: source-auditor` gets the tighter allowlist.

## Per-role MCP server

`scripts/capability_mcp.py --role <agent>` is a stdio MCP server (newline-delimited JSON-RPC: `initialize`,
`notifications/initialized`, `ping`, `tools/list`, `tools/call`) that serves exactly the capability tools
`capabilities/profiles.json` grants that role and dispatches in-process to `scripts/capability.py`. The profile stays the
single source of truth: `tools/list` is recomputed from it at launch, so a profile edit changes the served set and
`scripts/capability_profiles_validate.py` still flags frontmatter/Codex files that disagree. The Codex package carries
byte-identical copies of `capability.py`, `capability_mcp.py`, `lib/capability_extra.py` and `profiles.json`
(`packages/tests/test_codex_capability_parity.py`).

- **Tool names.** MCP tool names cannot contain dots, so `repo.inspect`, `diff.read`, `tests.run`, `pr.comment`, `cmd.run`
  are served as `repo_inspect`, `diff_read`, `tests_run`, `pr_comment`, `cmd_run`. Guarded read-only roles
  (`deploy-safety-reviewer`, `design-scout`, `disposition-scout`, `preflight-scout`) get `repo_inspect`, `diff_read`;
  `source-auditor` additionally gets `tests_run` and `cmd_run`. The two read tools advertise `readOnlyHint: true`.
  The execution tools advertise `readOnlyHint: false`; they can run repo code.
- **Per-role instance; role is not an argument.** The role is fixed at launch. No `inputSchema` has a `role` property and
  `capability.check` rejects unknown keys, so a smuggled `role` is `capability_args_invalid`. Startup exits 2 with a
  stderr reason when the role is absent from `profiles.json`, holds no capability tool, or an unknown flag is given.
  It tries to write a `capability_mcp_refused` trace row. A `tools/call` for a name outside the role's list returns a
  JSON-RPC error and tries to write a `capability_wrong_role` row. It dispatches nothing.
- **cwd and `worktree`.** A plugin MCP server's cwd is the session's cwd, not a subagent's worktree. Every repo tool
  therefore accepts an optional `worktree` argument, honoured only if it is a path listed by `git worktree list` in the
  server's own repo (else `capability_path_denied`).
- **More `repo.inspect` ops** (all through `safe_path` / `REF`): `show` (`spec` = `<ref>:<path>`), `blame`, `wc`, `sha256`,
  `glob` (a `git ls-files` pathspec, tracked files only) and `offset` on `read`.
- **`cmd.run`** runs one entry of `profiles.json` `named_commands` (`git-rev-count {ref}`, `file-lines {path}`,
  `file-sha256 {path}`): argv templates with typed placeholders (`repo_path`, `ref`), exact argument keys, whole-token
  substitution (no shell), executed through `capability.sandboxed()` like `tests.run` (no network, confined writes,
  scrubbed env). Granted to `source-auditor` only. Refusals: `capability_args_invalid` (unknown name, missing/extra key),
  `capability_path_denied` (`..`, absolute), `capability_bad_ref`.
- **Trace.** Each call and refusal tries to append a `capability` row with inputs `{tool, role, via: mcp}` (stored as
  hashes). A missing trace library or failed write leaves no row. A recognized tool's response sets `traced: false` in
  that case; startup and wrong-role errors have no `traced` field. Counters include only stored rows:
  `python3 scripts/lib/capability_counters.py [--since <ISO ts>]` (reads `CLAUDE_AGENTIC_LOOP_DIR`).
- **Cost.** Plugin MCP servers all launch at session start: one python process per role, five per session.

Limits (stated, not hidden): `cmd.run` and `pr.comment` offer no network command: `gh pr view` is
deliberately NOT offered, so reviewers work from `diff.read` and dispatcher-supplied PR metadata. `tests.run` and
`cmd.run` are contained only where `sandbox-exec` exists (else `capability_sandbox_unavailable`). The server cannot stop
an agent that holds a raw shell from bypassing it; that is what removing Bash from the agent achieves. Same-user policy
files are agent-writable: this is a cooperating-agent safeguard, not an absolute boundary.

Further stated limits: (1) `cmd.run` and `tests.run` read `capabilities/profiles.json` on every call, and `tests.run`
executes repo code in a sandbox that can write the repo, so that code can edit the command table within a session
(the same-user "tests.run executes repo code" boundary; `tools/list` is fixed at launch, the command tables are not).
(2) The `worktree` argument accepts any entry of `git worktree list`, not only the dispatched tree, so a granted role can
read, and via `tests.run`/`cmd.run` execute in, another agent's worktree of the same repo.

## Role binding: tools, generated config, identity gate, Codex role sessions

**Claude.** `.claude-plugin/plugin.json` declares `"mcpServers": "./capabilities/mcp.json"`. That file is GENERATED from
`profiles.json` by `python3 scripts/capability_profiles_validate.py --write-mcp` (one server `cap-<role>` per guarded
role, command `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/capability_mcp.py --role <role>`); `--check` (also the default) fails
on a doctored file, a server for a role not in the profile, or a missing one. Each guarded agent's frontmatter `tools:` is
exactly the derived `mcp__plugin_coderails_cap-<role>__<tool>` names (+`Skill` for `preflight-scout`); `disallowedTools`
stays. The validator names an error for: any `Bash`/`Write`/`Edit`/`NotebookEdit`/`Agent`/`Task`/`WebFetch`/`Read`/`Grep`/
`Glob` in a guarded agent, a stale or extra MCP name, and a full tool name over 64 characters (the API limit; the longest,
`cap-deploy-safety-reviewer`, is 62).

**Observed, not just configured.** `hooks/scripts/tests/reviewer_tools_probe_test.py` runs the real `claude` CLI against a
loopback API fixture (no billing), both as `--agent coderails:<role>` and as an Agent-tool dispatch with
`subagent_type`, and asserts the `tools` array of the request the model receives: exactly the profile-derived names for
all five roles, none of Bash, Write, Edit, NotebookEdit, Agent, Read. design-scout's list holds none of source-auditor's
server tools, and the live per-role servers refuse `tests_run` (design-scout) and any `cmd_run` name not in `profiles.json`.
A control agent that does list Bash shows Bash in the same request, so the probe can fail.

**Decision D4 (native Read/Grep/Glob removed too).** The literal reading is taken: a guarded role has MCP tools only.
`repo_inspect` compensates with `read` (with `offset`), `list`, `grep`, `glob`, `status`, `log`, `show`, `blame`, `wc`,
`sha256`. If reviewers prove unusable, restoring native `Read`/`Grep`/`Glob` is acceptable (they are not a shell); that is
a one-line change to `EXTRA_TOOLS`/`FORBIDDEN_TOOLS` in `scripts/lib/capability_validation.py` plus the agent files.

**Known cost: preflight-scout skills.** Its skills may shell out (wiki-query runs a search command). Without Bash the
agent text tells it to report that step UNSUPPORTED; it is never handed a shell. Measure how often via the
`capability/refused` and agent reports before re-adding anything.

**Identity gate.** `hooks/scripts/subagent_identity_gate.py` (registered right after `reviewer_bash_allowlist`) denies a Bash
call with `agent_id` present and `agent_type` absent/blank in a graph-bound session: reason `bash_agent_type_absent`. It
lives in its own hook; `loop_dispatch_guard.py` is not touched. Claude only. It is a cooperating-agent safeguard: it
relies on the harness populating `agent_id`, and a session with no `progress.json` is out of its scope. It denies only
when tool is Bash, `agent_id` is present, `agent_type` is blank and the session is graph-bound; it allows when
`session_id` is missing/`?`, `progress.json` is missing/unreadable/without `graph`, `agent_id` is omitted, or the tool is
not Bash. It is not "fail-closed" in general. Claude role binding is also not a forced route: a present `agent_type`
(including `general-purpose`, which keeps Bash) passes untouched, so dispatching a guarded role by `subagent_type`
depends on lane A's `loop_dispatch_guard` (not changed here) and is otherwise a cooperating-orchestrator convention.

**Codex.** Each guarded role TOML carries `[features]` / `shell_tool = false` after the instructions string (a table
before `developer_instructions` would swallow it) and keeps `sandbox_mode = "read-only"`; the validator requires both.
`sandbox_mode` alone is not sufficient: a native child preserves the parent's permissions and MCP configuration.
`scripts/codex_role_session.py --role <agent> --prompt-file <file> [--cwd <dir>]` (byte-identical copy in the Codex
package) launches `codex exec --ignore-user-config -s read-only -c features.shell_tool=false -c
features.multi_agent=false -c mcp_servers.cap-<role>=... -`. It registers only that role's server. It reads the prompt
from the file on stdin and passes an allowlisted environment (PATH, HOME, CODEX_HOME, LANG, LC_ALL, TERM, TMPDIR; no
tokens). It also loads the tracked role TOML's
`developer_instructions` into the contained session. The Codex cite-check, merge, workflow, post-review,
workflow-audit, and docs-sync skills route guarded review roles through this launcher with an exact-head worktree.
For `source-auditor` only, the launcher sets `approval_mode="approve"` on that server's `cmd_run` and `tests_run` tools.
This allows the two granted, sandboxed execution tools to run under Codex's `approval=never` policy. It adds no approval
for other tool names or roles. The [Codex config reference](https://learn.chatgpt.com/docs/config-file/config-reference)
defines the per-server, per-tool setting. The MCP server still checks the role, arguments, named command or test, and
execution sandbox. These same-user files can be changed by repo code; this route is not a tamper-proof boundary.
Use it for `source-auditor`, because
`tests_run`/`cmd_run` must not be reachable by inherited children. It refuses roles that are not guarded profile entries.
The Codex plugin manifest declares no `mcpServers`: a manifest server would be inherited by every native child, and
Codex's `mcpServers` handling could not be exercised offline here, so a native Codex child of a guarded role has the
shell off and no capability tools and must report file/history checks UNSUPPORTED; route real work through the role
session.

Accepted limit (review finding): `scripts/installer/codex.py` is untouched, so the launcher is the only Codex route to
the typed tools; the plan's installer-managed read-only reviewer `mcp_servers` block is not built because it would be
inherited by every native child. The role-TOML `[features]` block is config asserted, not observed.

Stated limits of the Codex path (not hidden): (1) The role session is the built alternative, not a forced route. Nothing
in the installer or the agent flow stops an orchestrator running a native Codex child or a plain `codex exec`, and Codex
PreToolUse carries no `agent_type`, so no hook can backstop it; the plan accepts "separate contained sessions where a
sandbox/MCP boundary is required" and the installer deliberately adds no per-role `mcpServers` block (it would be
inherited by every native child). (2) `--ignore-user-config` skips `$CODEX_HOME/config.toml` only. Project `.codex/`
config discovered from the cwd up to the repo root is NOT skipped, so the launcher refuses a `--cwd` (or working
directory) whose tree holds a `.codex` directory; "exactly one `mcp_servers` entry" is then true of the effective
config for that tree, and the live test observes the tools array for the repo cwd only. Project `AGENTS.md` still loads
as instructions; it grants no tools.

`subagent_identity_gate` is ON by default; `subagent_identity_gate: off` in `.coderails/workflow.config.yaml` disables
it (any other value leaves it on). Trace rows `subagent_identity_gate/denied/bash_agent_type_absent` show it firing.

`preflight-scout` keeps `Skill`. Skills such as `engineering-principles-*` declare `allowed-tools` that include Bash,
Write and Edit. Whether invoking one grants a tool the subagent's `tools:` list omits is UNVERIFIED (no probe re-lists
tools after a Skill call). If it did, the remaining controls are `reviewer_bash_allowlist` (agent_type present) and
`subagent_identity_gate`; treat "no shell for preflight-scout" as probe-observed for the initial tools array only.

**Codex observation.** `scripts/tests/codex_role_session_live_test.py` runs the real `codex exec` with the launcher's
argv against a loopback Responses fixture that answers with an `exec_command` call. With the launcher's argv the request's
`tools` array holds no `exec_command`/`write_stdin`, the call returns `unsupported call: exec_command`, and only the
requested role's server tools are present. All five guarded roles offer no `spawn_agent` tool. Without
`features.multi_agent=false`, the control run offers `spawn_agent`. Without `features.shell_tool=false`, the control
run offers the shell and executes the command. The tests observe the launcher's argv. They do not test the `[features]`
block in the role TOML files by spawning a native child.
An OAuth spot check also ran the launcher with `approval=never` and a read-only Codex sandbox. `design-scout` completed
`repo_inspect`; `source-auditor` completed `cmd_run(file-lines)` and `tests_run(reviewer-allowlist)`. Before the read
annotation and the two per-tool approval settings, Codex offered the tools but refused calls that required approval.

Measurement note: the success signal is the `capability_wrong_role`, `capability_args_invalid`, `capability_path_denied`
and `capability_bad_ref` counts staying near zero for well-behaved roles, with `ok` rising once agents are bound to the
servers. A sustained `capability_wrong_role` rate means a prompt or profile asks a role for a tool it does not hold.

Binding measurement note: `subagent_identity_gate/denied/bash_agent_type_absent` should stay at zero for well-formed
dispatches; any count means a subagent reached Bash without a typed identity. `codex_role_session/refused/*` counts
launcher refusals. A rising `capability/refused/capability_wrong_role` after binding means a prompt asks a role for a
tool it does not hold.
