# Coderails agents catalogue

[Coderails components](REFERENCE.md).

## Agents

When the plugin is on, Claude discovers subagent definitions in `agents/`. The names use `coderails:<name>`.
A skill dispatches by name. The definition supplies the model and tools if the child does not follow the prompt text.

In a graph-bound loop, `begin-wave` records the node's contract role. The `loop_dispatch_guard.py` hook checks the dispatched role.
The named read-only roles are `preflight-scout`, `design-scout`, `disposition-scout`, `source-auditor`, and `deploy-safety-reviewer`.
Use the role name `coderails:<role>`. Other roles accept that name or `general-purpose`. An incorrect role gives `role_mismatch`.

A scout can run only if the plugin agent is installed. The sandboxed Bash launcher does not send an agent type.

The tool controls differ by agent:

- The `spec-reviewer` has `tools: Read, Grep, Glob`. It has no write tool.

- The `source-auditor` excludes `Write` and `Edit` through `disallowedTools`. It keeps `Bash` so it can run commands again.
  Bash can write files. The read-only contract relies in part on the agent to follow the instructions.

- The `pr-review-toolkit:code-reviewer` agent has no `tools:` key. It has full tool access.
  Its definition supplies a pinned model and a rubric.

Claim that an agent is "physically unable" to edit only if its `tools:` and `disallowedTools` controls prevent edits.

Plugin agent definitions accept `name`, `description`, `model`, `effort`, and `maxTurns`. They also accept `tools`, `disallowedTools`, `skills`, `memory`, `background`, and `isolation`.
They do not accept `hooks`, `mcpServers`, or `permissionMode`.

#### `source-auditor`

**Purpose:** Re-derive one or more claims from durable sources only: file contents, Git output, and new command output.
Give a PASS, FAIL, or UNSUPPORTED verdict with sources for each claim.

**Tools:** `Read, Grep, Glob, Bash`, with `disallowedTools: Write, Edit, NotebookEdit`.
Rule 3 uses Bash to run commands again and calculate the numbers. Bash can write files. The agent must follow the read-only instructions.

**Model:** `sonnet`.

**Used by:** `/coderails:cite-check` forks into this agent. The auditor cannot read the conversation that gave the claim.
The fork prevents self-verification.

#### `spec-reviewer`

**Purpose:** Examine a spec or design document before implementation planning. Check its scope, clarity, internal consistency, completeness, and YAGNI.
Give Approved or Issues Found.

**Tools:** `Read, Grep, Glob` (read-only).

**Model:** `sonnet`.

**Used by:** Step 7 of `superpowers:brainstorming` uses this agent. The author can infer meaning from ambiguous wording. The reviewer has only the text on the page.

#### `wiki-writer`

**Purpose:** Read, write, and maintain LLM Wiki pages that follow the `AGENTS-wiki-schema.md` contract.
Write files, commit, and open PRs when the vault config makes them necessary.

**Tools:** `Read, Grep, Glob, Write, Edit, Bash`.

**Model:** `sonnet`.

**Used by:** `wiki-ingest`, `wiki-query`, and `wiki-lint` write through this agent.
A read-only agent such as `Explore` cannot do their commit step.

#### `loop-worker`

**Purpose:** Implement one work unit. Write code and tests, commit, examine the result, and report with records for verification.
Use BLOCKED or NEEDS_CONTEXT when necessary information is unavailable.

**Tools:** `Read, Grep, Glob, Write, Edit, Bash, Skill`.

**Model:** `inherit`. Set the model explicitly on dispatch. See Model Selection in `superpowers:subagent-driven-development`.
Without a model, the child inherits the session model, which usually costs the most.

**Used by:** `superpowers:subagent-driven-development`, `superpowers:dispatching-parallel-agents`.

#### `design-scout`

**Purpose:** If the primitive, topology, or other architecture is undecided, read the actual code paths.
Give one recommendation and the condition that would change it. Do not examine a document with a proposed solution.
Read the primitive contract if a shared lock, queue, transaction, or equivalent primitive runs in nested, recursive, parallel, or re-entrant code.

**Tools:** `Read, Grep, Glob, Bash`, with `disallowedTools: Write, Edit, NotebookEdit`.
Bash can write files. The read-only contract relies on the agent to follow the instructions.

**Model:** `inherit`. Set the model explicitly on dispatch.
Phase 2.5 of `agentic-loop` uses `default` or `frontier` according to the Phase 2.8 table.

