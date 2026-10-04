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
| Bash narrowed to capability tools | `reviewer_bash_allowlist.py` PreToolUse hook: exact absolute path of `scripts/capability.py`, tool checked against the caller's `agent_type` profile | not enforced: no per-agent Bash hook (`agent_type` appears only in `spawn_agent` tool input); instruction text only |
| Typed first-class tools | no (needs an MCP server; none ships) | no |
| `tests.run` | allowed for `source-auditor` only; bounded execution of declared argv lists, NOT read-only | same script; the read-only sandbox may block its cache writes (inferred) |

So the capability tools are typed arguments plus an argv-path match on Bash, not harness-level typed tools. Interpreters
(`python`, `node`, `bash -c`) stay denied for guarded agents; execution is only via a declared name in `profiles.json`
`tests`. The hook allows the call only when the caller's profile grants that tool, and refuses with
`capability_denied_<tool>`, `capability_unknown_agent`, `capability_unknown_tool` or `capability_bad_argv`.

Known gaps: the agent must be handed the absolute script path (the hook does not expand `$CLAUDE_PLUGIN_ROOT`); a
missing or malformed `profiles.json` makes the hook raise (non-blocking hook error), so the validator test is the guard.
