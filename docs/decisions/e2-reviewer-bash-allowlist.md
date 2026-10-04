# E2: reviewer and scout Bash allowlist

Hook: `hooks/scripts/reviewer_bash_allowlist.py` (PreToolUse, `Bash`), registered last in the Bash group, after
`destructive_bash_gate`, `enforce_pr_workflow`, `test_gate` and `verification_volume_ceiling` (order unchanged).

## Which agents

Claude agents that keep `Bash` and are read-only by contract: `deploy-safety-reviewer`, `design-scout`,
`disposition-scout`, `preflight-scout`, `source-auditor` (`agents/*.md`: `tools: Read, Grep, Glob, Bash` with
`disallowedTools: Write, Edit, NotebookEdit`). `spec-reviewer` has no Bash. `docs-auditor`, `loop-worker`,
`wiki-writer` and `proof-author` write by design and are not guarded.

## What is and is not enforced

**Enforced (by the hook, keyed on the payload `agent_type`):** a guarded agent's Bash call is denied unless it is one
command whose argv starts with `ls`, `cat`, `head`, `tail`, `wc`, `grep`, `rg`, `sha256sum`, `git status|log|diff|show|blame`
or `gh pr view|list ... --json`. Denied on sight: `;` `|` `&` backtick `$(` `>` `<`, newlines, `git -c`, any other
command (so `find -exec/-delete`, `sed -i`, `python`/`python3`/`node`/`bash -c` all fail), and the flags
`--output`, `--pre`, `--pre-glob`, `--ext-diff`, `--textconv`, `--hostname-bin`. `rg` is on a per-flag allowlist
(unknown long flags and `-z` are denied) because its flag surface is open-ended. `agent_type` is matched after stripping a
plugin namespace (`coderails:design-scout`); the namespaced form is inferred, not captured from a live payload. Each denial
writes a log line and a trace row with `reason_code=bash_allowlist_deny_{meta,flag,parse,argv}` naming the cause.

**Fail-open by design:** an absent or foreign `agent_type`, a non-Bash tool, or a malformed payload is a no-op.
Top-level calls carry no `agent_type` (AGENTS.md, `agent_only_gate` probe on Claude Code 2.1.220), so the
orchestrator is never restricted.

**Not enforced, and not to be claimed:**

- `docs-auditor` has Bash plus Edit/Task and writes by design, so it is unguarded; any other Bash-bearing agent not in
  the guarded list is likewise unrestricted.

- An allowlisted `git`, `grep`, `rg` or `cat` can still read secrets anywhere the process can read. This is a
  write and execution guard, not a confidentiality guard. `$VAR` expansion is not rejected.
- `Write`/`Edit` denial (frontmatter `disallowedTools`) is the real block on file writes; this hook narrows Bash.
- Behaviour under `claude --agent <name>` is unverified (the live probe used a plain session).
- Claude frontmatter has no command-level Bash restriction (inferred: none found), so only a hook can enforce it.
- Known cost: `source-auditor` instructs "run the thing" to re-derive numbers (test suite, coverage script). A
  test-suite run is not on the allowlist, so those runs are now denied for guarded types. Widening would admit an
  interpreter that can write, so it is left for a human decision.
- **Codex** keeps `sandbox_mode = "read-only"` on `deploy-safety-reviewer`, `design-scout`, `disposition-scout`,
  `preflight-scout`, `source-auditor` and `spec-reviewer` (`grep sandbox_mode packages/codex/agents/*.toml`). No
  per-command knob was found (inferred), so shell reads there are instruction-only. The Codex tomls are unchanged.

## Addendum: capability tools close the "Known cost" without widening Bash

`source-auditor` now has the `tests.run` capability (`capabilities/profiles.json`). It reaches it as
`<abs>/scripts/capability.py tests.run --json-args '{"name":"<declared>"}'`; the hook allows that exact absolute path
only when the caller's profile grants the tool (`capability_denied_<tool>` otherwise, `capability_unknown_agent` for a
foreign `agent_type`). `python3 -c`, `bash -c` and `python3 <script>` stay denied. Pinned by
`hooks/scripts/tests/capability_hook_test.py::test_e2_known_cost_closed_without_widening_bash`.

What this is not: `tests.run` is bounded execution of repo code (declared argv lists, timeout, scrubbed env), not
read-only, and a declared suite can still write caches in the repo. It is a typed argument schema plus an argv-path
match on Bash, not a harness-level typed tool (that needs an MCP server; none ships). On Codex there is no per-agent
Bash hook, so the same script ships in `packages/codex/scripts` but per-agent gating there is `sandbox_mode` plus
instruction text only, and a read-only sandbox may block the suite's cache writes (inferred). See `docs/CAPABILITIES.md`.
