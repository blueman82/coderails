# Capability profiles

`capabilities/profiles.json` defines what each agent type may use.
`scripts/capability_profiles_validate.py` checks it against `agents/*.md`
frontmatter and `packages/codex/agents/*.toml`. The check runs through
`scripts/tests/capability_profiles_test.py` and fails on a mismatch.

Capabilities: `repo.inspect`, `diff.read`, `tests.run`, `pr.comment` (reached through `scripts/capability.py <tool>`),
plus `worktree.write` (Write/Edit, or a non-read-only Codex sandbox) and `shell.raw` (unrestricted Bash). An agent with
a capability tool but no `shell.raw` is "guarded": the Bash allowlist hook derives its guarded set from this file.

## What each harness can enforce

| Property | Claude Code | Codex |
|---|---|---|
| Write/Edit withheld | frontmatter `tools`/`disallowedTools` (harness-enforced) | `sandbox_mode = "read-only"` (sandbox-enforced) |
| Bash narrowed to capability tools | `reviewer_bash_allowlist.py` PreToolUse hook: exact absolute path of `scripts/capability.py`, tool checked against the caller's `agent_type` profile | not enforced: no per-agent Bash hook (`agent_type` appears only in `spawn_agent` tool input); instruction text only |
| Typed first-class tools | per-role MCP server ships (see below); agents are not yet bound to it | same server mirrored; not yet bound |
| `tests.run` | allowed for `source-auditor` only; bounded execution of declared argv lists, NOT read-only | same script; the read-only sandbox may block its cache writes (inferred) |

Capability tools use typed arguments and an argv-path match on Bash. They are
not harness-level typed tools. Guarded agents cannot call interpreters such as
`python`, `node`, or `bash -c`. They can run only a name declared in
`profiles.json` `tests`. The hook allows a call only if the caller's profile
grants that tool. Otherwise, it refuses with `capability_denied_<tool>`,
`capability_unknown_tool`, or `capability_bad_argv`. An `agent_type` absent
from `profiles.json` (including `general-purpose`) passes through unchanged.

Known gaps: the agent must be handed the absolute script path (the hook does not expand `$CLAUDE_PLUGIN_ROOT`); a
missing or malformed `profiles.json` makes the hook fall back to the original hard-coded guarded set (allowlist stays on, capability calls then deny as plain Bash). `tests.run` executes repo code: that is user-level code execution unless confined. On macOS it runs under `sandbox-exec` (no network, writes only to the repo, a throwaway HOME and tmp, real-home `.ssh`/`.config/gh`/`.aws`/`.gnupg` unreadable); elsewhere it refuses with `capability_sandbox_unavailable` unless `CAPABILITY_TESTS_UNSANDBOXED=1` (then it is NOT contained). A throwaway `$HOME` alone does not protect secrets: Python and ssh resolve the real home via the passwd entry. The validator also fails an agent file with no inline `tools:` line (the harness then grants all tools) and guarded agents holding `Task`/`WebFetch`/`mcp__*` (only preflight-scout's `Skill` is allowlisted). The documented `general-purpose` source-auditor dispatch is not gated by profiles (it already has full Bash), so only a dispatch as `subagent_type: source-auditor` gets the tighter allowlist.

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
  `source-auditor` additionally gets `tests_run` and `cmd_run`.
- **Per-role instance; role is not an argument.** The role is fixed at launch. No `inputSchema` has a `role` property and
  `capability.check` rejects unknown keys, so a smuggled `role` is `capability_args_invalid`. Startup exits 2 (stderr
  reason, trace `capability_mcp_refused`) when the role is absent from `profiles.json`, holds no capability tool, or an
  unknown flag is given. A `tools/call` for a name outside the role's list is a JSON-RPC error, a
  `capability_wrong_role` trace row, and nothing is dispatched.
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
- **Trace.** Every call and refusal appends a `capability` row with inputs `{tool, role, via: mcp}` (stored as hashes).
  Counters: `python3 scripts/lib/capability_counters.py [--since <ISO ts>]` (reads `CLAUDE_AGENTIC_LOOP_DIR`).
- **Cost.** Plugin MCP servers all launch at session start: one python process per role, five per session.

Limits (stated, not hidden): this unit ships the server and its tests; it does not by itself remove Bash from any agent
(frontmatter/Codex binding is the next unit). `cmd.run` and `pr.comment` offer no network command: `gh pr view` is
deliberately NOT offered, so reviewers work from `diff.read` and dispatcher-supplied PR metadata. `tests.run` and
`cmd.run` are contained only where `sandbox-exec` exists (else `capability_sandbox_unavailable`). The server cannot stop
an agent that holds a raw shell from bypassing it; that is what removing Bash from the agent achieves. Same-user policy
files are agent-writable: this is a cooperating-agent safeguard, not an absolute boundary.

Further stated limits: (1) `cmd.run` and `tests.run` read `capabilities/profiles.json` on every call, and `tests.run`
executes repo code in a sandbox that can write the repo, so that code can edit the command table within a session
(the same-user "tests.run executes repo code" boundary; `tools/list` is fixed at launch, the command tables are not).
(2) The `worktree` argument accepts any entry of `git worktree list`, not only the dispatched tree, so a granted role can
read, and via `tests.run`/`cmd.run` execute in, another agent's worktree of the same repo.

Measurement note: the success signal is the `capability_wrong_role`, `capability_args_invalid`, `capability_path_denied`
and `capability_bad_ref` counts staying near zero for well-behaved roles, with `ok` rising once agents are bound to the
servers. A sustained `capability_wrong_role` rate means a prompt or profile asks a role for a tool it does not hold.
