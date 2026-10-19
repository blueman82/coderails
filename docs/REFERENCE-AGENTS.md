# Coderails agents catalogue

[Component reference](REFERENCE.md).

## Agents

Subagent definitions in `agents/`, auto-discovered when the plugin is enabled and
referenced by their namespaced name (`coderails:<name>`). Skills dispatch these
by name instead of pasting a prompt into a `general-purpose` subagent: the model
and tool set travel with the definition, so they survive even if the dispatching
prose is ignored. Inside a graph-bound loop this is enforced: `begin-wave` stores
each node's contract role and `loop_dispatch_guard.py` requires the guarded
read-only scouts (`preflight-scout`, `design-scout`, `disposition-scout`,
`source-auditor`, `deploy-safety-reviewer`) to be dispatched as `coderails:<role>`;
other roles accept that or `general-purpose`, and anything else is `role_mismatch`.
A plugin agent that is not installed cannot run a guarded scout, and the sandboxed
Bash launcher carries no agent type.

How strong that guarantee is varies per agent, and the difference matters:

- **Enforced.** `spec-reviewer` declares `tools: Read, Grep, Glob` and has no
  write capability at all.
- **Partly enforced.** `source-auditor` withholds `Write`/`Edit` via
  `disallowedTools` but keeps `Bash` (it must re-run commands), and `Bash` can
  mutate — so its read-only property is partly discipline.
- **Not enforced.** `pr-review-toolkit:code-reviewer` declares no `tools:` key
  and therefore has full tool access. Naming it buys a pinned model and a
  maintained rubric, not an inability to edit what it reviews.

Do not describe agent dispatch as making a reviewer "physically unable" to edit
unless that specific agent's `tools:`/`disallowedTools` actually says so.

Plugin agents support `name`, `description`, `model`, `effort`, `maxTurns`,
`tools`, `disallowedTools`, `skills`, `memory`, `background` and `isolation`.
They do **not** support `hooks`, `mcpServers` or `permissionMode`.

#### `source-auditor`

**Purpose:** Re-derives one or more stated claims from durable sources only —
file contents, git output, fresh command output — and returns a sourced
PASS / FAIL / UNSUPPORTED verdict per claim.

**Tools:** `Read, Grep, Glob, Bash`, with `disallowedTools: Write, Edit, NotebookEdit`. Not read-only by construction: rule 3 requires re-running commands to re-derive numbers, so `Bash` stays — and `Bash` can mutate. `Write`/`Edit` are withheld; the rest is the agent's stated discipline.
**Model:** `sonnet`.

**Used by:** `/coderails:cite-check`, which forks into it so the audit runs with no
access to the conversation that produced the claim. Verifying a claim inside the
context that generated it is self-verification; the fork is the point.

#### `spec-reviewer`

**Purpose:** Reviews a spec or design document for completeness, internal
consistency, clarity, scope and YAGNI before any implementation planning starts.
Returns Approved or Issues Found.

**Tools:** `Read, Grep, Glob` (read-only). **Model:** `sonnet`.

**Used by:** `superpowers:brainstorming` step 7, replacing an inline self-review.
The author knows what they meant, so ambiguous wording reads as clear to them;
the reviewer only knows what is on the page.

#### `wiki-writer`

**Purpose:** Reads, authors and maintains LLM Wiki pages against the
`AGENTS-wiki-schema.md` contract. Writes files, commits, and opens PRs when the
vault config requires it.

**Tools:** `Read, Grep, Glob, Write, Edit, Bash`. **Model:** `sonnet`.

**Used by:** `wiki-ingest`, `wiki-query`, `wiki-lint`. All three write — a
read-only agent such as `Explore` would break them at their commit step.

#### `loop-worker`

**Purpose:** Implements one scoped unit of work end-to-end: code, tests, commit,
self-review, then an evidence-backed report. Escalates (BLOCKED / NEEDS_CONTEXT)
rather than guessing.

**Tools:** `Read, Grep, Glob, Write, Edit, Bash, Skill`. **Model:** `inherit` —
pass an explicit model at dispatch per `superpowers:subagent-driven-development`'s Model
Selection section; an unconsidered dispatch inherits the session's model, which
is usually the most expensive one.

**Used by:** `superpowers:subagent-driven-development`, `superpowers:dispatching-parallel-agents`.

#### `design-scout`

**Purpose:** Given an unresolved architectural fork (which primitive, which
topology, which of several viable shapes), reads the actual code paths and
originates ONE recommendation with a named flip-condition — never reviews an
existing document. Mandatory primitive-contract read whenever a shared lock,
queue, transaction, or similar is called in nested/recursive/parallel/
re-entrant contexts.

**Tools:** `Read, Grep, Glob, Bash`, with `disallowedTools: Write, Edit, NotebookEdit` (read-only discipline, not a tool guarantee — `Bash` can mutate). **Model:** `inherit` — pass an explicit model at dispatch; `agentic-loop` Phase 2.5 routes `default` or `frontier` per Phase 2.8's table.

