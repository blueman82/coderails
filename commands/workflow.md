---
allowed-tools: SlashCommand(/coderails:prep), SlashCommand(/coderails:push), SlashCommand(/pr-review-toolkit:review-pr), SlashCommand(/coderails:post-review), SlashCommand(/coderails:merge), SlashCommand(/wiki-ingest), SlashCommand(/wiki-lint), SlashCommand(/engineering-principles), SlashCommand(/engineering-principles-python), SlashCommand(/engineering-principles-go), SlashCommand(/engineering-principles-ts), SlashCommand(/simplify), Bash(git*), Bash(./worktree-add*), Bash(cat*)
argument-hint: <branch> "<description>"
description: Orchestrate the full feature workflow — prep → code → push → review → merge → wiki-ingest/lint
---

## Project config

Config: !`source "${CLAUDE_PLUGIN_ROOT}/scripts/lib/config.sh" && coderails::resolve_config`

If the config block above says `NO_CONFIG`, do NOT stop. Run in minimal mode:
- Skip Phase 2 (Orient/wiki-query) and Phase 5's wiki steps — `config.wiki_path` is null.
- Skip Phase 1's Jira creation — `config.jira` is null. /prep still runs for the worktree.
- Skip the engineering-principles pre-flight — `config.engineering_principles_paths` is null.
- Worktree uses plain `git worktree add` off the git root.

The workflow collapses to: prep (worktree only) → code → push → review → merge.

## Raw arguments

```
$ARGUMENTS
```

## Purpose

This command is the umbrella for the canonical code-change workflow. The rules it encodes:

- **Worktree before code**: create a worktree for every feature/bug branch — never edit on main
- **Engineering-principles pre-flight**: run `config.engineering_principles_skill` (default: `/engineering-principles-python`) before pushing if the diff touches paths listed in `config.engineering_principles_paths` (or any file with ≥20 lines changed)
- **Adversarial PR review**: use `/pr-review-toolkit:review-pr`, not manual Agent fan-out — runs 4+ specialist agents in parallel
- **Apply findings inline**: on authorized ship-it, apply blocking and worthwhile review findings directly; do not re-ask per finding
- **Wiki after merge**: after every merge run BOTH `/wiki-ingest` AND `/wiki-lint` (if `config.wiki_path` is non-null)
- **Parallel tool calls**: when multiple tool calls or file reads have no dependency between them, issue them in parallel in a single message — not sequentially. Never serialize work that can run concurrently.

Phase 2b (design adversarial review) is distinct from Phase 3 (`/pr-review-toolkit:review-pr`): Phase 2b reviews the *design page* before coding, Phase 3 reviews the *code* before merge. Both are required on non-trivial features.

The workflow has two interactive pauses where the developer drives: (a) the code/iterate loop, (b) the final ship-it authorization. Everything else auto-chains. The Phase 3 review chain runs in order: `review-pr → post-review → (Phase 4 ship-it pause) → /merge`.

## Parse Arguments

`$ARGUMENTS` is whatever the user typed after `/workflow`. Extract:

1. **Branch name** (required). First token matching `feature/*`, `bug/*`, `bugfix/*`. If absent, ask for it.
2. **Description** (optional). Everything after the branch name, or the `--summary "..."` flag if present. If absent, humanise the branch name (`feature/foo-bar` → "Implement foo bar").

Accepted shapes (same as `/prep`):

```
/workflow feature/add-retry-logic
/workflow bug/fix-timeout --summary "Request timeout too short"
/workflow feature/my-feature "Add my-feature to the project"
```

If ambiguous, ask one targeted clarifying question — do not guess the branch name.

## Phase 1 — Prep (auto)

Invoke `/coderails:prep` with the parsed args. It handles:

- Worktree creation at `<config.worktree_base>-<description>` (via `config.worktree_script` if set, otherwise plain `git worktree add`)
- JIRA ticket creation (if `config.jira` is non-null): project `config.jira.project`, epic `config.jira.epic`, 1 story point, fix-version `config.jira.fix_version` (if set). Jira MCP tool namespace: `config.jira.mcp_namespace` (default: `jira`).
- Transition to `config.jira.transitions.start` → `config.jira.transitions.resolve`
- `git config branch.<branch>.jira-ticket <KEY>` so `/push` can auto-resolve later

Report the worktree path and JIRA key (if created).

## Phase 2 — Orient (auto, before coding starts)

**Skip this phase if `config.wiki_path` is null.** If skipped, go directly to Phase 2b.

