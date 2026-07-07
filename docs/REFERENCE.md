# coderails Component Reference

Catalogue of every coderails component (31 skills, plus hooks, commands, scripts): what it does, when it's active, when it's NOT, and dependencies. Ground truth: all entries verified from source files. See README for a lighter overview.

---

## Table of Contents

1. [Skills](#skills)
   - [Coderails-original skills](#coderails-original-skills)
   - [Vendored dev-workflow skills](#vendored-dev-workflow-skills)
   - [Wiki skills](#wiki-skills)
   - [Engineering principles skills](#engineering-principles-skills)
2. [Hook Activation Matrix](#hook-activation-matrix)
3. [Commands](#commands)
4. [Scripts and Libraries](#scripts-and-libraries)
5. [Artifact and State Locations](#artifact-and-state-locations)

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

**Dependencies:** Reads and writes `progress.json` (ephemeral loop state — path computed by `hooks/scripts/lib/agentic_loop_path.sh`, never manually). Invokes `coderails:writing-plans`, `coderails:premortem`, `coderails:brainstorming`, `coderails:handoff` as sub-skills. Interacts with `loop_state_guard` and `loop_stall_guard` Stop hooks.

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

**Purpose:** Game-resistant success-eval generation. Produces a frozen `evals.json` (scope `pr` or `loop`, tiers 0-2) with negative controls and grader independence, so success is judged against a fixed target instead of hand-waved after the fact.

**When it triggers:** Invoked at agentic-loop Phase 2.7, at plan completion per `writing-plans` (after stress-test, before implementation dispatch), or directly.

**Dependencies:** Consumed by `scripts/post_evals.sh` (`pr` scope, merge gate) and the `loop_state_guard` hook (`loop` scope gate).

---

#### `dashboard`

**Purpose:** Live local web HUD showing sessions, agentic loops, PR gate states, runs, memory activity, and declared one-click triggers.

**Invocation:** `/coderails:dashboard` or `scripts/start-dashboard.sh`.

---

#### `workflow-audit`

**Purpose:** Mines Claude Code session transcripts for tool-use patterns that repeat across sessions, judges which ones are genuine candidates for a new skill, and — only after explicit owner approval — creates each approved skill through the normal `writing-skills` TDD process and a full PR gate.

**When it triggers:** "look at our last N sessions and pull out repeated tasks", "what do I do repeatedly that isn't a skill yet", "audit my workflows", "mine my transcripts for skill candidates", "turn my repeated tasks into skills".

**Pipeline:** `scripts/scan_transcripts.sh` (transcripts → per-session tool-use event sequences) pipes into `scripts/cluster_ngrams.sh` (event sequences → recurring n-gram clusters across `--min-sessions` distinct sessions), then a fresh sonnet subagent applies `references/judge-contract.md` to each cluster for a propose/reject verdict. Proposed candidates are charted for the owner; nothing is created without an explicit approval in that interaction — this gate overrides any standing agentic-loop autonomy.

**Queue-mode output (optional):** each `verdict: "propose"` judge output can additionally be piped through `scripts/write_queue_entry.sh` to surface it on the observability dashboard, writing into `~/.claude/coderails-dashboard/approvals/` (routines' own scheduler intents live in the sibling `queue/` directory — see `docs/routines.md`). This is additive to, never a replacement for, the interactive approval gate — a dashboard "Approve" click only flips a queue entry's `status` from `pending` to `approved`.

**Approve-click build runner:** flipping a `workflow-audit:propose-skill` entry to `approved` makes the dashboard's `POST /api/queue` route (`skills/dashboard/app/src/lib/build/spawn.ts`) claim the entry and spawn a detached, headless `claude -p` build (`skills/dashboard/scripts/run-builder.sh`, prompted via `skills/dashboard/app/src/lib/build/prompt.ts`) that authors the proposed skill through skill-creator and ships it as a coderails PR through the full gate sequence. The builder never merges — its terminal state is an open PR with gates green, surfaced on the dashboard (`skills/dashboard/app/src/lib/collect/builds.ts`) as "awaiting your merge"; the owner reviews and merges by hand. Full contract: `docs/coderails/specs/2026-07-07-approve-build-runner.md`.

**Privacy invariant:** every artifact in the pipeline — scan output, cluster output, judge input/output, proposal chart, queue entry — carries only tool names, a privacy-whitelisted `head` (first two Bash command tokens, the Skill name, or the Agent subagent_type), counts, and session ids. Never verbatim transcript prose, file contents, or reconstructed intent.

**When it does NOT apply:** it never creates a skill without the interactive approval gate; the mechanical scan+cluster+queue-write pipeline has no skill-creation capability at all, the judge stage only proposes, and the build runner only triggers on an explicit owner Approve click — it is not autonomous.

---

#### `memory-consolidation`

**Purpose:** Health-checks and consolidates a project's persistent memory directory (`~/.claude/projects/<slug>/memory/`) — dedupes overlapping memories, flags stale or contradicted ones (without silently deleting `feedback`-type memories), and refreshes the `MEMORY.md` index.

**When it triggers:** "consolidate memory", "clean up memory", "memory consolidation", or when running as a scheduled routine (weekly, via the `routines` section of `~/.claude/coderails-dashboard.json`). Also runs standalone on demand.

**Dependencies:** Writes a durable report artifact to `~/.claude/coderails-dashboard/routines/memory-consolidation/report-{date}.md`, unconditionally — the property a scheduled routine's artifact-gate checks.

---

### Vendored dev-workflow skills

These are coderails' general development-discipline skills (not coderails-specific workflow) — they ship with the plugin, so no external skill plugin is required.

#### `brainstorming`

**Purpose:** Explores user intent, requirements, and design before implementation. Required before any creative work.

**When it triggers:** MUST be used before creating features, building components, adding functionality, or modifying behaviour. Mandatory pre-implementation gate. Saves spec to `docs/coderails/specs/YYYY-MM-DD-<topic>-design.md`.

**When it does NOT apply:** Pure investigation/research turns with no implementation intent.

---

#### `writing-plans`

**Purpose:** Turn a resolved spec into an ordered set of self-contained implementation tasks, each with exact files, interfaces, bite-sized steps, and verify-criteria.

**When it triggers:** After a spec exists and work spans multiple tasks, files, or reviewable units. Not for single trivial edits.

**Plan storage:** Plans referenced as `docs/coderails/plans/<name>.md` (committed to the repo, not ephemeral). The agentic loop's `plan.md` is a special case — it lives in the loop-state dir outside the repo alongside `progress.json`.

**Next step (required):** After the self-review gate, the plan goes through `/coderails:planning-sequence` (Pre-Parade → Premortem → Red Team) before implementation hands off to `subagent-driven-development`/`executing-plans`. Findings fold back into the plan inline.

---

#### `subagent-driven-development`

**Purpose:** Execute implementation plans with independent tasks in the current session using sub-agents.

**When it triggers:** When executing a written implementation plan with tasks that can be parallelised.

---

#### `dispatching-parallel-agents`

**Purpose:** Pattern for dispatching 2+ independent tasks to parallel agents to avoid sequential bottlenecks.

**When it triggers:** When facing 2+ independent tasks with no shared state or sequential dependencies.

---

#### `executing-plans`

**Purpose:** Execute a written implementation plan in a separate session with review checkpoints.

**When it triggers:** When a written implementation plan exists and needs to be executed with oversight.

---

#### `using-git-worktrees`

**Purpose:** Ensure an isolated workspace exists via native tools or git worktree fallback before feature work.

**When it triggers:** When starting feature work that needs isolation from the current workspace, or before executing implementation plans.

---

#### `requesting-code-review`

**Purpose:** Guide the code review request process to ensure work is complete and requirements are met.

**When it triggers:** When completing tasks, implementing major features, or before merging.

---

#### `receiving-code-review`

**Purpose:** Ensure code review feedback is handled with technical rigor and verification, not performative agreement or blind implementation.

**When it triggers:** When receiving code review feedback, before implementing suggestions — especially when feedback seems unclear or technically questionable.

---

#### `finishing-a-development-branch`

**Purpose:** Presents structured options (merge, PR, cleanup) for integrating completed work when implementation is done and all tests pass.

**When it triggers:** When implementation is complete, all tests pass, and a decision is needed on how to integrate the work.

---

#### `systematic-debugging`

**Purpose:** Structured debugging approach before proposing fixes for bugs, test failures, or unexpected behaviour.

**When it triggers:** When encountering any bug, test failure, or unexpected behaviour — before proposing fixes.

---

#### `test-driven-development`

**Purpose:** Red-green-refactor discipline: write the failing test first, watch it fail for the right reason, write minimal code to pass, refactor.

**When it triggers:** When about to implement or fix code that can carry a test — features, bugfixes, or refactors that add or alter a function, method, or branch.

**When it does NOT apply:** Docs, config, or prose edits with no testable code — those verify by inspection.

---

#### `verification-before-completion`

**Purpose:** Run verification commands and confirm output before making any success claims. Evidence before assertions.

**When it triggers:** When about to claim work is complete, fixed, or passing, before committing or creating PRs.

---

#### `using-coderails`

**Purpose:** Establishes how to find and use skills at session start. Requires skill invocation before ANY response including clarifying questions.

**When it triggers:** When starting any conversation. Also injected automatically at every session start by the `inject_bootstrap.sh` `SessionStart` hook — Claude receives the full SKILL.md content as context so it can self-bootstrap without being told.

---

#### `writing-skills`

**Purpose:** Guidance for creating new skills, editing existing skills, or verifying skills work before deployment.

**When it triggers:** When creating, editing, or verifying skills.

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

**Purpose:** Enforce engineering principles (YAGNI, KISS, DRY, Fail Fast, SSOT, Law of Demeter) and language-specific coding standards across Python, Go, and TypeScript. Uses LSP (Serena) for call site analysis and reference counting. Dispatches to the appropriate language sub-skill after detecting the file extension.

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

## Hook Activation Matrix

Hooks run automatically on lifecycle events. They can **block** (exit 2 / `permissionDecision: deny`), **warn** (inject advisory context), or run **silently** (inject context with no visible signal). Claude has no choice about whether they run — this is the mechanical enforcement layer.

| Event | Matcher | Script | Mode | WHEN ACTIVE | WHEN INACTIVE |
|---|---|---|---|---|---|
| `SessionStart` | `startup\|clear\|compact` | `inject_bootstrap.sh` | silent | On every session start, clear, or compact that matches the keyword | Never inactive once installed; only skips if `SKILL_FILE` is missing |
| `UserPromptSubmit` | (all prompts) | `inject_context.sh` | silent | Every user prompt — prepends `[ctx] <date> \| cwd=... \| branch=...`; on the first prompt of a session also appends the discipline reminder | Never inactive |
| `UserPromptSubmit` | (all prompts) | `discipline_catchup.sh` | warn | When the previous assistant response (≥200 chars) missed confidence labels or (for 3+ file edits) a `## Did Not Verify` section; injects `additionalContext` nudge into the new prompt | Skips when no transcript exists, when the last response is short (<200 chars), or when discipline was already present |
| `Stop` + `SubagentStop` | — | `check_confidence_labels.sh` | **block** | Blocks (exit 2) when the response is ≥200 chars and contains no `(verified)`, `(inferred)`, or `(guess)` label. On `SubagentStop`, reads `last_assistant_message` directly (skips transcript parse — avoids the parent-transcript flush race and checks the correct message). | Skips for short responses (<200 chars) or when any label is already present |
| `Stop` + `SubagentStop` | — | `check_verify_loop.sh` | **block** | Blocks (exit 2) when the response contains a `## Did Not Verify` section with any untagged bullet — enforced regardless of whether files were edited this turn (the `file_count` gate was removed). On `SubagentStop`, reads `last_assistant_message` directly. `loop_state_guard` and `loop_stall_guard` remain `Stop`-only (loop-state ownership is a parent-session concept; subagents have no `progress.json`). | Skips when: no transcript (Stop-only — on SubagentStop the script reads `last_assistant_message` directly and skips the transcript), already blocked once this turn (`stop_hook_active=true`), no DNV section, or all DNV bullets carry the `(unverifiable: <reason>)` tag |
| `Stop` | — | `loop_state_guard.sh` | **block** | Blocks when an agentic-loop Skill was invoked this session AND `progress.json` is absent, belongs to a different session, or is stale-complete after a rearm. Also gates loop-scope evals: when `progress.json`'s `work_units` field reports ≥3 units, blocks if no loop-scope `evals.json` is found beside it; fails open (no block) when `work_units` is absent. | Inactive (skips) when: no transcript, `stop_hook_active=true`, no `agentic-loop` Skill invocation in the transcript, or loop is genuinely complete and not re-armed for the current session |
| `Stop` | — | `loop_stall_guard.sh` | **block** | Blocks when an active (non-complete) agentic loop is running and the stopping turn carries no valid `LOOP-STOP: <hard-stop\|approval-gate\|awaiting-input\|complete> — <reason>` declaration | Inactive (skips) when: no transcript, `stop_hook_active=true`, no agentic-loop invocation, loop is complete and not re-armed, or a valid LOOP-STOP declaration is present in the last response |
| `Stop` | — | `unregistered_loop_guard.sh` | **nudge** (never blocks) | Injects an `additionalContext` nudge when the session is dispatch-heavy (≥3 distinct Agent-dispatch turns, counted by unique assistant `message.id`) with no `progress.json` at the resolved path and no `agentic-loop` Skill invocation anywhere in the transcript — the heuristic proxy for "orchestrator forgot to register the loop." Sibling to `loop_state_guard`/`loop_stall_guard`, not an extension: those answer "is a *registered* loop's `progress.json` present and healthy" (ground-truth, blockable); this one answers "does this *unregistered* session look like a loop that should have registered" (heuristic, nudge-only). | Skips (silent, no nudge) when: no transcript, dispatch turns < 3, `progress.json` already present at the resolved path, or an `agentic-loop` Skill invocation is found in the transcript |
| `PreToolUse` | `Bash` | `destructive_bash_gate.sh` | **block** | Permanent blocklist: `rm -rf`, `git push --force`, `git reset --hard`, SQL `DROP TABLE/DATABASE/SCHEMA` and `TRUNCATE TABLE`, `dd if=`, `mkfs.*`, `chmod -R 777`, `git commit --no-verify`, `git clean -f/--force`, `find -delete/--delete`, `truncate -s/--size`, `shred`. Also blocks in-Bash source-file edits (`sed -i`, `perl -i`, `>` / `>>` redirects, `tee`, `cp`/`mv`/`dd of=`) targeting source extensions (`.py`, `.ts`, `.tsx`, `.js`, `.jsx`, `.go`) or plugin markdown (`skills/*/SKILL.md`, `commands/*.md`) when the file's repo is on main/master (best-effort; variable filenames, quoted paths with spaces, `python -c` writes remain uncaught). | Skips when no Bash command is detected or when the command matches none of the patterns. There is NO approval path — the only escape is a `settings.json` Bash permission rule |
| `PreToolUse` | `Bash` | `enforce_pr_workflow.sh` | **block** | Blocks `gh pr create` unless `/coderails:push` ran this session; blocks `gh pr merge <N>` unless `/pr-review-toolkit:review-pr <N>` ran this session (per-PR, consume-on-use — the PR number must match); blocks `git merge` on main/master unless `review-pr` ran since the last `git merge`; blocks `git push` to main/master (current branch, colon refspec `HEAD:main`, or positional bare branch token `git push origin main`) unless `review-pr` ran this session. Scans `agent_transcript_path` in addition to `transcript_path` for subagent context. `git merge-base`/`merge-file`/`merge-tree` (read-only plumbing) excluded; `--abort`/`--continue`/`--quit`/`--skip` exempt. | **Opt-in only**: inactive (skips) when no `workflow.config.yaml` exists (`NO_CONFIG`). Also skips for `--help`/`--dry-run`. Escapable by adding a Bash permission to `settings.json` |
| `PreToolUse` | `Bash` | `test_gate.sh` | **block** | Blocks `git commit` if the project has `.claude/test_command` and the tests fail | **Opt-in only**: completely inactive unless `.claude/test_command` exists in the project. Set up via `/coderails:test-gate-setup` |
| `PreToolUse` | `Write\|Edit\|MultiEdit` | `no_edit_on_main.sh` | **block** | On main/master, blocks edits to ANY file EXCEPT an explicit allowlist: `.md`/`.txt`/`.rst` (plain docs), `.yaml`/`.yml`/`.json`/`.toml`/`.ini`/`.cfg` (config), the literal `.gitignore` dotfile (by basename — not `deploy.gitignore`), and `LICENSE`. Plugin source markdown (`skills/*/SKILL.md`, `commands/*.md`) is also blocked (treated as source, not docs) when the file's repo carries `.claude-plugin/plugin.json`. Both the gated-ness and the branch check key off the **file's own repo**, not the session cwd. | Skips for allowlist files, for non-`main`/`master` branches, and for a sibling **non-plugin** repo's lookalike `commands/`/`skills/` markdown (e.g. the wiki — no marker, so never gated). Escapable by creating a feature branch first, or by adding a `Write`/`Edit` permission rule to `settings.json` |
| `PreToolUse` | `Write\|Edit\|MultiEdit` | `comment_citation_gate.sh` | **block** | Blocks Write/Edit/MultiEdit content (`new_string`/`content`/`edits[].new_string`) that adds a comment citing a session-artifact label — `E#:`, `F# fix`/`:`/`design`, `CHANGE B#`/`C#`, `Task A#`, `TA-I#`, "reviewer finding", `eval E#`, `WU#:`, `C2`, or "per the plan/design/session" — instead of stating the constraint the code enforces. `PR #NN` is a documented survivor (resolves to a durable, checkable GitHub artifact) so it is not matched. | Skips entirely for `.md` files (markdown is out of scope); skips when no citation-shaped label is found in the new content; fails open on malformed/missing input |

### Notes on the activation conditions

- **`loop_state_guard` and `loop_stall_guard`** only enforce discipline when an `agentic-loop` Skill invocation appears in the transcript. Outside an agentic loop session they are silent no-ops.
- **`unregistered_loop_guard`** is the inverse case: it fires precisely when NO `agentic-loop` Skill invocation appears in the transcript, but dispatch behaviour looks loop-like. It never blocks — only a nudge — so it carries no bypass mechanism.
- **`enforce_pr_workflow`** is a no-op in any repo without `workflow.config.yaml`. It only kicks in once a project is initialised with `/coderails:init`.
- **`test_gate`** requires an explicit opt-in file (`.claude/test_command`) per project. Run `/coderails:test-gate-setup` to configure it.
- **`destructive_bash_gate`** has no approval path — it is a permanent block. The only override is a `settings.json` Bash permission rule added by the user.
- **`check_verify_loop`**: the `(unverifiable: <reason>)` tag is the only escape for a DNV bullet. Enforcement is independent of whether files were edited this turn — a DNV section in any response is policed. It is auditable — overuse is visible on review. Tagging a checkable item to avoid the block is the one thing the hook cannot catch.

### Hook library files

| File | Purpose | Consumers |
|---|---|---|
| `hooks/scripts/lib/discipline_common.sh` | Shared transcript-extraction utilities: `dc_extract_last_text`, `dc_stable_text` (with retry-backoff for the transcript-flush race) | `check_confidence_labels.sh`, `check_verify_loop.sh`, `discipline_catchup.sh` |
| `hooks/scripts/lib/loop_state_common.sh` | Shared agentic-loop detection: `LOOP_STOP_VOCAB`, `als_log`, `als_sanitise_session_id`, `als_count_invocations`, `als_stable_invocations`, `als_resolve_path`, `als_read_file_state`, `als_read_work_units`, `als_read_loop_evals_result` | `loop_state_guard.sh`, `loop_stall_guard.sh`, `unregistered_loop_guard.sh` |
| `hooks/scripts/lib/agentic_loop_path.sh` | Sole authority for the `progress.json` path. Computes `<base>/<slug>/<session_id>/progress.json` where slug is keyed to the repo's `git --git-common-dir` (absolute path, validated; shared across a repo's worktrees) when cwd is inside a git repo, falling back to cwd with `/` replaced by `-` on any git failure or non-absolute output; session_id defaults to `$CLAUDE_CODE_SESSION_ID` (falling back to a unique generated value when unavailable). Never called directly by Claude — always run via Bash to get the path. | `loop_state_common.sh` (via `als_resolve_path`), the agentic-loop orchestrator (to get the write path) |

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
| `/coderails:merge` | Merge an approved PR, switch to main, and pull latest. Requires a coderails review artifact AND a coderails eval artifact on the PR for the current head SHA before merging. | Shells out to `scripts/merge.sh`; requires GitHub remote; checks PR approval if branch protection is on; fetches live PR comments for both the review-artifact gate and the eval-artifact gate |
| `/coderails:init` | Scaffold a `workflow.config.yaml` for the current project. Writes to `$(pwd)/.claude/` (resolved by walk-up — see Config resolution). | `git rev-parse`, Write tool; idempotent — confirms before overwriting |
| `/coderails:test-gate-setup` | Configure the test gate for the current project. Detects the test runner (npm, cargo, pytest, go test, etc.) and writes `.claude/test_command`. | Write tool; opt-in gate for `test_gate.sh` hook |
| `/coderails:assumptions` | List every assumption currently being made (task, codebase, environment, state), marked `(verified)` or `(inferred)`. Pure inventory — does no other work. | None |
| `/coderails:disconfirm` | Argue against the most recent recommendation — find the strongest case it is wrong. Steelmans the opposition. | None |
| `/coderails:verify` | Re-derive a specific claim from sources only (tool results, file contents, user statements, git output). No recall, no inference. | None |
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
| `scripts/push.sh` | Stage tracked changes only (`git add -u`; warns about any untracked files instead of staging them), commit (prefixing Jira key if set), push, and create or update a PR via `gh`. Detects whether a PR already exists and comments on it rather than creating a duplicate. | `/coderails:push` command (shells out to it) |
| `scripts/merge.sh` | Resolve a PR from a number, branch name, or current branch; check approval if branch protection requires it; merge via `gh pr merge --merge`; switch to main; pull; clean up the remote branch (best-effort, non-fatal). | `/coderails:merge` command (shells out to it) |
| `scripts/lib/git-common.sh` | Shared bash utilities: terminal colour helpers (`ok`, `warn`, `err`, `step`, `banner`); git core helpers (`branch`, `dirty`, `main`, `ahead`, `ahead_list`); repository helpers (`repo`, `protected`); PR helpers (`pr::num`, `pr::url`, `pr::state`, `pr::title`, `pr::review`, `pr::exists`); guards (`require::feature`, `require::clean`, `require::repo`); review-gate helpers (`pr::head_sha`, `pr::has_coderails_review_for_head`). | `scripts/push.sh`, `scripts/merge.sh` (both `source` it) |
| `scripts/post_review.sh` | Summary grammar validator and progress.json cache writer for `/coderails:post-review`. Exposes `validate`/`write-cache` subcommands. Called as a subprocess by `commands/post-review.md`. | `/coderails:post-review` command |
| `scripts/lib/review-artifact.sh` | SSOT for the coderails review artifact marker: `review_artifact::marker <pr> <sha>` (builds the exact marker string), `review_artifact::matches_marker <line> <pr> <sha>` (exact-equality match). Both `/post-review` (writer) and `/merge` (reader) source this lib — no literal marker duplication. | `scripts/post_review.sh`, `scripts/merge.sh` (via `git-common.sh`) |
| `scripts/lib/eval-artifact.sh` | SSOT for the coderails eval artifact marker: `eval_artifact::marker <pr> <head_sha> <result> <tier>` (builds the exact marker string), plus `eval_artifact::compute_go` (the only place a `GO`/`NO-GO` result is derived). Source-only — mirrors `review-artifact.sh`. Both `/post-evals` (writer) and `/merge` (reader) source this lib. | `scripts/post_evals.sh`, `scripts/merge.sh` |
| `scripts/post_evals.sh` | Structural validator and result computer for `/coderails:post-evals`. `post_evals::validate_structure` runs anti-gaming structural refusals (schema, frozen-SHA match, tier/priority shape, and other gaming checks) in order, first failure wins; `post_evals::compute_and_validate_result` echoes `GO`/`NO-GO` by calling `eval_artifact::compute_go` — never read from a caller-supplied field. | `/coderails:post-evals` command |

### `require::repo` constraint

`push.sh` calls `require::repo` which validates that the git remote is on `github.com`. Repos on other hosts (GitLab, Bitbucket, self-hosted) will fail at push time.

---

## Artifact and State Locations

| Artifact | Location | Committed? | Notes |
|---|---|---|---|
| `workflow.config.yaml` | first `.claude/workflow.config.yaml` found walking from cwd up to git root (`$(pwd)/.claude/` for `/init`) | Yes | Project-specific config for jira, wiki, worktree, engineering-principles. Created by `/coderails:init`. |
| `.claude/test_command` | Project working directory | Yes (project-local) | Plain-text file containing the test command. Created by `/coderails:test-gate-setup`. Activates `test_gate.sh`. |
| Specs from brainstorming | `docs/coderails/specs/YYYY-MM-DD-<topic>-design.md` | Yes | Written by `brainstorming` skill after design resolution. Permanent record. |
| Plans from writing-plans | `docs/coderails/plans/<name>.md` | Yes | Written by `writing-plans` skill. Permanent plan record. |
| Agentic loop `progress.json` | `~/.claude/agentic-loop/<repo-or-cwd-slug>/<session_id>/progress.json` | No — ephemeral loop state, outside the repo | Dynamic position tracker for the loop. Path computed by `agentic_loop_path.sh` — keyed to the repo (shared across its worktrees) when cwd is inside a git repo, falling back to cwd otherwise. Session-keyed. |
| Agentic loop `spec.md` | Same dir as `progress.json` | No — ephemeral loop state | Written by the agentic-loop orchestrator for ≥3-unit loops. Not a PR deliverable. |
| Agentic loop `plan.md` | Same dir as `progress.json` | No — ephemeral loop state | Written by `coderails:writing-plans` as invoked by the agentic-loop. Consumed, not write-only: the orchestrator re-reads it after compaction to recover scope. |
| `evals.json` (pr scope) | Working material only — no fixed path; wherever the invoking workflow placed it (e.g. current working tree or a path named in the worker prompt) | No — the durable artifact is the SHA-bound `coderails-eval-summary` PR comment, not this file | Generated and frozen per PR; validated and posted by `/coderails:post-evals` via `scripts/post_evals.sh` + `scripts/lib/eval-artifact.sh`. |
| `evals.json` (loop scope) | Same dir as `progress.json` | No — ephemeral loop state | Read by the `loop_state_guard.sh` hook when `progress.json`'s `work_units` ≥ 3; blocks `Stop` if absent. |
| Discipline log | `~/.claude/discipline.log` (or `$CLAUDE_DISCIPLINE_LOG`) | No | Structured `key=value` log appended by hooks on every fire. Never committed. |
| LLM Wiki vault | `config.wiki_path` (set in `workflow.config.yaml`) | Separate repo/vault | Maintained by `wiki-ingest`, `wiki-lint`, `wiki-query`. Browsed in Obsidian. |

### The ephemeral vs committed boundary

The loop's `spec.md`, `plan.md`, and `progress.json` live in `~/.claude/agentic-loop/` — **outside** the code repo. They are loop state keyed to this orchestrator run, not shareable design records. If work needs handing to a human, `coderails:handoff` is the right tool. Committed artifacts (brainstorming specs, writing-plans plans) live in `docs/coderails/` inside the repo and are permanent.
