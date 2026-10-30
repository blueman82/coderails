# Coderails skills catalogue

[Component reference](REFERENCE.md).

## Skills

Skills are loaded by Claude via the `Skill` tool. They encode a discipline, workflow, or method. There is no automatic activation — Claude must choose to invoke a skill, guided by each skill's `description` frontmatter (which is what the harness surfaces to Claude when deciding whether to fire).

### Coderails-original skills

These skills were written for coderails and are not vendored from elsewhere.

#### `agentic-loop`

**Purpose:** Multi-agent orchestration discipline for sessions where the user has authorised autonomous work across multiple PRs or agents.

**When it triggers:** Any of: "spawn a team", "create a team", "team of agents", "no human gates", "self-merge", "autonomous", "without the human", "no per-PR confirmation", "agentic loop", "multi-PR", or 3+ PRs authorised in one instruction. Also triggers for single-PR autonomous merge+deploy+verify chains where the user has explicitly waived per-step confirmation.

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

**Graduation predicate (evaluated on every run, dormant until met):** at least 10 `retro.json` files under the repo-key dir; at least one order in the typed ledger `orders.json` whose `last_recurred` differs from its `created` date (one full lifecycle); at least one order with `status: decayed` (one clean decay), all computed by `scripts/lib/lessons.py predicate`. Every run — met or unmet — appends a line to `promotion-runs.log`; an unmet predicate then appends a `run=ok` terminal marker and stops, with no branch, no PR, no gate chain. The routine's artifact gate is a `last-marker` predicate keyed on that log's final terminal marker (`run=ok` passes; `abort=` or a stranded `delivery=started` fails).

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
