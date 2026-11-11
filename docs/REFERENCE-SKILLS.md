# Coderails skills catalogue

[Coderails components](REFERENCE.md).

## Skills

Claude uses the `Skill` tool to invoke a skill for a discipline, workflow, or method.
The harness gives Claude the skill's `description` from frontmatter. Claude selects when to invoke it.

### Coderails-original skills

Coderails supplies these skills.

#### `agentic-loop`

**Purpose:** Coordinate work across agents or PRs when the user grants autonomy.

**When to use it:** "spawn a team", "create a team", "team of agents", "no human gates", "self-merge", "autonomous", "without the human", "no per-PR confirmation", "agentic loop", or "multi-PR".
It also applies if the user authorizes three or more PRs in one instruction.
It can run a single-PR merge, deploy, and verification chain if the user explicitly waives confirmation for each step.

**When it does NOT apply:** Use `/coderails:workflow` for interactive single-PR work. The agentic loop uses `/workflow` as a subroutine.

**Key discipline:** The parent session orchestrates. Send each code change to a provider-native worker with explicit task instructions.
This includes edits to one file. The orchestrator checks artifacts and starts a team only for three or more sequential PRs or dependency chains.

**Dependencies:** Reads and writes `progress.json` for temporary loop data. Use `hooks/scripts/lib/agentic_loop_path.py` to calculate the path.
It invokes `superpowers:writing-plans`, `coderails:premortem`, `superpowers:brainstorming`, and `coderails:handoff`.
The `loop_state_guard` and `loop_stall_guard` hooks check Stop.

---

#### `planning-sequence`

**Purpose:** Use Pre-Parade for success conditions, Premortem for possible causes of a bad result, and Red Team for adversarial challenge.
Use them in that sequence before you commit to a plan, idea, or decision.

**When to use it:** "run the planning sequence", "put this through the planning techniques", "stress-test my plan", or "Pre-Parade this".
Use it before a high-stakes decision or if the user is about to commit without adversarial planning.

**When it does NOT apply:** Use other skills for forward-looking checklists, code inspection, and general architecture critique.

---

#### `premortem`

**Purpose:** Start with the assumption that a plan, decision, or approach did not succeed. Work from that result to find its possible causes.

**When to use it:** "premortem this", "steelman the failure", or "what could go wrong with this plan".
It applies to adversarial stress-testing of a commitment by starting from an assumed bad result.

**When it does NOT apply:** Forward-looking checklists such as "what should I check before X", code inspection, general architecture critique, and fact verification.

---

#### `handoff`

**Purpose:** Write a structured memory file and a prompt to continue work in a new Claude Code session.

**When to use it:** "handoff", "hand off", "continue in new session", "pick this up later", "save this for next session", or "create a handoff".
Use it if the user wants to keep session context, for example at the end of a long session that they plan to continue.

---

#### `improve-prompt`

**Purpose:** Improve the prompt before execution. Identify ambiguity, fill missing information with reasonable assumptions, and write a clear task.

**When to use it:** `/improve-prompt`, "improve this prompt", "what's missing from this prompt", or a user who asks to tighten a task before execution.
Also use it when a prompt is vague or has no clear conditions for success.

---

#### `task-evals`

**Purpose:** Make a frozen `evals.json` with `pr` or `loop` scope and verification level 0 to 2.
Use negative controls and a grader who works independently. Compare results with a fixed target to prevent gaming.

**When to use it:** Use it at agentic-loop Phase 2.7 or when `superpowers:writing-plans` finishes the plan.
For a plan, use it after the stress test and before sending implementation work. Users can also invoke it directly.

**Dependencies:** `scripts/post_evals.py` reads `pr` scope for the merge gate. The `loop_state_guard` hook reads `loop` scope.

---

#### `dashboard`

**Purpose:** A live local web dashboard for sessions, agentic loops, PR gate status, runs, and memory operations. It offers declared one-click commands.

**Invocation:** `/coderails:dashboard` or `skills/dashboard/scripts/start_dashboard.py`.

[Dashboard output and connection behavior](REFERENCE-DASHBOARD.md).