**Used by:** `agentic-loop` Phase 2.5 design forks.

#### `disposition-scout`

**Purpose:** Given a Phase 1 plan that retires existing code paths,
recommends clean-break or preserve-compat per retirement unit from the
actual consumers and constraints. Defaults to clean-break; preserve-compat
requires a specific named consumer that cannot migrate in this unit, plus a
removal ticket.

**Tools:** `Read, Grep, Glob, Bash`, with `disallowedTools: Write, Edit, NotebookEdit` (read-only discipline, not a tool guarantee — `Bash` can mutate). **Model:** `inherit` — pass an explicit model at dispatch; `agentic-loop` Phase 2.6 assigns its role inline per Phase 2.8's table (see `model-routing.md`'s "Inline sites elsewhere").

**Used by:** `agentic-loop` Phase 2.6 disposition decisions.

#### `docs-auditor`

**Purpose:** Runs `/sync-docs` to audit the repo's own in-tree docs
(README.md, AGENTS.md, docs/REFERENCE.md, etc.) for drift against just-merged
code, then triages findings — fixes only drift the loop's own PRs introduced,
surfaces pre-existing drift to the human rather than folding it in. Distinct
from `wiki-writer`, which maintains the external wiki vault, not in-tree docs.

**Tools:** `Read, Grep, Glob, Bash, Edit, Skill, Task`, with `disallowedTools: Write, NotebookEdit`. **Model:** `sonnet`.

**Used by:** `agentic-loop` Phase 9.

#### `preflight-scout`

**Purpose:** Runs the pre-planning skill sequence (planning-sequence,
premortem, assumptions, notchecked, wiki-query) plus a retro-intake pass over
`standing-orders.md` and recent `retro.json` files, then returns one
consolidated pre-flight report. Additive-only — never relaxes a gate, skips a
phase, or pre-justifies an eval amendment.

**Tools:** `Read, Grep, Glob, Bash, Skill`, with `disallowedTools: Write, Edit, NotebookEdit`. **Model:** `sonnet`.

**Used by:** `agentic-loop` Phase 2 pre-flight.

#### `proof-author`

**Purpose:** Writes a frozen `proof.json` from `authorising_prompt_raw`,
`session_id`, and `loop_id` — all three verbatim, handed to it as explicit
dispatch inputs, never read from `progress.json` — plus any docs the prompt
directly references. Never the plan, spec, design decisions, or dispatching
conversation. Author/grader independence for `agentic-loop` Phase 2.7e. Every
proof status stays `"pending"`; this agent never runs or scores a proof.

**Tools:** `Read, Bash, Write`, with `disallowedTools: NotebookEdit`. **Model:** `sonnet`.

**Used by:** `agentic-loop` Phase 2.7e.

#### `deploy-safety-reviewer`

**Purpose:** Reviews a PR or planned change for deploy-safety risk —
rollback risk, blast radius, deploy-time observability coverage,
migration/schema backward-compatibility, and feature-flag applicability —
and returns ONE verdict with a named risk boundary. Distinct from
`pr-review-toolkit:code-reviewer` (correctness/quality), `/security-review`
(auth/injection/secrets), and `pr-review-toolkit:silent-failure-hunter`
(swallowed exceptions, error-handling correctness) — this agent owns whether
a correct, secure, non-silently-failing change is still unsafe to deploy.

**Tools:** `Read, Grep, Glob, Bash`, with `disallowedTools: Write, Edit, NotebookEdit` (read-only discipline, not a tool guarantee, same framing as `source-auditor`/`design-scout`). **Model:** `sonnet`.

**Used by:** any change with a runtime/production surface, before merge — see
"Agents deliberately not shipped" below for why it exists alongside the
`pr-review-toolkit` review agents rather than duplicating them.

#### Agents deliberately not shipped

`pr-review-toolkit@claude-plugins-official` is already a required dependency and
already ships `code-reviewer`, `code-simplifier`, `comment-analyzer`,
`pr-test-analyzer`, `silent-failure-hunter` and `type-design-analyzer`. coderails
does not duplicate them — near-duplicate agents make dispatch ambiguous. Skills
needing code review name `pr-review-toolkit:code-reviewer` directly.

`agents/deploy-safety-reviewer.md` is not a near-duplicate of this list: it
covers deploy-safety concerns — rollback risk, blast radius, migration/schema
safety, feature-flag applicability, and deploy-time observability coverage —
that no `pr-review-toolkit` agent addresses. Its one point of potential
overlap, observability, is deliberately narrowed to the ops-visibility
question (does alerting/dashboard/runbook coverage match the change's blast
radius) and explicitly defers code-level error-handling correctness to
`silent-failure-hunter`.

---
