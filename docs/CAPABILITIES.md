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

Known gaps:

- The dispatcher must provide the absolute script path. The hook does not expand `$CLAUDE_PLUGIN_ROOT`.
- If `profiles.json` is missing or invalid, the hook uses its original guarded-agent set. The Bash allowlist stays active, but capability calls are denied as plain Bash.
- `tests.run` executes repo code. On macOS, `sandbox-exec` blocks network access and limits writes to the repo, a temporary home, and tmp. It denies reads of the real home's `.ssh`, `.config/gh`, `.aws`, and `.gnupg`. On other platforms, the tool refuses with `capability_sandbox_unavailable` unless `CAPABILITY_TESTS_UNSANDBOXED=1`; that override removes containment.
- A temporary `$HOME` alone does not protect secrets. Python and ssh can resolve the real home through the passwd entry.
- The validator rejects an agent file without an inline `tools:` line, because the harness would grant all tools. It also rejects `Task`, `WebFetch`, or `mcp__*` for guarded agents. Only preflight-scout's `Skill` is allowed.
- A `general-purpose` source-auditor dispatch keeps full Bash access. Only `subagent_type: source-auditor` gets the tighter profile allowlist.

## Per-role MCP server

`scripts/capability_mcp.py --role <agent>` starts a stdio MCP server. It uses
newline-delimited JSON-RPC. It supports `initialize`,
`notifications/initialized`, `ping`, `tools/list`, and `tools/call`.
It serves only the tools that `capabilities/profiles.json` grants to the
selected role. It calls `scripts/capability.py` in-process. At launch,
`tools/list` reads the profile. A profile change changes the served set on
the next launch. `scripts/capability_profiles_validate.py` checks that agent
frontmatter and Codex files agree with the profile.

The Codex package has byte-identical copies of `capability.py`,
`capability_mcp.py`, `lib/capability_extra.py`, and `profiles.json`. The parity
check is `packages/tests/test_codex_capability_parity.py`.

- **Tool names:** MCP names cannot contain dots. The server maps
  `repo.inspect`, `diff.read`, `tests.run`, `pr.comment`, and `cmd.run` to
  `repo_inspect`, `diff_read`, `tests_run`, `pr_comment`, and `cmd_run`.
  `deploy-safety-reviewer`, `design-scout`, `disposition-scout`, and
  `preflight-scout` get `repo_inspect` and `diff_read`. `source-auditor` also
  gets `tests_run` and `cmd_run`.
- **Role:** The role is fixed at launch. No `inputSchema` accepts `role`.
  `capability.check` rejects an unknown key with `capability_args_invalid`.
  The server exits 2 at startup if the role is absent from the profile,
  has no capability tool, or receives an unknown flag. It writes a reason
  to stderr and a `capability_mcp_refused` trace row. A `tools/call` outside
  the role's list returns a JSON-RPC error and writes
  `capability_wrong_role`; it dispatches nothing.
- **Working tree:** The server's cwd is the session's cwd, which may differ
  from a subagent's worktree. Repo tools accept an optional `worktree`.
  They honor it only when `git worktree list` in the server's repo names
  that path. Otherwise they refuse with `capability_path_denied`.
- **`repo.inspect`:** It also supports `show` (`spec` = `<ref>:<path>`),
  `blame`, `wc`, `sha256`, `glob`, and `offset` on `read`. `glob` uses a
  `git ls-files` pathspec and returns tracked files only. These operations
  pass through `safe_path` and `REF` checks.
- **`cmd.run`:** It runs one `named_commands` entry from `profiles.json`:
  `git-rev-count {ref}`, `file-lines {path}`, or `file-sha256 {path}`.
  Templates use typed `repo_path` and `ref` placeholders, exact argument
  keys, and whole-token substitution without a shell. Like `tests.run`,
  it uses `capability.sandboxed()`, with no network, confined writes, and
  a scrubbed environment. Only `source-auditor` gets it. Unknown names or
  wrong keys return `capability_args_invalid`. `..` or an absolute path
  returns `capability_path_denied`; a bad ref returns `capability_bad_ref`.
- **Trace and cost:** Each call or refusal writes a `capability` row with
  hashed `{tool, role, via: mcp}` inputs. Read counts with
  `python3 scripts/lib/capability_counters.py [--since <ISO ts>]`; it reads
  `CLAUDE_AGENTIC_LOOP_DIR`. Plugin MCP servers start with the session:
  one Python process per role, five per session.

This unit ships the server and tests. It does not bind agents to the server
or remove their raw Bash access. An agent with a shell can bypass the server.
`cmd.run` and `pr.comment` offer no network command. In particular, the
server does not offer `gh pr view`; reviewers use `diff.read` and PR metadata
from the dispatcher. `tests.run` and `cmd.run` are contained only where
`sandbox-exec` exists. Else they refuse with
`capability_sandbox_unavailable`. Same-user agents can write policy files,
so this is a cooperating-agent safeguard, not an absolute boundary.

Both commands read `capabilities/profiles.json` on each call. `tests.run`
executes repo code in a sandbox that can write to the repo. That code can
change the command table during a session. `tools/list` stays fixed from
launch, but the command tables do not. The optional `worktree` can name any
entry in `git worktree list`, including another agent's worktree in the same
repo. A granted role can read it and run `tests.run` or `cmd.run` there.

Monitor `capability_wrong_role`, `capability_args_invalid`,
`capability_path_denied`, and `capability_bad_ref`. For roles that use the
server correctly, these counts should stay near zero and `ok` should rise.
A sustained `capability_wrong_role` count means a prompt or profile asks a
role to use a tool it does not hold.