---

#### `workflow-audit`

**Purpose:** Find recurring tool-use patterns in Claude Code transcripts. Check which patterns qualify for a skill.
Only after owner approval, write each approved skill through `superpowers:writing-skills` TDD and the full PR gate.

**When to use it:** "look at our last N sessions and pull out repeated tasks", "what do I do repeatedly that isn't a skill yet", "audit my workflows", "mine my transcripts for skill candidates", or "turn my repeated tasks into skills".

**Procedure.** The `skills/workflow-audit/scripts/scan_transcripts.py` script gives tool-use sequences for each session.
The `skills/workflow-audit/scripts/cluster_ngrams.py` script groups recurring n-grams across `--min-sessions` different sessions.
A new sonnet subagent applies `references/judge-contract.md` to each cluster and proposes or rejects it.

Show the candidates to the owner. Only explicit approval in that interaction permits creation. This gate also applies during agentic-loop autonomy.

**Queue output.** Optionally send `verdict: "propose"` through `skills/workflow-audit/scripts/write_queue_entry.py` to show it on the dashboard.
It writes to `~/.claude/coderails-dashboard/approvals/`. Scheduled intent files use sibling `queue/`. See `docs/routines.md`.

The dashboard "Approve" click changes an entry's `status` from `pending` to `approved`. This does not replace interactive approval.

**Build after approval.** When a `workflow-audit:propose-skill` entry becomes `approved`, `POST /api/queue` claims a build directory.
It starts a detached headless `claude -p` build through `skills/dashboard/app/src/lib/build/spawn.ts` and `skills/dashboard/scripts/run_builder.py`.
The prompt comes from `skills/dashboard/app/src/lib/build/prompt.ts`. The builder uses skill-creator and opens a Coderails PR through the full gate sequence.

The builder leaves the PR open with its gates green. The collector is `skills/dashboard/app/src/lib/collect/builds.ts`.
The owner examines and merges the PR by hand. The first skill from this procedure was `verify-merged-pr`.

During the build, the panel shows phase, elapsed time, and heartbeat age.
The collector validates the phase against `authoring`, `testing`, `pushing`, and `opening_pr`.
When the PR leaves a trusted open-PR set, the panel shows "PR resolved". If that set cannot be trusted, it does not mark the PR resolved.

**Privacy.** Transcript extraction, clustering, judging, charts, and queue entries use only tool names, approved `head` values, counts, and session IDs.
The `head` value is the first two Bash command tokens, Skill name, or Agent `subagent_type`.
No step includes verbatim transcript prose, file contents, or reconstructed intent.

**When it does NOT apply:** The extraction, clustering, and queue tools do not write skills.
The judge only proposes. The builder runs only after an explicit owner Approve click. This procedure does not grant autonomy.

---

#### `verify-merged-pr`

**Purpose:** Check a "PR #N is merged" claim before you rely on it.
Check merge status with `gh pr view`, and check content on `origin/main` with fetch, `git merge-base --is-ancestor`, and `git grep`.
Check sibling PRs from the same author and time window. A report can name one PR when a session merged more than one.

**When to use it:** Use it if an agent, teammate, CI report, or session summary says a PR is merged, shipped, live, or landed.
Use it before building on, deploying, or handing off work that requires the merge. A headless builder can report "done — PR merged" with one PR number.

**When it does NOT apply:** You did and saw the merge in this session, or the claim concerns an open or draft PR.

**Provenance:** A `workflow-audit` proposal, approved on the dashboard and built by a headless `skill-creator` session. The owner merged it by hand.
It was the first skill that the dashboard Approve→build runner made.

---

#### `cite-check`

**Purpose:** Check a claim from durable sources only: file contents, Git output, and new command output.
Give PASS, FAIL, or UNSUPPORTED with sources for each claim. Use no recall or inference.

**How it runs:** Uses `context: fork`, `agent: coderails:source-auditor`, and `background: false`.
The forked auditor gets only the claim through `$ARGUMENTS`. It does not get the conversation that gave the claim.
The fork prevents self-verification.