Before handing control to the user, run a **targeted wiki pre-flight** using `/wiki-query`:

```
/wiki-query "What does the wiki cover about [feature area derived from branch name]?
Identify: known constraints, open gaps, adjacent behaviour, superseded decisions.
Flag anything that looks like an assumption that is NOT enforced in code."
```

This is `/wiki-query`, not `/wiki-lint`. `/wiki-lint` is a full-vault audit (orphans, stale dates) — wrong scope and too slow at coding time. `/wiki-query` reads only relevant pages and answers a targeted question.

What to look for in the response:
- **Design gaps**: assumptions baked into the current implementation that this change might violate
- **Missing constraints**: things the wiki says should be true that aren't visibly enforced
- **Adjacent behaviour**: related features that interact with this one and could be affected

If the query surfaces a gap worth preserving:
1. File an investigation page now (`investigations/<topic>_<YYYY-MM-DD>.md`) before coding starts — not after deploy
2. Update `index.md` and `log.md` (use a worktree per the wiki-ingest skill)
3. Surface findings to the user as a short pre-coding brief: "Before we start — I noticed X in the wiki. Is that intentional / in scope?"

If no gap found, report "wiki clear" and hand control to the user.

**Do not skip this step.** Runtime discoveries (post-deploy surprises) are often detectable from the wiki before a line is written.

## Phase 2b — Design Adversarial Review (conditional, auto)

Run **before handing control to the user** if the design investigation page filed in Orient meets any of these triggers:

- ≥40 lines, OR
- spans >1 service (e.g. scheduler + app, app + notifier), OR
- introduces a new DDB schema or new feature flag pair, OR
- any LLM call in the data path

If none of those apply, skip this phase and go straight to Code.

**How to run**: launch 2-3 agents in a single message (parallel). Select agents based on what the design actually touches — do not default to a fixed list:

| Design element | Agent to include |
|---|---|
| LLM call in the loop (prompt, taxonomy, classification) | `prompt-engineer` |
| Cross-service data flow, DDB schema, PK design | `architect-reviewer` |
| User input → write path, Slack-interactive, auth surface | `security-auditor` |
| New async/concurrent patterns, error propagation | `silent-failure-hunter` |
| New dependency-injection protocol or service registration pattern | `type-design-analyzer` |
| Novel test surface or integration boundary | `pr-test-analyzer` |

Always pick at least 2. Cap at 3. Brief each agent with the full design investigation page content + the specific sub-questions most relevant to its expertise (not just "review this" — give it attack vectors).

**After the agents report:**
1. Enumerate every finding — do not skip any.
2. Classify each as: **accept** (update design page) / **skip** (record reason inline).
3. Apply accepted changes to the investigation page and commit before coding starts.
4. Log skipped findings with rationale — in the investigation page's "Adversarial review" section, not in memory.

**This is design review, not code review.** It catches schema flaws, taxonomy gaps, and service-boundary issues that are cheap to fix now and expensive mid-implementation. The PR-time `/pr-review-toolkit:review-pr` is separate and still required.

## Phase 2 — Code (interactive pause)

Hand control back to the user. They will:

1. Point his editor at the worktree
2. Implement the change (with your help across any number of turns)
3. Run the project's test suite during iteration and before pushing
4. Signal readiness with a phrase like *"push"*, *"ready to push"*, *"done coding"*, *"ship it"*

Do not proceed to Phase 3 until the user gives that signal. Do not nag.

**Pre-flight when the user signals ready:** if `config.engineering_principles_paths` is non-null and the cumulative diff against the base branch touches any of those paths — or any file with ≥20 lines changed — run `config.engineering_principles_skill` (default: `/engineering-principles-python`) on those files before calling `/push`.

Note: `/push` already runs this pre-flight itself for paths in `config.engineering_principles_paths`, so if you forget, `/push` will catch it. The reason to also run it here is to catch non-config-listed large diffs that `/push`'s pre-flight misses.

## Phase 3 — Push + Adversarial Review (auto after ready signal)

Execute in order — do not pause between these:

