# coderails Component Reference

Catalogue of coderails skills, hooks, commands, and scripts: what it does, when it's active, when it's NOT, and dependencies. General dev-workflow skills (planning, TDD, debugging, code review, worktrees) are provided by the required `superpowers@claude-plugins-official` plugin dependency, not bundled here. Ground truth: all entries verified from source files. See README for a lighter overview.

---

## Table of Contents

1. [Skills](#skills)
   - [Coderails-original skills](#coderails-original-skills)
   - [Required plugin dependency: superpowers](#required-plugin-dependency-superpowers)
   - [Wiki skills](#wiki-skills)
   - [Engineering principles skills](#engineering-principles-skills)
2. [Agents](#agents)
3. [Hook Activation Matrix](#hook-activation-matrix)
4. [Commands](#commands)
5. [Scripts and Libraries](#scripts-and-libraries)
6. [Artifact and State Locations](#artifact-and-state-locations)

---

## Skills

Skills are loaded by Claude via the `Skill` tool. They encode a discipline, workflow, or method. There is no automatic activation — Claude must choose to invoke a skill, guided by each skill's `description` frontmatter (which is what the harness surfaces to Claude when deciding whether to fire).

### Coderails-original skills

These skills were written for coderails and are not vendored from elsewhere.

#### `agentic-loop`

**Purpose:** Multi-agent orchestration discipline for sessions where the user has authorised autonomous work across multiple PRs or agents.

**When it triggers:** Any of: "spawn a team", "create a team", "team of agents", "no human gates", "self-merge", "crack on", "without the human", "no per-PR confirmation", "agentic loop", "multi-PR", or 3+ PRs authorised in one instruction. Also triggers for single-PR autonomous merge+deploy+verify chains where the user has explicitly waived per-step confirmation.

**When it does NOT apply:** Single-PR interactive work — that is `/coderails:workflow`. The agentic loop sits _above_ `/workflow` and uses it as a subroutine.

**Key discipline:** Main context is a pure orchestrator. Every code change (even single-file edits) goes to a routed provider-native worker with explicit task instructions. The orchestrator never implements; it delegates to agents, verifies artifacts, and escalates to a spawned team only for ≥3 sequential PRs or dependency chains.

**Dependencies:** Reads and writes `progress.json` (ephemeral loop state — path computed by `hooks/scripts/lib/agentic_loop_path.py`, never manually). Invokes `superpowers:writing-plans`, `coderails:premortem`, `superpowers:brainstorming`, `coderails:handoff` as sub-skills. Interacts with `loop_state_guard` and `loop_stall_guard` Stop hooks.

---

#### `planning-sequence`

**Purpose:** Three-stage adversarial planning — Pre-Parade (success conditions), Premortem (failure modes), Red Team (adversarial challenge) — run in order on a plan, idea, or decision before committing.

**When it triggers:** "run the planning sequence", "put this through the planning techniques", "stress-test my plan", "Pre-Parade this", or before high-stakes decisions. Also proactively when a user is about to commit without adversarial planning.

**When it does NOT apply:** Forward-looking checklists, code review, or general architecture critique — those do not require backwards reasoning from an assumed failure.

---

#### `premortem`

**Purpose:** Assume a plan, decision, or approach has already failed, then reason backwards to identify failure modes and causes.

**When it triggers:** "premortem this", "steelman the failure", "what could go wrong with this plan", adversarial stress-testing of a specific commitment. Distinguishing signal is backwards reasoning from an assumed bad outcome.

**When it does NOT apply:** Forward-looking checklists ("what should I check before X"), code review, general architecture critique, fact verification.

---

#### `handoff`

**Purpose:** Generate a structured memory file and continuation prompt for carrying work into a new Claude Code session.

**When it triggers:** "handoff", "hand off", "continue in new session", "pick this up later", "save this for next session", "create a handoff", or any intent to preserve session context for future continuation. Also proactively when a session grows long and the user signals they want to wrap up and continue later.

---

#### `improve-prompt`

**Purpose:** Improve a prompt before execution by surfacing ambiguities, filling gaps with reasonable assumptions, and rewriting it for clarity and precision.

**When it triggers:** `/improve-prompt`, "improve this prompt", "what's missing from this prompt", requests to tighten a task description before running it. Also proactively when a prompt is vague, underspecified, or missing success criteria.

---

#### `task-evals`

**Purpose:** Game-resistant success-eval generation. Produces a frozen `evals.json` (scope `pr` or `loop`, verification levels 0-2) with negative controls and grader independence, so success is judged against a fixed target instead of hand-waved after the fact.

**When it triggers:** Invoked at agentic-loop Phase 2.7, at plan completion per `superpowers:writing-plans` (after stress-test, before implementation dispatch), or directly.

**Dependencies:** Consumed by `scripts/post_evals.py` (`pr` scope, merge gate) and the `loop_state_guard` hook (`loop` scope gate).

---

#### `dashboard`

**Purpose:** Live local web HUD showing sessions, agentic loops, PR gate states, runs, memory activity, and declared one-click triggers.

**Invocation:** `/coderails:dashboard` or `skills/dashboard/scripts/start_dashboard.py`.

**Run output viewer:** the COMMAND DECK's `OutputViewerPanel`
(`skills/dashboard/app/src/components/OutputViewerPanel.tsx`) shows a
run's output, selected by clicking a row in run history. A still-live run
streams via the `run-output` SSE event (`runId`, `chunk`) added to the
aggregator's event set in `skills/dashboard/app/src/lib/collect/index.ts`
and published by `skills/dashboard/app/src/lib/runOutputBus.ts` — an
in-process pub/sub, not a second SSE endpoint, so it rides the existing
single `/api/events` connection. A finished run's full output is instead
fetched once from `GET /api/run/output`
(`skills/dashboard/app/src/app/api/run/output/route.ts`), which takes
`runId` + `token` query params and returns `{status: "ok", output}`,
`{status: "in-progress"}` (409, if the
run's `endedAt` hasn't landed yet — the client should keep using the live
SSE buffer instead) or `{status: "error", error}`.

**Context Trend and the `context-trend` SSE event:** the CONTEXT TREND panel
(`skills/dashboard/app/src/components/ContextTrendPanel.tsx`) is fed by
`collectContextTrend`
(`skills/dashboard/app/src/lib/collect/contextTrend.ts`), which sweeps every
coderails orchestrator transcript under the projects dir. That sweep is far
slower than the activity slice, so it rides its **own** `context-trend` SSE
event rather than the `activity` frame — otherwise it would gate the System
Vitals KPI tiles, which must paint as soon as their own collect resolves.

Adding a new SSE event means wiring **two** places, and they fail differently
— which is worth knowing before you debug one:

- `src/lib/collect/index.ts` — the `AggregatorEventName` union, the
  `AggregatorEventPayloadMap` entry, and the overloaded `emit`/listener
  signatures. Miss one and it is a **compile error**: the overloads exist so a
  mismatched event/payload pairing cannot type-check.
- `src/hooks/useDashboardState.ts` — the `DashboardEvent` union, a
  `mergeDashboardEvent` case, and the `SSE_EVENT_NAMES` array. That array is
  the **silent** one: the `for (const name of SSE_EVENT_NAMES)` loop is what
  registers each `addEventListener`, so a name missing from it means the
  browser receives the frame, no handler fires, and nothing errors. Only the
  hook-level wiring test catches it — a `mergeDashboardEvent` unit test cannot,
  because it bypasses the registration entirely.

`src/app/api/events/route.ts` needs **no** per-event change: its subscribe
callback forwards any `{event, data}` through an event-name-agnostic
`sseFrame`, with no per-event branch. It does hold
`sharedContextTrendCache`, but that is contextTrend-specific performance
plumbing (stat-only revalidation across connections) — omitting it forfeits
caching, it never drops a frame.

`Snapshot.contextTrend` is **tri-state**, and each state renders differently:
`undefined` means the frame has not arrived yet (the panel shows "loading…"),
`null` means the source was unreadable (the panel shows "unavailable"), and a
summary object is data. Collapsing `undefined` and `null` makes the panel
flash "unavailable" on every page load — the same regression PR #265 removed
for the KPI tiles, where `healthNotYetLoaded` in `RailLeft.tsx` distinguishes
"the collect has not resolved yet" from "the collector tried and could not
populate this tile".

**Per-connection teardown:** `/api/events` releases its aggregator from the
request's `abort` signal as well as `ReadableStream.cancel()`, plus an
`if (request.signal?.aborted)` re-check after setup. `cancel()` alone fires
only when the response *consumer* cancels — a client that simply goes away
does not reliably trigger it, and each abandoned connection then leaked a
recursive `fs.watch` handle per watched dir plus the gates interval. That is
fatal under launchd, which caps the process at `launchctl limit maxfiles`
(256 on stock macOS) rather than the shell's soft limit: once exhausted the
server still accepts TCP but serves nothing.

---

#### `workflow-audit`

**Purpose:** Mines Claude Code session transcripts for tool-use patterns that repeat across sessions, judges which ones are genuine candidates for a new skill, and — only after explicit owner approval — creates each approved skill through the normal `superpowers:writing-skills` TDD process and a full PR gate.

**When it triggers:** "look at our last N sessions and pull out repeated tasks", "what do I do repeatedly that isn't a skill yet", "audit my workflows", "mine my transcripts for skill candidates", "turn my repeated tasks into skills".

**Pipeline:** `skills/workflow-audit/scripts/scan_transcripts.py` (transcripts → per-session tool-use event sequences) pipes into `skills/workflow-audit/scripts/cluster_ngrams.py` (event sequences → recurring n-gram clusters across `--min-sessions` distinct sessions), then a fresh sonnet subagent applies `references/judge-contract.md` to each cluster for a propose/reject verdict. Proposed candidates are charted for the owner; nothing is created without an explicit approval in that interaction — this gate overrides any standing agentic-loop autonomy.

**Queue-mode output (optional):** each `verdict: "propose"` judge output can additionally be piped through `skills/workflow-audit/scripts/write_queue_entry.py` to surface it on the observability dashboard, writing into `~/.claude/coderails-dashboard/approvals/` (routines' own scheduler intents live in the sibling `queue/` directory — see `docs/routines.md`). This is additive to, never a replacement for, the interactive approval gate — a dashboard "Approve" click only flips a queue entry's `status` from `pending` to `approved`.

**Approve-click build runner:** flipping a `workflow-audit:propose-skill` entry to `approved` makes the dashboard's `POST /api/queue` route claim a build directory and spawn a detached, headless `claude -p` build (`skills/dashboard/app/src/lib/build/spawn.ts`, running `skills/dashboard/scripts/run_builder.py` and prompted via `skills/dashboard/app/src/lib/build/prompt.ts`) that authors the proposed skill through skill-creator and ships it as a coderails PR through the full gate sequence. The builder never merges — its terminal state is an open PR with gates green, surfaced on the dashboard (`skills/dashboard/app/src/lib/collect/builds.ts`); the owner reviews and merges by hand. While the build runs, the panel shows a coarse builder-reported phase (`authoring`/`testing`/`pushing`/`opening_pr`, closed-set-validated in the collector before reaching the client), an elapsed timer, and heartbeat freshness rather than an opaque "building"; once the build's PR leaves the dashboard's open-PR set it shows "PR resolved" instead of a stale "awaiting your merge" (skipped whenever the open-PR set is untrustworthy, so an open PR is never falsely marked resolved). **First skill built end-to-end by this runner:** `verify-merged-pr` (below).

**Privacy invariant:** every artifact in the pipeline — scan output, cluster output, judge input/output, proposal chart, queue entry — carries only tool names, a privacy-whitelisted `head` (first two Bash command tokens, the Skill name, or the Agent subagent_type), counts, and session ids. Never verbatim transcript prose, file contents, or reconstructed intent.

**When it does NOT apply:** it never creates a skill without the interactive approval gate; the mechanical scan+cluster+queue-write pipeline has no skill-creation capability at all, the judge stage only proposes, and the build runner only triggers on an explicit owner Approve click — it is not autonomous.

---

#### `verify-merged-pr`

**Purpose:** Re-derives a "PR #N is merged" claim from the tools before you rely on it — independently confirming the merge **state** (`gh pr view`), the **content** on `origin/main` (fetch + `git merge-base --is-ancestor` + `git grep`), and the **sibling PRs** that landed in the same author/time window. The sibling check is the one agents skip: a reporter names one PR, but a session often lands several.

**When it triggers:** an agent / teammate / CI report / session summary says a PR is merged, shipped, live, or landed; you are about to build on, deploy, or hand off work that depends on the merge being real; a headless builder or loop reports "done — PR merged" with one PR number.

**When it does NOT apply:** you performed the merge yourself this session and watched it complete, or the claim is about an open/draft PR (nothing merged to verify).

**Provenance:** the first skill authored end-to-end by the dashboard Approve→build runner (above) — a `workflow-audit` proposal, Approved on the dashboard, built by a headless `skill-creator` session, and merged by hand.

---

#### `cite-check`

**Purpose:** Re-derives a stated claim from durable sources only — file contents, git output, and fresh command output — and returns a sourced PASS / FAIL / UNSUPPORTED verdict per claim. No recall, no inference.

**How it runs:** `context: fork` with `agent: coderails:source-auditor` and `background: false`. The fork is the point: an audit that runs in the context which produced the claim is self-verification, since the same reasoning that made the error is available to excuse it. The forked auditor sees only the claim text passed via `$ARGUMENTS`.

**When it triggers:** invoked directly as `/coderails:cite-check <claim>`; also named by `agentic-loop` Phase 5, which applies it to the single claim "this bug currently reproduces" before spawning any fix.

**Naming:** called `cite-check` rather than `verify` because `/verify` is a Claude Code **bundled** skill (build and run your app to confirm a change). A project skill of the same name overrides the bundled one, which would silently shadow a built-in with an unrelated meaning.

**Dependencies:** the `coderails:source-auditor` agent.

---

#### `execution-discipline`

**Purpose:** Establishes working habits for specify-before-start, high autonomy, first-shot correctness, instruction retention over long sessions, and rigorous self-verification.

**When it triggers:** Any non-trivial task — multi-step work, anything involving files or tool calls, analysis, building something, debugging, research, document creation, or long-running work. Applied before starting work, not after, since it changes how the work is done.

**When it does NOT apply:** Trivial single-step responses with no tool use or file involvement.

---

#### `sync-docs`

**Purpose:** Analyzes any codebase and its documentation to identify drift and generate actionable sync reports. Enhanced with Serena for semantic code discovery — an optional `--semantic` flag adds AI-powered undocumented-code discovery on top of the mechanical diff.

**When it triggers:** "sync docs", "check documentation", "documentation drift", "doc audit", explicit `/sync-docs`.

**Invocation modes:** `/sync-docs` (full drift report), `/sync-docs --check` (drift report only, no suggestions), `/sync-docs --suggest-updates` (includes proposed markdown for updates), `/sync-docs --semantic` (Serena-powered deep code discovery), `/sync-docs --compare <section>` (deep-dive analysis of a specific section), `/sync-docs --verbose` (includes detailed file references), `/sync-docs --diagrams-only` (audits only `docs/diagrams/`).

---

#### `memory-consolidation`

**Purpose:** Health-checks and consolidates a project's persistent memory directory (`~/.claude/projects/<slug>/memory/`) — dedupes overlapping memories, flags stale or contradicted ones (without silently deleting `feedback`-type memories), and refreshes the `MEMORY.md` index.

**When it triggers:** "consolidate memory", "clean up memory", "memory consolidation", or when running as a scheduled routine (weekly, via the `routines` section of `~/.claude/coderails-dashboard.json`). Also runs standalone on demand.

**Dependencies:** Writes a durable report artifact to `~/.claude/coderails-dashboard/routines/memory-consolidation/report-{date}.md`, unconditionally — the property a scheduled routine's artifact-gate checks.

---

#### `docs-sync`

**Purpose:** Scheduled nightly pipeline (not for interactive use) that audits this repo's git-tracked documentation for drift against the actual codebase and — only if drift is found — edits, pushes, reviews and self-merges the fix with no human in the loop. Invokes `sync-docs`'s audit as its first step; distinct from that skill, which does the audit alone and is the right entry point for an interactive drift check.

**When it triggers:** Only as the scheduled `sync-docs-nightly` routine (see `docs/routines.md`). It replaced `sync-docs-weekly`, which was read-only (report-only) and had been dead since 2026-07-15 — its `foreignSkillPath` pointed at a path that never existed. An in-repo skill needs no `foreignSkillPath`, so there is no path left to rot.

**No-drift short-circuit:** if the audit finds nothing to fix, the routine appends a `no-drift` line to its run log, then appends a `run=ok` terminal marker, and exits 0 — no branch, no PR. That run log is the routine's `expectedArtifact`, gated by a `last-marker` predicate: the `run=ok` marker is what passes it, so a quiet night still satisfies the gate rather than reading as dead. There is no separate report file on a no-drift night. Most nights take this path.

**Delivery (only when drift is found):** full gate chain, manifest-locked — `task-evals` (pr scope) frozen before the edit, `/coderails:push`, `/pr-review-toolkit:review-pr`, `/coderails:post-review`, `/coderails:post-evals`, `/coderails:merge`. The manifest assertion reads `git diff origin/main...HEAD --name-status` (never `--name-only`, which prints a rename as its destination alone and cannot distinguish a deletion from an edit) and aborts with cleanup unless every path is a git-tracked `.md`, no path is on the self-governance deny-list, no rename's source was out of scope, and no in-scope doc is deleted.

**Self-governance deny-list:** `skills/**/SKILL.md` (including its own), `AGENTS.md`, `CLAUDE.md`, `docs/routines.md`, anything under `.claude/`, `examples/dashboard-config.json`. These are the documents that define what the routine may do; drift against them is reported and escalated to a human, never fixed by the routine. The deny-list is what makes that enforceable rather than merely stated: the first four are themselves `.md`, so the manifest's `.md`-only rule would happily pass them — naming them explicitly is the only thing that stops the routine editing its own contract. The last two are already caught by the non-`.md` rule and are listed anyway, so the deny-list reads as complete on its own rather than depending on a rule stated elsewhere.

**Dependencies:** the second routine in this repo to use a `bypass` button profile — `PreToolUse` hooks do not fire under `claude -p`, so `scripts/merge.py`'s own artifact gates are the merge rail. Honest boundary: the deny-list and every manifest condition are prompt-enforced, not hook-enforced; they narrow the blast radius (capped at `.md`) rather than mechanically closing it. See `docs/routines.md` for the full contract and security note.

---

#### `loop-retro-promotion`

**Purpose:** Predicate-dormant pipeline (scheduled, not for interactive use) that mines accumulated `retro.json` files and the `standing-orders.md` overlay for repo-agnostic lessons and promotes them into `skills/agentic-loop/learned-failure-modes.md`.

**When it triggers:** Only as the scheduled `loop-retro-promotion-weekly` routine (see `docs/routines.md`) — never for a single loop's retro and never from inside an active agentic-loop session.

**Graduation predicate (evaluated on every run, dormant until met):** at least 10 `retro.json` files under the repo-key dir; at least one `standing-orders.md` entry whose `last_recurred` differs from its `created` date (one full lifecycle); at least one `standing-orders-decayed.md` entry (one clean decay). Every run — met or unmet — appends a line to `promotion-runs.log`; an unmet predicate then appends a `run=ok` terminal marker and stops, with no branch, no PR, no gate chain. The routine's artifact gate is a `last-marker` predicate keyed on that log's final terminal marker (`run=ok` passes; `abort=` or a stranded `delivery=started` fails).

**Delivery (once graduated):** full gate chain, manifest-locked to exactly `skills/agentic-loop/learned-failure-modes.md` — `task-evals` (pr scope) frozen before the edit, `/coderails:push`, `/pr-review-toolkit:review-pr`, `/coderails:post-review`, `/coderails:post-evals`, `/coderails:merge`. Any other file in the diff aborts with cleanup (closes the PR, deletes the branch, logs the abort).

**Dependencies:** Its routine, `loop-retro-promotion-weekly`, is the first routine in this repo to use a non-read-only button profile (`bypass`) — `PreToolUse` hooks do not fire under that execution mode, so `scripts/merge.py`'s own artifact gates are the only merge rail once the predicate graduates. See `docs/routines.md` for the full routine contract and security note.

---

#### `using-coderails`

**Purpose:** Establishes how to find and use skills at session start. Requires skill invocation before ANY response including clarifying questions.

**When it triggers:** When starting any conversation. Also injected automatically at every session start by the `inject_bootstrap.py` `SessionStart` hook — Claude receives the full SKILL.md content as context so it can self-bootstrap without being told.

---

### Required plugin dependency: superpowers

These are general development-discipline skills (not coderails-specific
workflow). coderails no longer bundles them — they are provided by the
required `superpowers@claude-plugins-official` plugin (see
[Requirements](../README.md#requirements)/[INSTALLATION.md](../INSTALLATION.md)).
Without that plugin installed, the skill names below resolve to nothing.

| Skill | Purpose |
|---|---|
| `superpowers:brainstorming` | Explores user intent, requirements, and design before implementation. Required before any creative work |
| `superpowers:writing-plans` | Turns a resolved spec into an ordered set of self-contained implementation tasks, each with exact files, interfaces, bite-sized steps, and verify-criteria |
| `superpowers:subagent-driven-development` | Executes implementation plans with independent tasks in the current session using sub-agents |
| `superpowers:dispatching-parallel-agents` | Dispatches 2+ independent tasks to parallel agents to avoid sequential bottlenecks |
| `superpowers:executing-plans` | Executes a written implementation plan in a separate session with review checkpoints |
| `superpowers:using-git-worktrees` | Ensures an isolated workspace exists via native tools or git worktree fallback before feature work |
| `superpowers:requesting-code-review` | Guides the code review request process to ensure work is complete and requirements are met |
| `superpowers:receiving-code-review` | Ensures code review feedback is handled with technical rigor and verification, not performative agreement or blind implementation |
| `superpowers:finishing-a-development-branch` | Presents structured options (merge, PR, cleanup) for integrating completed work when implementation is done and all tests pass |
| `superpowers:systematic-debugging` | Structured debugging approach before proposing fixes for bugs, test failures, or unexpected behaviour |
| `superpowers:test-driven-development` | Red-green-refactor discipline: write the failing test first, watch it fail for the right reason, write minimal code to pass, refactor |
| `superpowers:verification-before-completion` | Runs verification commands and confirms output before making any success claims. Evidence before assertions |
| `superpowers:writing-skills` | Guidance for creating new skills, editing existing skills, or verifying skills work before deployment |

After the self-review gate, a `superpowers:writing-plans` plan goes through
`/coderails:planning-sequence` (Pre-Parade → Premortem → Red Team) before
implementation hands off to `superpowers:subagent-driven-development`/
`superpowers:executing-plans`. Plan storage: `docs/coderails/plans/` is
gitignored — plans are session-local working documents, never tracked in the
repo (owner decision, 2026-07-11). The agentic loop's `plan.md` is a special
case — it lives in the loop-state dir outside the repo alongside
`progress.json`, same treatment.

---

### Wiki skills

These skills manage the LLM Wiki — a persistent, compounding knowledge base maintained by Claude and browsable in Obsidian.

#### `wiki-init`

**Purpose:** Initialize an LLM Wiki for the current project.

**When it triggers:** "wiki init", "create wiki", "knowledge base", "set up obsidian wiki", explicit `/wiki-init`. Also when the user mentions Karpathy's LLM Wiki pattern, AGENTS.md, or wants to organise project knowledge beyond CLAUDE.md.

**When it does NOT apply:** When a wiki already exists and the user wants to query or update it.

---

#### `wiki-ingest`

**Purpose:** Create or update wiki pages to document a merged PR, shipped feature, or engineering decision.

**When it triggers:** "ingest this", "create wiki pages for this PR", "add to wiki", "document this in the wiki", "capture this change", "file this in the wiki". The user always has a concrete artifact to record.

**When it does NOT apply:** General knowledge lookup — use `wiki-query` for that.

---

#### `wiki-lint`

**Purpose:** Audit the quality and structural integrity of the project's LLM Wiki — find contradictions, stale pages, orphaned pages, dead links, missing cross-references, coverage gaps.

**When it triggers:** "wiki-lint", "lint the wiki", "wiki health check", find contradictions or stale content, detect orphaned pages.

**When it does NOT apply:** When the user wants to look up what the wiki says about a topic — use `wiki-query`.

---

#### `wiki-query`

**Purpose:** Search, query, or look up information in the project's LLM Wiki. Can also generate Marp slides or matplotlib charts drawing on wiki knowledge.

**When it triggers:** "search wiki", "query wiki", "ask the wiki", "what does the wiki say", requests to find project-specific answers grounded in wiki content.

**When it does NOT apply:** General coding questions unrelated to wiki content, wiki maintenance tasks (adding, filing, ingesting, linting), wiki initialisation.

---

### Engineering principles skills

These skills enforce engineering principles and language-specific coding standards on code being written or modified.

#### `engineering-principles`

**Purpose:** Enforce engineering principles (YAGNI, KISS, DRY, Fail Fast, SSOT, Law of Demeter) and language-specific coding standards across Python, Go, TypeScript, and Bash. Uses LSP (Serena) for call site analysis and reference counting. Dispatches to the appropriate language sub-skill after detecting the file extension (or, for extensionless files, the shebang line).

**When it triggers:** Proactively after writing or modifying any code file, or explicitly via `/engineering-principles`. Trigger phrases: "enforce standards", "check principles", "apply standards", "code quality".

**When it does NOT apply:** Docs, config, or prose edits with no code to audit.

---

#### `engineering-principles-python`

**Purpose:** Enforce Python idioms and standards on `.py` files — PEP 8 naming, type hints, EAFP over LBYL, context managers, and Pyright strict compliance.

**When it triggers:** Invoked by `engineering-principles` after detecting `.py` files, or directly for Python-only sessions.

---

#### `engineering-principles-go`

**Purpose:** Enforce Go idioms and standards on `.go` files — accept interfaces/return structs, errors-as-values, table-driven tests, and idiomatic naming.

**When it triggers:** Invoked by `engineering-principles` after detecting `.go` files, or directly for Go-only sessions.

---

#### `engineering-principles-ts`

**Purpose:** Enforce TypeScript idioms and standards on `.ts`/`.tsx` files — strict mode, no `any`, discriminated unions, optional chaining, and exhaustive switch checks.

**When it triggers:** Invoked by `engineering-principles` after detecting `.ts`/`.tsx` files, or directly for TypeScript-only sessions.

---

#### `engineering-principles-bash`

**Purpose:** Enforce Bash/shell idioms and standards on `.sh` files — the `set -euo pipefail` safety header and its documented exceptions (sourced libraries, degrade-gracefully hooks), quoting discipline, `[[ ]]` over `[ ]`, avoiding `eval`/word-splitting/unquoted globs, `local`-scoping and the command-substitution-subshell footgun, `namespace::function` decomposition, and shellcheck-clean patterns.

**When it triggers:** Invoked by `engineering-principles` after detecting `.sh` files (or an extensionless file with a `bash`/`sh` shebang), or directly for shell-only sessions.

---

## Agents

Subagent definitions in `agents/`, auto-discovered when the plugin is enabled and
referenced by their namespaced name (`coderails:<name>`). Skills dispatch these
by name instead of pasting a prompt into a `general-purpose` subagent: the model
and tool set travel with the definition, so they survive even if the dispatching
prose is ignored.

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

## Hook Activation Matrix

The authoritative event map is [AGENTS.md](../AGENTS.md#hook-event-map-hookshooksjson),
with exact registrations in [hooks.json](../hooks/hooks.json). Claude hooks and
Codex hooks are independently installed Python entrypoints. Stop denials exit 2;
PreToolUse denials return native permission JSON with exit 0. Payload reads have
a five-second deadline, including partially written input. Test-gate output is
retained in full; failure notices provide measurements and a reader command
instead of a fixed excerpt (see below).

Local hooks redirect and audit a cooperating agent. Their files and transcripts
remain inside the local trust domain. The root-owned integrity attestor and
GitHub required status provide the separate server-side boundary described in
[INTEGRITY-GATE.md](INTEGRITY-GATE.md).

### Retained test-gate output

Each configured test-command execution is one **run**, which may contain many
individual tests. Both providers execute their configured first line through
`/bin/bash -c`, preserving their existing command trust rules. Claude reads
`.claude/test_command`; Codex reads the worktree's trusted Git-internal
`coderails/test_command`. Passing commands still allow the commit. Failing
commands deny it and return the run identity, byte/line measurements, full log
path and a quoted reader command. An unknown platform output budget does not
justify an automatically selected tail or byte cap.

Every run, including passing and empty-output runs, captures combined stdout and
stderr bytes unchanged in a unique directory:
`~/.coderails/test-output/<provider>/<project-command-hash>/<run-id>/output.log`.
Completed logs rotate to `output.log.gz` automatically; active logs stay untouched.
Compression preserves all captured bytes, and the reader transparently handles it.
The sibling `run.json` records the run identity, provider, project, command,
exit status and measurements. `CODERAILS_TEST_OUTPUT_DIR` overrides the storage
root. A 1 GiB compressed-log budget applies across that storage root by default; set
`CODERAILS_TEST_LOG_BUDGET_BYTES` to choose another byte budget. Oldest completed
logs expire first. Active runs, logs being completed or read, and the cleanup
caller's current run are protected. File locks release automatically if a process
exits; later cleanup can expire previously protected completed logs. Therefore
retained content can exceed the budget; `run.json` records
`retention.remaining_compressed_bytes` and `retention.over_budget`.
Compact run metadata, retrieval metrics and delivery observations persist
separately, together with `retention.json` expiry records when log content is
removed. The budget governs compressed logs, not these records or active raw
output. A metadata-only notification does not itself mean the log is empty or
expired.
An expired log read fails explicitly; its retained metadata remains available
in `run.json`, request records and `retention.json`.

One canonical helper is copied byte-for-byte into each independent provider
installation. Use the helper from the same installation as the hook. In this source
checkout it is `hooks/scripts/test_output.py` for Claude and
`packages/codex/hooks/scripts/test_output.py` for Codex. Replace the quoted run
directory below with the directory reported by the denial. The examples use
the Claude helper; substitute the Codex path when appropriate.

```sh
python3 hooks/scripts/test_output.py read "/path/to/run-directory" --all
python3 hooks/scripts/test_output.py read "/path/to/run-directory" --start 2 --end 12
python3 hooks/scripts/test_output.py read "/path/to/run-directory" --search "AssertionError" --before 3 --after 5
python3 hooks/scripts/test_output.py read "/path/to/run-directory"
```

Line ranges are one-based and inclusive. Search is literal, with caller-chosen
context; it does not guess a framework's failure syntax. Full, range and search
reads return JSON with the text, selected source ranges, source/text byte
measurements, omitted line count and `policy_truncated: false`. Intentional
selection can omit content without policy truncation. Decoding for JSON text
can change its byte count, especially for invalid UTF-8; the captured bytes in
the retained log remain authoritative until retention expires its content.

Without selection flags, the reader always returns metadata and request
guidance only, including after earlier explicit reads. Adaptation is the
agent's demand-driven expansion of requests: inspect a literal match, request
more context, or read everything as needed. There is no automatic prediction
from prior runs' line positions, which can change between runs. Compact
measurements make retrieval auditable; neither fewer requests nor absence of
follow-ups proves diagnostic sufficiency or an optimal policy.

Each reader request writes a unique compact record of its selection,
requested and returned measurements, and emitted response bytes, without
duplicating the selected log text in the record. Emission is not proof
that a model received those bytes: delivery starts as unknown. To attach an
actual downstream observation to the exact request record, use:

```sh
python3 hooks/scripts/test_output.py observe "/path/to/request-file" --delivered-bytes 420 --truncated yes --source "reported tool transport observation"
```

Replace the example measurements with observed values; do not infer them from
file size or reader success. Observations are stored separately from request
measurements. Reading `output.log` with `cat` or a file-read tool bypasses this
telemetry and is **unobserved**, not zero delivery. Failed retrievals do not
remove the retained log. Disposable local fixtures can exercise these hooks
and readers without installed provider accounts.

### Hook library files

| Module | Responsibility |
|---|---|
| `hooks/scripts/hook_common.py` | Bounded payload reads and native hook responses. |
| `hooks/scripts/lib/agentic_loop_path.py` | Resolve the repository/session-owned loop state path. |
| `hooks/scripts/lib/discipline_common.py` | Read native Claude transcript tools, final text and edited-file count. |
| `hooks/scripts/lib/loop_state_common.py` | Loop detection, ownership, atomic state update behind the `dir_lock` mkdir lock; live completion marker. |
| `hooks/scripts/lib/dir_lock.py` | Stdlib-only mkdir lock with owner pid and start time; steals a dead owner's lock atomically (see `docs/graph-alignment-measurement.md`, stale-lock policy). |
| `hooks/scripts/lib/loop_evals.py` | Frozen dispatch authority and checksum-bound neutral completion verdicts. |
| `hooks/scripts/lib/loop_completion.py`, `loop_proofs.py`, `loop_cost.py` | Independent work-unit, retrospective, observed proof execution and dated cost checks. |
| `hooks/scripts/lib/graph_executor.py` | Provider-local lock around the installed pure schema-3 semantic operations. |
| `hooks/scripts/lib/graph_dispatch.py` | Current native ownership envelopes, instruction-source plan, wave collection and completion artifact gates. |
| `hooks/scripts/lib/graph_evidence.py` | Actual parent requests/results, confined native transcript paths, child attribution and genuine harness notifications. |
| `hooks/scripts/lib/graph_evidence_bind.py`, `graph_evidence_revalidate.py` | Derive and revalidate all native child identities and attempts; reject caller provenance, reused children and echoed completion. |

The sole maintained pure semantics are `packages/graph-semantics/graph_semantics.py`.
The installer materializes exact copies into each provider. Each adapter retains
its own dispatch, transcript, lock and artifact behavior. There are no schema-2
readers or shell fallback writers. See
[execution-graph.md](../skills/agentic-loop/execution-graph.md) for native CLI
commands, whole-wave collection and retry/respawn rules. Graph IDs identify work;
provider-native labels identify workers. Explicit worker instructions travel in
the prompt. `work_units` remains independent of `graph.nodes`.

## Commands

Commands are slash commands invoked by Claude (or the user via `/coderails:<name>`). They encode workflow logic but are **advisory** — Claude must choose to invoke them. Unlike hooks, commands cannot self-enforce.

| Command | Description | Key dependencies |
|---|---|---|
| `/coderails:workflow` | Orchestrate the full feature workflow: `prep → code → push → review → merge → wiki-ingest → wiki-lint`. Two interactive pauses: the code/iterate loop, and final ship-it authorisation. | Delegates to all other commands; reads `workflow.config.yaml`; requires `pr-review-toolkit` plugin for the review stage |
| `/coderails:prep` | Create a safety branch, a feature/bug branch, and optionally a Jira ticket. | `git worktree`, Jira MCP (optional — skips if `config.jira` is null or no Jira MCP); reads `workflow.config.yaml` |
| `/coderails:push` | Stage, commit, push changes, and create a PR. Runs an engineering-principles pre-flight if `config.engineering_principles_paths` is set. | Shells out to `scripts/push.py`; requires a GitHub remote; reads `workflow.config.yaml` |
| `/coderails:post-review` | Post the SHA-bound review artifact as a GitHub PR comment. Validates the review summary structure, then posts a machine-marked comment. The `/merge` gate requires this artifact for the current head SHA — fail-closed. | Shells out to `scripts/post_review.py`; runs the Python review marker CLI; uses `gh api` (not `gh pr comment`) to capture the returned comment URL; best-effort cache write to `progress.json` if it exists |
| `/coderails:post-evals` | Validate and post the SHA-bound eval-artifact summary as a GitHub PR comment. Consumes the `evals.json` produced by `/coderails:task-evals` for this PR, computes `GO`/`NO-GO` (never hand-written), and posts a machine-marked comment. The `/merge` gate requires this artifact for the current head SHA — fail-closed, additive to the review-artifact gate. | Shells out to `scripts/post_evals.py`; runs the Python eval marker CLI |
| `/coderails:merge` | Merge an approved PR, switch to main, and pull latest. Requires a coderails review artifact AND a coderails eval artifact on the PR for the current head SHA before merging, and — where the repo config activates it (`wiki_debt_epoch_pr` + `wiki_path`) — a wiki-ingest debt check (`has_wiki_ingest_for_merged_prs`) that greps the wiki vault's `origin/main` for coverage of every PR merged after the epoch. | Shells out to `scripts/merge.py`; requires GitHub remote; checks PR approval if branch protection is on; fetches live PR comments for both the review-artifact gate and the eval-artifact gate |
| `/coderails:init` | Scaffold or migrate a `workflow.config.yaml` for the current project. Writes to `$(pwd)/.coderails/` (resolved by walk-up — see Config resolution). | `git rev-parse`, Write tool; confirms before overwriting |
| `/coderails:test-gate-setup` | Configure the test gate for the current project. Detects the test runner (npm, cargo, pytest, go test, etc.) and writes `.claude/test_command`. | Write tool; opt-in gate for `test_gate.py` hook |
| `/coderails:assumptions` | List every assumption currently being made (task, codebase, environment, state), marked `(verified)` or `(inferred)`. Pure inventory — does no other work. | None |
| `/coderails:disconfirm` | Argue against the most recent recommendation — find the strongest case it is wrong. Steelmans the opposition. | None |
| `/coderails:cite-check` (skill at `skills/cite-check/`, not a `commands/` file) | Re-derive a specific claim from durable sources only (file contents, git output, fresh command output). No recall, no inference. Runs `context: fork` into `coderails:source-auditor` with `background: false`, so the audit has no access to the conversation that produced the claim — verifying inside that context would be self-verification. Named `cite-check` rather than `verify` because `/verify` is a Claude Code bundled skill and a same-named project skill would override it. | `coderails:source-auditor` agent |
| `/coderails:notchecked` | Review recent responses and list every non-trivial claim that was NOT verified. Surface gaps ruthlessly. | None |

### Config resolution (`workflow`, `prep`, and `push`) and init scope

Command frontmatter runs `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lib/config.py" resolve-config`.
The same `config_path(start_dir)` implementation is imported by workflow gates:
walk toward the Git root, choose the nearest `.coderails/workflow.config.yaml`,
and emit `NO_CONFIG` when absent. No legacy runtime fallback or config merging
occurs. Init validates preserved configuration before moving legacy files to
Trash; it never silently overwrites user values.

## Scripts and Libraries

| Entrypoint/module | Responsibility |
|---|---|
| `scripts/push.py`, `merge.py` | Explicit staging/commit/PR workflow and current-head review, eval, integrity and wiki-debt merge gates. |
| `scripts/post_review.py`, `post_evals.py` | Review grammar/cache, structural eval validation, neutral grading and observed smoke execution. |
| `scripts/external_enforcement.py`, `ci_verify.py`, `enforcement_trace.py` | Opt-in, inert-by-default external enforcement: ruleset `plan`/`apply --yes`, an independent-runner verifier reusing the merge-gate functions, and advisory trace rows/counters. See `docs/external-enforcement/README.md`. |
| `scripts/lib/git_common.py` | GitHub repository/PR operations and newest trusted exact-head artifact selection. Requires a `github.com` remote. |
| `scripts/lib/{config,review_artifact,eval_artifact,artifact_io}.py` | Shared root-provider config and structured artifact operations. |
| `scripts/lib/{eval_validation,eval_execution}.py` | Eval criteria and command/control verification. Gate smoke runs in a detached worktree at the trusted SHA. |
| `scripts/sandbox/spawn_sandboxed_worker.py` | Guard dispatch before scratch allocation; run a separate Claude process through pinned srt and retain its exit status. |
| `scripts/sandbox/{render_settings,sandbox_probe}.py` | Render explicit write containment and discriminate allowed versus forbidden filesystem writes. |
| `scripts/integrity-gate/integrity_gate_runner.py` | Root-owned mechanical review/eval/diff attestation; no LLM classifier. Deployed with its root-owned HTTP and policy modules. |
| `scripts/integrity-gate/{install,setup}.py` | Reviewable owner-run promotion, credential handling and GitHub ruleset setup. |
| `install.py`, `uninstall.py` | Independent provider installation/removal with preserved user data, preflight checks and read-only dry-run. |
| `launchd/*_routines.py`, `*_dashboard_agent.py` | Literal-path launch agent installation and verified unload/removal. |
| `scripts/quality/check.py` | Strict source, format, typing, size and generated-materialization checks. |
| `hooks/scripts/tests/run_all.py` | Native Python suite discovery with explicit skips and all-skipped failure. |

## Artifact and State Locations

| Artifact | Location | Committed? | Notes |
|---|---|---|---|
| `workflow.config.yaml` | first `.coderails/workflow.config.yaml` found walking from cwd up to git root (`$(pwd)/.coderails/` for `/init`) | No — local project setup, ignored by Git | Project-specific config for jira, wiki, worktree, engineering-principles, and sandbox workers. Created or migrated by `/coderails:init`; share its values through your normal project configuration process. |
| `.claude/test_command` | Project working directory | Yes (project-local) | Plain-text file containing the test command. Created by `/coderails:test-gate-setup`. Activates `test_gate.py`. |
| Codex `coderails/test_command` | Worktree Git metadata, resolved by `git rev-parse --git-path coderails/test_command` | No | Trusted native Codex test-gate command; a workspace file cannot configure it. |
| Test-gate runs and reader records | `~/.coderails/test-output/` or `CODERAILS_TEST_OUTPUT_DIR` | No | Completed logs automatically rotate and compress; active logs stay untouched. Run metadata, retrieval records and reported delivery observations persist separately. |
| Specs from brainstorming | Session-local scratch path (`docs/coderails/specs/` is gitignored) | No — ephemeral, never tracked | Written by `superpowers:brainstorming` after design resolution. Owner decision 2026-07-11: use `coderails:handoff` or a wiki page for a durable record instead. |
| Plans from writing-plans | Session-local scratch path (`docs/coderails/plans/` is gitignored) | No — ephemeral, never tracked | Written by `superpowers:writing-plans`. Same owner decision, 2026-07-11. |
| Agentic loop `progress.json` | `~/.coderails/agentic-loop/<repo-or-cwd-slug>/<session_id>/progress.json` | No — ephemeral loop state, outside the repo | Dynamic position tracker for the loop. Path computed by `agentic_loop_path.py` — keyed to the repo (shared across its worktrees) when cwd is inside a git repo, falling back to cwd otherwise. Session-keyed. When the canonical slug has no file, the helper probes `<base>/*/<session_id>/progress.json` so state written under a different slug (older helper version, mid-loop cwd drift) is still found by session_id. |
| Agentic loop `spec.md` | Same dir as `progress.json` | No — ephemeral loop state | Written by the agentic-loop orchestrator for ≥3-unit loops. Not a PR deliverable. |
| Agentic loop `plan.md` | Same dir as `progress.json` | No — ephemeral loop state | Written by `superpowers:writing-plans` as invoked by the agentic-loop. Consumed, not write-only: the orchestrator re-reads it after compaction to recover scope. |
| `evals.json` (pr scope) | Working material only — no fixed path; wherever the invoking workflow placed it (e.g. current working tree or a path named in the worker prompt) | No — the durable artifact is the SHA-bound `coderails-eval-summary` PR comment, not this file | Generated and frozen per PR; validated and posted by `/coderails:post-evals` via `scripts/post_evals.py` + `scripts/lib/eval_artifact.py`. |
| `evals.json` (loop scope) | Same dir as `progress.json` | No — ephemeral loop state | Read by the `loop_state_guard.py` hook when `progress.json`'s `work_units` ≥ 1; blocks `Stop` if absent. |
| Discipline log | `~/.claude/discipline.log` (or `$CLAUDE_DISCIPLINE_LOG`) | No | Structured `key=value` log appended by hooks on every fire. Never committed. |
| LLM Wiki vault | `config.wiki_path` (set in `workflow.config.yaml`) | Separate repo/vault | Maintained by `wiki-ingest`, `wiki-lint`, `wiki-query`. Browsed in Obsidian. |

### The ephemeral vs committed boundary

The loop's `spec.md`, `plan.md`, and `progress.json` live in `~/.coderails/agentic-loop/` — **outside** the code repo and Claude's configuration tree. They are loop state keyed to this orchestrator run, not shareable design records. If work needs handing to a human, `coderails:handoff` is the right tool. Durable records belong in the wiki or an explicitly authorized repository document, not these session-local scratch files.
