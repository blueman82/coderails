# coderails Component Reference

Complete catalogue of every coderails component: what it does, when it's active, when it's NOT, and dependencies. Ground truth: all entries verified from source files. See README for a lighter overview.

---

## Table of Contents

1. [Skills](#skills)
   - [Coderails-original skills](#coderails-original-skills)
   - [Vendored dev-workflow skills](#vendored-dev-workflow-skills)
   - [Wiki skills](#wiki-skills)
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

**When it triggers:** Any of: "TeamCreate", "spawn a team", "no human gates", "self-merge", "crack on", "without the human", "no per-PR confirmation", "agentic loop", "multi-PR", or 3+ PRs authorised in one instruction. Also triggers for single-PR autonomous merge+deploy+verify chains where the user has explicitly waived per-step confirmation.

**When it does NOT apply:** Single-PR interactive work — that is `/coderails:workflow`. The agentic loop sits _above_ `/workflow` and uses it as a subroutine.

**Key discipline:** Main context is a pure orchestrator. Every code change (even single-file edits) goes to a spawned Sonnet agent. The orchestrator never implements; it delegates to agents, verifies artifacts, and escalates to `TeamCreate` only for ≥3 sequential PRs or dependency chains.

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

## Hook Activation Matrix

Hooks run automatically on lifecycle events. They can **block** (exit 2 / `permissionDecision: deny`), **warn** (inject advisory context), or run **silently** (inject context with no visible signal). Claude has no choice about whether they run — this is the mechanical enforcement layer.

| Event | Matcher | Script | Mode | WHEN ACTIVE | WHEN INACTIVE |
|---|---|---|---|---|---|
| `SessionStart` | `startup\|clear\|compact` | `inject_bootstrap.sh` | silent | On every session start, clear, or compact that matches the keyword | Never inactive once installed; only skips if `SKILL_FILE` is missing |
| `UserPromptSubmit` | (all prompts) | `inject_context.sh` | silent | Every user prompt — prepends `[ctx] <date> \| cwd=... \| branch=...`; on the first prompt of a session also appends the discipline reminder | Never inactive |
| `UserPromptSubmit` | (all prompts) | `discipline_catchup.sh` | warn | When the previous assistant response (≥200 chars) missed confidence labels or (for 3+ file edits) a `## Did Not Verify` section; injects `additionalContext` nudge into the new prompt | Skips when no transcript exists, when the last response is short (<200 chars), or when discipline was already present |
| `Stop` | — | `check_confidence_labels.sh` | **block** | Blocks (exit 2) when the response is ≥200 chars and contains no `(verified)`, `(inferred)`, or `(guess)` label | Skips for short responses (<200 chars) or when any label is already present |
| `Stop` | — | `check_verify_loop.sh` | **block** | Blocks (exit 2) when the response contains a `## Did Not Verify` section with any bullet that is NOT tagged `(unverifiable: <reason>)` | Skips when: no transcript, no files edited this turn, already blocked once this turn (`stop_hook_active=true`), no DNV section, or all DNV bullets carry the unverifiable tag |
| `Stop` | — | `loop_state_guard.sh` | **block** | Blocks when an agentic-loop Skill was invoked this session AND `progress.json` is absent, belongs to a different session, or is stale-complete after a rearm | Inactive (skips) when: no transcript, `stop_hook_active=true`, no `agentic-loop` Skill invocation in the transcript, or loop is genuinely complete and not re-armed for the current session |
| `Stop` | — | `loop_stall_guard.sh` | **block** | Blocks when an active (non-complete) agentic loop is running and the stopping turn carries no valid `LOOP-STOP: <hard-stop\|approval-gate\|awaiting-input\|complete> — <reason>` declaration | Inactive (skips) when: no transcript, `stop_hook_active=true`, no agentic-loop invocation, loop is complete and not re-armed, or a valid LOOP-STOP declaration is present in the last response |
| `PreToolUse` | `Bash` | `destructive_bash_gate.sh` | **block** | Blocks `rm -rf`, `git push --force`, `git reset --hard`, SQL `DROP`/`TRUNCATE`, `dd if=`, `mkfs.*`, `chmod -R 777`, `git commit --no-verify` patterns | Skips when no Bash command is detected or when the command matches none of the destructive patterns. There is NO approval path — the only escape is a `settings.json` Bash permission rule |
| `PreToolUse` | `Bash` | `enforce_pr_workflow.sh` | **block** | Blocks `gh pr create` unless `/coderails:push` ran this session; blocks `gh pr merge` or `git merge` on main/master unless `/pr-review-toolkit:review-pr` ran this session; `git merge-base`/`merge-file`/`merge-tree` (read-only plumbing) excluded; `--abort`/`--continue`/`--quit`/`--skip` exempt | **Opt-in only**: inactive (skips) when no `workflow.config.yaml` exists (`NO_CONFIG`). Also skips for `--help`/`--dry-run` and for commands that aren't `gh pr create\|merge` or `git merge`. Escapable by adding a Bash permission to `settings.json` |
| `PreToolUse` | `Bash` | `test_gate.sh` | **block** | Blocks `git commit` if the project has `.claude/test_command` and the tests fail | **Opt-in only**: completely inactive unless `.claude/test_command` exists in the project. Set up via `/coderails:test-gate-setup` |
| `PreToolUse` | `Write\|Edit\|MultiEdit` | `no_edit_on_main.sh` | **block** | Blocks Write/Edit/MultiEdit on `.py`, `.ts`, `.tsx`, `.js`, `.jsx`, `.go` files, plus plugin source carried in markdown (`skills/*/SKILL.md`, `commands/*.md`), when the current branch is `main` or `master` | Skips for plain docs/config (including non-`SKILL.md` markdown and root docs like `README.md`) and for any branch that is not `main`/`master`. Escapable by creating a feature branch first, or by adding a `Write`/`Edit` permission rule to `settings.json` |

### Notes on the activation conditions

- **`loop_state_guard` and `loop_stall_guard`** only enforce discipline when an `agentic-loop` Skill invocation appears in the transcript. Outside an agentic loop session they are silent no-ops.
- **`enforce_pr_workflow`** is a no-op in any repo without `workflow.config.yaml`. It only kicks in once a project is initialised with `/coderails:init`.
- **`test_gate`** requires an explicit opt-in file (`.claude/test_command`) per project. Run `/coderails:test-gate-setup` to configure it.
- **`destructive_bash_gate`** has no approval path — it is a permanent block. The only override is a `settings.json` Bash permission rule added by the user.
- **`check_verify_loop`**: the `(unverifiable: <reason>)` tag is the only escape for a DNV bullet. It is auditable — overuse is visible on review. Tagging a checkable item to avoid the block is the one thing the hook cannot catch.

### Hook library files

| File | Purpose | Consumers |
|---|---|---|
| `hooks/scripts/lib/discipline_common.sh` | Shared transcript-extraction utilities: `dc_extract_last_text`, `dc_stable_text` (with retry-backoff for the transcript-flush race) | `check_confidence_labels.sh`, `check_verify_loop.sh`, `discipline_catchup.sh` |
| `hooks/scripts/lib/loop_state_common.sh` | Shared agentic-loop detection: `LOOP_STOP_VOCAB`, `als_log`, `als_count_invocations`, `als_stable_invocations`, `als_resolve_path`, `als_read_file_state` | `loop_state_guard.sh`, `loop_stall_guard.sh` |
| `hooks/scripts/lib/agentic_loop_path.sh` | Sole authority for the `progress.json` path. Computes `<base>/<slug>/progress.json` where slug is cwd with `/` replaced by `-`. Never called directly by Claude — always run via Bash to get the path. | `loop_state_common.sh` (via `als_resolve_path`), the agentic-loop orchestrator (to get the write path) |

---

## Commands

Commands are slash commands invoked by Claude (or the user via `/coderails:<name>`). They encode workflow logic but are **advisory** — Claude must choose to invoke them. Unlike hooks, commands cannot self-enforce.

| Command | Description | Key dependencies |
|---|---|---|
| `/coderails:workflow` | Orchestrate the full feature workflow: `prep → code → push → review → merge → wiki-ingest → wiki-lint`. Two interactive pauses: the code/iterate loop, and final ship-it authorisation. | Delegates to all other commands; reads `workflow.config.yaml`; requires `pr-review-toolkit` plugin for the review stage |
| `/coderails:prep` | Create a safety branch, a feature/bug branch, and optionally a Jira ticket. | `git worktree`, Jira MCP (optional — skips if `config.jira` is null or no Jira MCP); reads `workflow.config.yaml` |
| `/coderails:push` | Stage, commit, push changes, and create a PR. Runs a strictcode pre-flight if `config.strictcode_paths` is set. | Shells out to `scripts/push.sh`; requires a GitHub remote; reads `workflow.config.yaml` |
| `/coderails:merge` | Merge an approved PR, switch to main, and pull latest. | Shells out to `scripts/merge.sh`; requires GitHub remote; checks PR approval if branch protection is on |
| `/coderails:init` | Scaffold a `workflow.config.yaml` for the current project. Detects monorepo vs standalone layout. | `git rev-parse`, Write tool; idempotent — confirms before overwriting |
| `/coderails:test-gate-setup` | Configure the test gate for the current project. Detects the test runner (npm, cargo, pytest, go test, etc.) and writes `.claude/test_command`. | Write tool; opt-in gate for `test_gate.sh` hook |
| `/coderails:assumptions` | List every assumption currently being made (task, codebase, environment, state), marked `(verified)` or `(inferred)`. Pure inventory — does no other work. | None |
| `/coderails:disconfirm` | Argue against the most recent recommendation — find the strongest case it is wrong. Steelmans the opposition. | None |
| `/coderails:verify` | Re-derive a specific claim from sources only (tool results, file contents, user statements, git output). No recall, no inference. | None |
| `/coderails:notchecked` | Review recent responses and list every non-trivial claim that was NOT verified. Surface gaps ruthlessly. | None |

### Config resolution (shared by `workflow`, `prep`, `push`, `init`)

Every workflow command reads `workflow.config.yaml` inline via a bash substitution:

```bash
GIT_ROOT=$(git rev-parse --show-toplevel)
cat "$GIT_ROOT/projects/$(basename $(pwd))/.claude/workflow.config.yaml" \  # monorepo layout
  || cat "$GIT_ROOT/.claude/workflow.config.yaml" \                         # standalone repo
  || echo "NO_CONFIG"
```

`NO_CONFIG` is the sentinel for "not initialised." All workflow commands degrade gracefully: Jira steps no-op, wiki steps skip, strictcode pre-flight skips, `enforce_pr_workflow` hook is inactive.

---

## Scripts and Libraries

| File | Purpose | Consumers |
|---|---|---|
| `scripts/push.sh` | Stage (`git add -A`), commit (prefixing Jira key if set), push, and create or update a PR via `gh`. Detects whether a PR already exists and comments on it rather than creating a duplicate. | `/coderails:push` command (shells out to it) |
| `scripts/merge.sh` | Resolve a PR from a number, branch name, or current branch; check approval if branch protection requires it; merge via `gh pr merge --merge`; switch to main; pull; clean up the remote branch (best-effort, non-fatal). | `/coderails:merge` command (shells out to it) |
| `scripts/lib/git-common.sh` | Shared bash utilities: terminal colour helpers (`ok`, `warn`, `err`, `step`, `banner`); git core helpers (`branch`, `dirty`, `main`, `ahead`, `ahead_list`); repository helpers (`repo`, `protected`); PR helpers (`pr::num`, `pr::url`, `pr::state`, `pr::title`, `pr::review`, `pr::exists`); guards (`require::feature`, `require::clean`, `require::repo`). | `scripts/push.sh`, `scripts/merge.sh` (both `source` it) |

### `require::repo` constraint

`push.sh` calls `require::repo` which validates that the git remote is on `github.com`. Repos on other hosts (GitLab, Bitbucket, self-hosted) will fail at push time.

---

## Artifact and State Locations

| Artifact | Location | Committed? | Notes |
|---|---|---|---|
| `workflow.config.yaml` | `<git-root>/.claude/workflow.config.yaml` (standalone) or `<git-root>/projects/<name>/.claude/workflow.config.yaml` (monorepo) | Yes | Project-specific config for jira, wiki, worktree, strictcode. Created by `/coderails:init`. |
| `.claude/test_command` | Project working directory | Yes (project-local) | Plain-text file containing the test command. Created by `/coderails:test-gate-setup`. Activates `test_gate.sh`. |
| Specs from brainstorming | `docs/coderails/specs/YYYY-MM-DD-<topic>-design.md` | Yes | Written by `brainstorming` skill after design resolution. Permanent record. |
| Plans from writing-plans | `docs/coderails/plans/<name>.md` | Yes | Written by `writing-plans` skill. Permanent plan record. |
| Agentic loop `progress.json` | `~/.claude/agentic-loop/<cwd-slug>/progress.json` | No — ephemeral loop state, outside the repo | Dynamic position tracker for the loop. Path computed by `agentic_loop_path.sh`. Session-keyed. |
| Agentic loop `spec.md` | Same dir as `progress.json` | No — ephemeral loop state | Written by the agentic-loop orchestrator for ≥3-unit loops. Not a PR deliverable. |
| Agentic loop `plan.md` | Same dir as `progress.json` | No — ephemeral loop state | Written by `coderails:writing-plans` as invoked by the agentic-loop. Consumed, not write-only: the orchestrator re-reads it after compaction to recover scope. |
| Discipline log | `~/.claude/discipline.log` (or `$CLAUDE_DISCIPLINE_LOG`) | No | Structured `key=value` log appended by hooks on every fire. Never committed. |
| LLM Wiki vault | `config.wiki_path` (set in `workflow.config.yaml`) | Separate repo/vault | Maintained by `wiki-ingest`, `wiki-lint`, `wiki-query`. Browsed in Obsidian. |

### The ephemeral vs committed boundary

The loop's `spec.md`, `plan.md`, and `progress.json` live in `~/.claude/agentic-loop/` — **outside** the code repo. They are loop state keyed to this orchestrator run, not shareable design records. If work needs handing to a human, `coderails:handoff` is the right tool. Committed artifacts (brainstorming specs, writing-plans plans) live in `docs/coderails/` inside the repo and are permanent.