**When to use it:** Use `/coderails:cite-check <claim>`. In Phase 5, `agentic-loop` uses it on "this bug currently reproduces" before it sends repair work.

**Naming:** The name `cite-check` avoids a collision with Claude Code's bundled `/verify`, which builds and runs an app to check a change.
A project skill named `verify` would override the bundled skill.

**Dependencies:** The `coderails:source-auditor` agent.

---

#### `execution-discipline`

**Purpose:** Specify work before starting. Work autonomously in the granted scope, keep instructions in long sessions, and check the result.

**When to use it:** Use it before non-trivial work: multiple steps, files, tool calls, analysis, builds, debugging, research, document work, or long tasks.

**When it does NOT apply:** A trivial single-step response with no tool or file use.

---

#### `sync-docs`

**Purpose:** Compare code with its documentation to find drift and report work to correct it.
The optional `--semantic` setting uses Serena to find undocumented code. The mechanical diff also runs.

**When to use it:** "sync docs", "check documentation", "documentation drift", "doc audit", or `/sync-docs`.

**Invocation modes:**

- `/sync-docs` gives a full drift report.
- `/sync-docs --check` gives a report without suggestions.
- `/sync-docs --suggest-updates` gives proposed Markdown updates.
- `/sync-docs --semantic` uses Serena to find related code.
- `/sync-docs --compare <section>` analyzes one section in depth.
- `/sync-docs --verbose` gives file refs.
- `/sync-docs --diagrams-only` audits only `docs/diagrams/`.

---

#### `memory-consolidation`

**Purpose:** Check a project's memory directory at `~/.claude/projects/<slug>/memory/`.
Remove duplicates, mark stale or contradictory entries, and update `MEMORY.md`.
Do not silently remove `feedback` memories.

**When to use it:** "consolidate memory", "clean up memory", or "memory consolidation".
Run on demand or weekly through `routines` in `~/.claude/coderails-dashboard.json`.

**Dependencies:** Always write the report to `~/.claude/coderails-dashboard/routines/memory-consolidation/report-{date}.md`.
The scheduled artifact gate checks it.

---

#### `docs-sync`

**Purpose:** The scheduled procedure checks Git-tracked docs against code. If it finds drift, it edits, pushes, checks, and merges the fix without human interaction.
It uses the `sync-docs` audit first. Use `sync-docs` for an interactive audit.

**When to use it:** Only `sync-docs-nightly`. See `docs/routines.md`.
The previous read-only `sync-docs-weekly` did not run after 2026-07-15 because `foreignSkillPath` named a missing path.
The in-repo skill does not use that setting.

**No drift.** If the audit finds no drift, append `no-drift` and then terminal `run=ok`. Exit 0 without a branch or PR.
The run log is the `expectedArtifact`.
Its `last-marker` predicate accepts `run=ok`. A night with no drift passes without a different report file.

Most nights use this path.

**Publication.** If the audit finds drift, freeze `task-evals` for `pr` before edits.
Use `/coderails:push`, `/pr-review-toolkit:review-pr`, `/coderails:post-review`, `/coderails:post-evals`, and `/coderails:merge`.
Check `git diff origin/main...HEAD --name-status`. Do not use `--name-only`, which shows only the destination of a rename and cannot distinguish a deletion.

Abort and clean up unless the changed paths are Git index entries for Markdown files.
Abort and clean up for denylist matches, renames from paths external to scope, and deletions of docs in scope.

**Denylist.** The list has `skills/**/SKILL.md`, `AGENTS.md`, `CLAUDE.md`, `docs/routines.md`, all paths in `.claude/`, and `examples/dashboard-config.json`.
It includes this skill's own instructions. Report their drift to the human. Do not edit them in the scheduled procedure.

The first four entries are `.md`, so the manifest needs explicit denylist entries to prevent edits to them.
The rule for non-`.md` paths also blocks the last two. They stay in the list so it is complete on its own.

**Dependencies:** This was the repo's second scheduled procedure with the button set to `bypass`.
In `claude -p`, `PreToolUse` hooks do not run. The merge uses the artifact gates in `scripts/merge.py`.

