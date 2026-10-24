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
| Typed first-class tools | no (needs an MCP server; none ships) | no |
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