1. `/coderails:push` — stages, commits, pushes, opens PR with branch-protection reviewers, auto-resolves JIRA on PR creation (if `config.jira` non-null). Capture the PR URL from the output.
2. `/pr-review-toolkit:review-pr all` — runs the four specialist agents (code-reviewer, pr-test-analyzer, silent-failure-hunter, type-design-analyzer) in parallel.
2b. **Verify engineering principles** — run `/engineering-principles` on the cumulative diff against the base branch. Apply the same rule as `/push`'s pre-flight: deviations from documented architectural conventions are blocking; style notes are non-blocking. Feed any blocking finding into step 3's apply loop.
2c. **Simplify** — run `/simplify` on the diff (built-in command). `review-pr`'s own `code-simplifier` agent only runs "after passing review" and is not guaranteed, so this is the explicit simplify pass; route its changes through step 3.
3. Apply worthwhile findings inline — do not re-ask per finding. Push the follow-up commit. Classify each finding as:
   - **Blocking** (apply silently): correctness bug, protocol violation, silent-failure pattern, missing test for changed public contract, missing dependency-injection registration
   - **Worthwhile** (apply silently): readability wins, better names, extracted helpers that clearly reduce duplication
   - **Cosmetic/subjective** (skip, note in PR body): style preferences, naming opinions without a concrete defect
4. Post a ledger comment on the PR summarising what was applied vs. skipped and why.
5. `/coderails:post-review <PR#>` — post the SHA-bound review artifact on the PR. This converts the ephemeral review output into a durable, machine-verifiable GitHub comment that `/merge` requires before merging. Run this after all findings are applied and the follow-up commit is pushed, so the artifact is stamped against the final head SHA. The chain is: `review-pr → (apply findings) → post-review → (Phase 4 ship-it pause) → /merge`.

Report the PR URL, review summary, and resolved JIRA key (if applicable).

## Phase 4 — Ship-It (interactive pause)

Wait for the user to approve the merge. Signals: *"ship it"*, *"merge"*, *"ok to merge"*, *"lgtm go"*.

While waiting, you may: answer review questions, help debug CI failures, iterate on review comments, push additional commits. Do NOT proceed to Phase 5 autonomously.

## Phase 5 — Merge + Wiki (auto after ship signal)

Execute in order:

1. `/coderails:merge` — merges the PR, switches back to `main`, pulls latest. Do not re-ask about merge strategy flags.
2. **If `config.wiki_path` is non-null**: `/wiki-ingest` — creates the source page in `<config.wiki_path>/sources/pr_<N>_*.md`, updates affected wiki pages, refreshes the index, appends to the log. Never write wiki pages directly — always use the skill.
3. **If `config.wiki_path` is non-null**: `/wiki-lint` — checks for contradictions, stale pages, orphans, missing cross-references. Fix anything directly related to this PR; defer anything else.

Report: merge commit SHA, wiki source page path (if wiki enabled), any lint findings that need follow-up.

## Worktree cleanup

After Phase 5 completes and the PR is merged, clean up the worktree without asking first:

```bash
git worktree remove <worktree-path>
git branch -d <branch-name>
```

If `git branch -d` refuses because the branch is not fully merged into local `main`, investigate before using `-D`. Don't force-delete to make the refusal go away.

## Escape hatches

- **Docs-only change:** skip `/workflow` and edit on `main` directly. The `no_edit_on_main.sh` hook blocks code files (`.py/.ts/.tsx/.js/.jsx/.go`) on `main`/`master`, plus plugin source carried in markdown (`skills/*/SKILL.md`, `commands/*.md`) when you're in a plugin repo — so *plain* docs and config (README, `docs/*.md`, JSON) pass freely, but editing a `SKILL.md` or a command `.md` on `main` is blocked. A one-line *code* (or plugin-source) hotfix still needs a branch (run `/coderails:prep`) or a `settings.json` Write/Edit permission override — the hook blocks regardless of size.
- **Phase skip:** The user can interrupt at any time and tell you to skip a specific phase or re-enter a prior phase. Obey; don't argue for the canonical sequence.
- **Standalone sub-commands:** every phase's sub-command (`/coderails:prep`, `/coderails:push`, `/pr-review-toolkit:review-pr`, `/coderails:merge`, `/wiki-ingest`, `/wiki-lint`) remains callable on its own for edge cases. `/coderails:workflow` is the happy path, not the only path.

## What this command is NOT

- Not enforcement. Slash commands are advisory — Claude has to choose to invoke them. Mechanical enforcement belongs in `PreToolUse` hooks: `enforce_pr_workflow.sh` blocks `gh pr create` unless `/coderails:push` ran this session, and blocks `gh pr merge` unless `/pr-review-toolkit:review-pr` ran this session.
- Not a replacement for reading CLAUDE.md. This command encodes the workflow; the authoritative spec for project-specific standards still lives in `projects/<name>/CLAUDE.md`.
- Not interactive for the branch name. If the user doesn't provide a branch, ask once — don't invent one.