The prompt supplies the denylist and manifest checks. The hooks do not check those conditions.
The `.md` rule limits scope for a cooperating agent. See the procedure and its limits in `docs/routines.md`.

---

#### `loop-retro-promotion`

**Purpose:** The scheduled procedure reads accumulated `retro.json` files and `standing-orders.md`.
It promotes lessons that apply across repositories into `skills/agentic-loop/learned-failure-modes.md`.

**When to use it:** Only `loop-retro-promotion-weekly`. See `docs/routines.md`.
Do not use it for one retro or in an active agentic-loop session.

**Graduation.** The `scripts/lib/lessons.py predicate` check runs each time. It checks for 10 or more `retro.json` files in the repo-key directory.
In `orders.json`, one entry must have different `last_recurred` and `created` dates. One must have `status: decayed`.

Each run appends a line to `promotion-runs.log`. If the condition does not hold, append terminal `run=ok` and stop without a branch, PR, or gate chain.
The artifact gate uses `last-marker`. It accepts `run=ok` and refuses `abort=` or an unfinished `delivery=started`.

**Publication.** After graduation, freeze `task-evals` for `pr` before edits.
Use `/coderails:push`, `/pr-review-toolkit:review-pr`, `/coderails:post-review`, `/coderails:post-evals`, and `/coderails:merge`.
The manifest accepts only `skills/agentic-loop/learned-failure-modes.md`. If a different file changes, abort, close the PR, remove the branch, and log the abort.

**Dependencies:** This was the first scheduled procedure with a button set to `bypass` for writes.
The `PreToolUse` hooks do not run in that mode. The `scripts/merge.py` artifact gates apply after graduation.
See the procedure and its limits in `docs/routines.md`.

---

#### `using-coderails`

**Purpose:** Find and use skills at session start. Invoke an applicable skill before a response or question.

**When to use it:** At the start of a conversation.
The `inject_bootstrap.py` `SessionStart` hook adds the full SKILL.md text so Claude can start with those instructions.

---

### Required plugin dependency: superpowers