**Used by:** Phase 2.5 of `agentic-loop` for open design decisions.

#### `disposition-scout`

**Purpose:** Given a Phase 1 plan that retires code paths, read the actual consumers and constraints for each retirement unit.
Recommend a clean break or keep compatibility. Default to a clean break.
Keep compatibility only if a named consumer cannot migrate in this unit and there is a removal ticket.

**Tools:** `Read, Grep, Glob, Bash`, with `disallowedTools: Write, Edit, NotebookEdit`.
Bash can write files. The read-only contract relies on the agent to follow the instructions.

**Model:** `inherit`. Set the model explicitly on dispatch.
Phase 2.6 of `agentic-loop` selects the model role inline according to the Phase 2.8 table.
See "Inline sites elsewhere" in `model-routing.md`.

**Used by:** Phase 2.6 of `agentic-loop` for decisions on what to retire.

#### `docs-auditor`

**Purpose:** Run `/sync-docs` on repository docs such as `README.md`, `AGENTS.md`, and `docs/REFERENCE.md`.
Compare those files with the newly merged code. Correct only differences that the loop's PRs caused. Report earlier differences to the human.
The `wiki-writer` owns the external wiki vault.

**Tools:** `Read, Grep, Glob, Bash, Edit, Skill, Task`, with `disallowedTools: Write, NotebookEdit`.

**Model:** `sonnet`.

**Used by:** Phase 9 of `agentic-loop`.

#### `preflight-scout`

**Purpose:** Run planning-sequence, premortem, assumptions, notchecked, and wiki-query.
Read `standing-orders.md` and recent `retro.json` files. Give one consolidated pre-flight report.
The report cannot weaken a gate, skip a phase, or justify a future eval change.

**Tools:** `Read, Grep, Glob, Bash, Skill`, with `disallowedTools: Write, Edit, NotebookEdit`.

**Model:** `sonnet`.

**Used by:** Phase 2 pre-flight of `agentic-loop`.

#### `proof-author`

**Purpose:** Write a frozen `proof.json` from `authorising_prompt_raw`, `session_id`, and `loop_id`.
Use the three explicit dispatch inputs verbatim and docs that the prompt names directly.
Do not read `progress.json`, the plan, the spec, decisions about the design, or the dispatching conversation.
For Phase 2.7e of `agentic-loop`, the proof author and grader are different agents.
Each proof status stays `"pending"`. The author does not run or score proofs.

**Tools:** `Read, Bash, Write`, with `disallowedTools: NotebookEdit`.

**Model:** `sonnet`.

**Used by:** Phase 2.7e of `agentic-loop`.

#### `deploy-safety-reviewer`

**Purpose:** Examine a PR or planned change for deployment risk and give one verdict with a named risk boundary.
Check rollback risk, blast radius, observability during deployment, compatibility of migrations and schemas with previous versions, and applicable feature flags.
This agent checks deployment risk for changes that are correct, pass their safety checks, and report errors.

The `pr-review-toolkit:code-reviewer` agent checks if the code is correct and checks its quality. The `/security-review` checks auth, secrets, and the treatment of untrusted input as instructions.
The `pr-review-toolkit:silent-failure-hunter` agent checks that code reports and handles errors correctly.

**Tools:** `Read, Grep, Glob, Bash`, with `disallowedTools: Write, Edit, NotebookEdit`.
Bash can write files. The read-only contract relies on the agent to follow the instructions, as for `source-auditor` and `design-scout`.

**Model:** `sonnet`.

**Used by:** Changes with a runtime or production surface, before merge. See "Agents deliberately not shipped".

#### Agents deliberately not shipped

The mandatory `pr-review-toolkit@claude-plugins-official` dependency supplies `code-reviewer`, `code-simplifier`, `comment-analyzer`, `pr-test-analyzer`, `silent-failure-hunter`, and `type-design-analyzer`.
Coderails uses those definitions without duplicates, so the dispatcher can select one agent.
Skills that use code inspection name `pr-review-toolkit:code-reviewer` directly.

The `agents/deploy-safety-reviewer.md` definition checks deployment concerns that the other agents skip.
It checks rollback risk, blast radius, migration and schema safety, feature flags, and observability during deployment.
It checks if alerts, dashboards, and runbooks include the full blast radius. The `silent-failure-hunter` owns code-level error handling.

---
