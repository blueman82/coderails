# E2: reviewer and scout Bash allowlist

This record describes the E2 decision. For current provider limits, use
[`docs/CAPABILITIES.md`](../CAPABILITIES.md) and the hook source.

The `hooks/scripts/reviewer_bash_allowlist.py` hook runs on PreToolUse for
`Bash`. It remains last in the Bash group, after `destructive_bash_gate`,
`enforce_pr_workflow`, `test_gate`, and `verification_volume_ceiling`.

## Which agents

The guarded Claude roles are `deploy-safety-reviewer`, `design-scout`,
`disposition-scout`, `preflight-scout`, and `source-auditor`. Their agent files
allow Bash and deny `Write`, `Edit`, and `NotebookEdit`. `spec-reviewer` has no
Bash. The hook does not guard `docs-auditor`, `loop-worker`, `wiki-writer`, or
`proof-author`. Those roles can write by design.

## What is and is not enforced

**Enforced by the hook:** The payload `agent_type` selects a guarded role.
That role can run one Bash command from this list:

- `ls`, `cat`, `head`, `tail`, `wc`, `grep`, `rg`, or `sha256sum`;
- `git status`, `git log`, `git diff`, `git show`, or `git blame`;
- `gh pr view` or `gh pr list` with `--json`.

The hook denies `;`, `|`, `&`, backticks, `$(`, `>`, `<`, and newlines. It
also denies `git -c`, other commands, and these flags: `--output`, `--pre`,
`--pre-glob`, `--ext-diff`, `--textconv`, and `--hostname-bin`. For example,
`find -exec`, `sed -i`, and interpreter commands fail. `rg` has its own
flag allowlist. Unknown long flags and `-z` fail. The hook strips a plugin
namespace before it matches `agent_type`. The namespaced form is an
inference; no live payload captured it. Each denial writes a log line and
a trace row. The reason code is `bash_allowlist_deny_{meta,flag,parse,argv}`.

**Fail-open by design:** An absent or foreign `agent_type` does not activate
this hook. The hook also ignores a non-Bash tool or a malformed payload.
Top-level calls carried no `agent_type` in the Claude Code 2.1.220 probe.
Thus, the hook did not restrict the orchestrator in that probe.

**Not enforced, and not to be claimed:**

- `docs-auditor` has Bash and can write by design. It is unguarded. The
  hook also leaves any other Bash role outside the guarded list alone.

- An allowed `git`, `grep`, `rg`, or `cat` can read any file that the process
  can read. The hook limits Bash commands; it does not hide secrets.
  It does not reject `$VAR` expansion.
- Agent frontmatter denies `Write` and `Edit`. This hook narrows Bash.
- Behaviour under `claude --agent <name>` is unverified (the live probe used a plain session).
- No command-level Bash rule was found in Claude agent frontmatter. This
  is an inference from the inspected files. The hook applies that rule.
- At the first E2 decision, `source-auditor` could not run a test suite
  through the Bash allowlist. Its instructions require fresh numbers.
  Allowing an interpreter would also permit file writes. The capability
  tool below addresses this cost.
- The listed Codex roles use `sandbox_mode = "read-only"` in their agent
  files. No per-command Bash hook was found for Codex. Its shell guidance
  is instruction text. The Codex agent files were unchanged by E2.

## Addendum: capability tools close the "Known cost" without widening Bash

`source-auditor` has the `tests.run` capability in `capabilities/profiles.json`.
It calls `<abs>/scripts/capability.py tests.run --json-args '{"name":"<declared>"}'`.
The hook allows that exact absolute path when the role profile grants the
tool. Otherwise, it returns `capability_denied_<tool>`. An `agent_type`
absent from the profiles remains unguarded. The hook still denies
`python3 -c`, `bash -c`, and `python3 <script>`. The test
`hooks/scripts/tests/capability_hook_test.py::test_e2_known_cost_closed_without_widening_bash`
checks this path.

`tests.run` executes declared repo commands with a timeout and a scrubbed
environment. It can write caches in the repo. It uses typed arguments and
an argv-path match in the Bash hook. It is not a harness-level typed tool;
that would need an MCP server, which does not ship here.

Codex has no per-agent Bash hook. The same capability script ships in
`packages/codex/scripts`, but Codex role limits come from the sandbox and
instruction text. A read-only sandbox may block test cache writes. That
last point is an inference. See [`docs/CAPABILITIES.md`](../CAPABILITIES.md).