Install `superpowers@claude-plugins-official` for these general development skills. See [Requirements](../README.md#requirements) and [installation instructions](../INSTALLATION.md).
Without that plugin, the skill names below do not resolve.

| Skill | Purpose |
|---|---|
| `superpowers:brainstorming` | Examine user intent, requirements, and design before creative work or implementation. |
| `superpowers:writing-plans` | Put implementation tasks in sequence. For each task, specify files, interfaces, small steps, and checks. |
| `superpowers:subagent-driven-development` | Use subagents in the current session for tasks in a plan that have no dependencies on each other. |
| `superpowers:dispatching-parallel-agents` | Send two or more tasks without dependencies to agents that can work in parallel. |
| `superpowers:executing-plans` | Use an isolated session to do the plan, with inspection checkpoints. |
| `superpowers:using-git-worktrees` | Set up an isolated workspace before feature work. Use native tools or a Git worktree. |
| `superpowers:requesting-code-review` | Get a code inspection and check the work against its requirements. |
| `superpowers:receiving-code-review` | Check the technical basis for each result before you apply it. |
| `superpowers:finishing-a-development-branch` | Select merge, PR, or cleanup after implementation and tests are complete. |
| `superpowers:systematic-debugging` | Examine the cause of a bug, a test error, or unexpected behavior before a repair. |
| `superpowers:test-driven-development` | Write the test first. Check that it gives the expected error. Write the minimum code for success, then refactor. |
| `superpowers:verification-before-completion` | Run checks and show their output before you claim success. |
| `superpowers:writing-skills` | Write, edit, and check skills before deployment. |

After the self-review gate, run `/coderails:planning-sequence` on the `superpowers:writing-plans` plan.
Do Pre-Parade, Premortem, and Red Team before `superpowers:subagent-driven-development` or `superpowers:executing-plans`.
Git ignores session plans in `docs/coderails/plans/` by the owner's 2026-07-11 decision.
An agentic loop keeps `plan.md` with `progress.json` in its external loop directory.

---

### Wiki skills

Claude maintains the LLM Wiki across sessions. Read it in Obsidian.

#### `wiki-init`

**Purpose:** Initialize an LLM Wiki for the current project.

**When to use it:** "wiki init", "create wiki", "knowledge base", "set up obsidian wiki", explicit `/wiki-init`. Also use it when the user mentions Karpathy's LLM Wiki pattern or `AGENTS.md`, or wants a knowledge base external to `CLAUDE.md`.

**When it does NOT apply:** Use the applicable skill when the user wants to query or update an existing wiki.

---

#### `wiki-ingest`

**Purpose:** Write or update wiki pages to document a merged PR, shipped feature, or engineering decision.

**When to use it:** "ingest this", "create wiki pages for this PR", "add to wiki", "document this in the wiki", "capture this change", "file this in the wiki". The user always has a concrete artifact to record.

**When it does NOT apply:** Use `wiki-query` to look up information.

---

#### `wiki-lint`

**Purpose:** Check the quality and structure of the project's LLM Wiki. Find contradictions, stale or orphaned pages, dead links, missing cross-references, and topics with missing pages.

**When to use it:** "wiki-lint", "lint the wiki", "wiki health check", find contradictions or stale content, find orphaned pages.

**When it does NOT apply:** Use `wiki-query` to look up a topic.

---

#### `wiki-query`

**Purpose:** Search, query, or look up information in the project's LLM Wiki. It can also make Marp slides or matplotlib charts from wiki material.

**When to use it:** "search wiki", "query wiki", "ask the wiki", "what does the wiki say", or a user who wants a project answer with wiki sources.

**When it does NOT apply:** General coding questions unrelated to wiki content, wiki maintenance (page changes, ingest, or lint), wiki initialisation.

---

### Engineering principles skills

These skills apply engineering principles and language standards to code changes.

#### `engineering-principles`

**Purpose:** Apply engineering principles (YAGNI, KISS, DRY, Fail Fast, SSOT, Law of Demeter) and language-specific coding standards across Python, Go, TypeScript, and Bash. Use LSP (Serena) to examine call sites and count uses. Select the language skill from the extension or, for a file without one, the shebang.

**When to use it:** Use after a code change or when the user invokes `/engineering-principles`. Example phrases are "enforce standards", "check principles", "apply standards", "code quality".

**When it does NOT apply:** Docs, config, or prose edits with no code to audit.

---

#### `engineering-principles-python`

**Purpose:** Apply Python standards to `.py` files. Use PEP 8 names, type hints, EAFP in preference to LBYL, context managers, and Pyright strict checks.

**When to use it:** Invoked by `engineering-principles` after detecting `.py` files, or directly for Python-only sessions.

---

#### `engineering-principles-go`

**Purpose:** Apply Go idioms and standards on `.go` files — accept interfaces, give callers structs, errors-as-values, table-driven tests, and idiomatic naming.

**When to use it:** Invoked by `engineering-principles` after detecting `.go` files, or directly for Go-only sessions.

---

#### `engineering-principles-ts`

**Purpose:** Apply TypeScript standards to `.ts` and `.tsx` files. Use strict mode, discriminated unions, optional chaining, and checks for all switch branches. Do not use `any`.

**When to use it:** Invoked by `engineering-principles` after detecting `.ts`/`.tsx` files, or directly for TypeScript-only sessions.

---

#### `engineering-principles-bash`

**Purpose:** Apply Bash standards to `.sh` files. Use the `set -euo pipefail` header unless the file is a sourced library or a hook that must degrade safely.
Put shell expansions in quotation marks and use `[[ ]]` in preference to `[ ]`. Do not use `eval`, word splitting, or unquoted globs.
Use `local` for function scope and check for subshell effects in command substitutions. Use `namespace::function` names to organize functions and run ShellCheck.

**When to use it:** `engineering-principles` invokes it for `.sh` files and files without extensions that have a `bash` or `sh` shebang. Invoke it directly for shell-only sessions.

---
