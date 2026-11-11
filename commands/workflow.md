---
allowed-tools: SlashCommand(/coderails:prep), SlashCommand(/coderails:push), SlashCommand(/pr-review-toolkit:review-pr), SlashCommand(/coderails:post-review), SlashCommand(/coderails:merge), SlashCommand(/wiki-ingest), SlashCommand(/wiki-lint), SlashCommand(/engineering-principles), SlashCommand(/engineering-principles-python), SlashCommand(/engineering-principles-go), SlashCommand(/engineering-principles-ts), SlashCommand(/engineering-principles-bash), SlashCommand(/simplify), Bash(git*), Bash(./worktree-add*), Bash(cat*)
argument-hint: <branch> "<description>"
description: Orchestrate the full feature workflow — prep → code → push → review → merge → wiki-ingest/lint
---

## Project config

Config: !`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lib/config.py" resolve-config`

If the config block above says `NO_CONFIG`, do NOT stop. Run in minimal mode:
- Skip Phase 2 (Orient/wiki-query) and Phase 5's wiki steps — `config.wiki_path` is null.
- Skip Phase 1's Jira creation because `config.jira` is null. Run /prep for the worktree.
- Skip the engineering-principles pre-flight — `config.engineering_principles_paths` is null.
- Worktree uses plain `git worktree add` off the git root.

In minimal mode, run prep for the worktree, then code, push, run reviewer checks, and merge.

## Raw arguments

```
$ARGUMENTS
```

## Purpose

This command runs the code-change workflow. Follow these rules:

- **Worktree before code**: make a worktree for each feature or bug branch. Do not edit on `main`.
- **Engineering-principles pre-flight**: run `config.engineering_principles_skill` before pushing. The default is `/engineering-principles-python`. Run it if the diff touches a path in `config.engineering_principles_paths` or a file has ≥20 lines changed.
- **Adversarial PR checks**: use `/pr-review-toolkit:review-pr`. It runs 4+ specialist agents in parallel. Do not start agents manually for this check.
- **Apply reviewer results inline**: if the user authorizes ship-it, apply blocking and worthwhile changes directly. Do not prompt again for each change.
- **Wiki after merge**: run `/wiki-ingest` after each merge if `config.wiki_path` is non-null. Run `/wiki-lint` immediately only if `config.wiki_git_worktree` is `false` (direct write). If the key is `true` or missing, run `/wiki-lint` after the ingest PR merges. See Phase 5.
- **Parallel tool calls**: when tool calls or file reads can run independently, issue them in parallel in one message.

Phase 2b checks the *design page* before coding. Phase 3 uses `/pr-review-toolkit:review-pr` to check the *code* before merge. Run the two checks for non-trivial features.

Pause for the developer during coding and iteration. Pause again for ship-it authorization before merge. Run the other steps in sequence: `review-pr → post-review → (Phase 4 ship-it pause) → /merge`.

## Parse Arguments

`$ARGUMENTS` contains what the user typed after `/workflow`. Read these fields:

1. Use the first token that matches `feature/*`, `bug/*`, or `bugfix/*` as the required **Branch name**. If none matches, get the branch name from the user.
2. Use the text after the branch name as the optional **Description**. If there is a `--summary "..."` flag, use that value. If there is no description, convert the branch name to plain language (`feature/foo-bar` → "Implement foo bar").

Accepted shapes (same as `/prep`):

```
/workflow feature/add-retry-logic
/workflow bug/fix-timeout --summary "Request timeout too short"
/workflow feature/my-feature "Add my-feature to the project"
```

If ambiguous, ask one targeted clarifying question — do not guess the branch name.

## Phase 1 — Prep (auto)

Invoke `/coderails:prep` with the parsed arguments. It does the work below.

- Make the worktree at `<config.worktree_base>-<description>`. Use `config.worktree_script` if set. If unset, use plain `git worktree add`.
- JIRA ticket creation (if `config.jira` is non-null): project `config.jira.project`, epic `config.jira.epic`, 1 story point, fix-version `config.jira.fix_version` (if set). Jira MCP tool namespace: `config.jira.mcp_namespace` (default: `jira`).
- Set the Jira status from `config.jira.transitions.start`, then from `config.jira.transitions.resolve`.
- Run `git config branch.<branch>.jira-ticket <KEY>` so `/push` can resolve the ticket automatically.

Report the worktree path and JIRA key (if created).

## Phase 2 — Orient (auto, before coding starts)

**Skip this phase if `config.wiki_path` is null.** If skipped, go directly to Phase 2b.

Before handing control to the user, run a **targeted wiki pre-flight** using `/wiki-query`:

```
/wiki-query "What does the wiki cover about [feature area derived from branch name]?
Identify: known constraints, open gaps, adjacent behaviour, superseded decisions.
Flag anything that looks like an assumption that is NOT enforced in code."
```

Use `/wiki-query` to read only the applicable pages and answer a targeted question. `/wiki-lint` audits the full vault for orphans and stale dates. That audit is too broad and slow for coding pre-flight.

What to look for in the response:
- **Risks in the design**: assumptions in the current implementation that this change can violate.
- **Missing constraints**: rules the wiki specifies that the code does not visibly enforce.
- **Adjacent behavior**: related features that interact with this feature and can change as a result.

If the query finds a problem worth recording:
1. File an investigation page (`investigations/<topic>_<YYYY-MM-DD>.md`) before coding starts. Do not wait for deploy.
2. Update `index.md` and `log.md`. Use a worktree as the wiki-ingest skill specifies.
3. Give the user a short summary before coding: "Before we start — I noticed X in the wiki. Is that intentional / in scope?"

If the query finds no problem, report "wiki clear" and hand control to the user.

**Do not skip this step.** A wiki query before coding can show issues that would only appear after deploy.

## Phase 2b — Design Adversarial Review (conditional, auto)

Run this phase before you hand control to the user if the design investigation page from Orient meets one or more of these conditions:

- ≥40 lines, OR
- spans >1 service (e.g. scheduler + app, app + notifier), OR
- introduces a new DDB schema or new feature flag pair, OR
- has an LLM call in the data path

If none of those apply, skip this phase and go straight to Code.

Start 2-3 agents in parallel in one message. Select agents for the parts of the design that the change touches. Do not use a fixed list by default.

| Part of the design | Agent to include |
|---|---|
| LLM call in the loop (prompt, taxonomy, category selection) | `prompt-engineer` |
| Cross-service data flow, DDB schema, PK design | `architect-reviewer` |
| User input → write path, Slack-interactive, auth surface | `security-auditor` |
| New async or concurrent patterns, how errors move through the system | `silent-failure-hunter` |
| New dependency-injection protocol or service registration pattern | `type-design-analyzer` |
| Novel test surface or integration boundary | `pr-test-analyzer` |

Select 2 or 3 agents. Give each agent the full design page. Give it questions and attack vectors for its area.

**After the agents report:**
1. List all reported issues.
2. Mark each result **accept** or **skip**. For **accept**, update the design page. For **skip**, record why inline.
3. Apply accepted changes to the investigation page and commit before coding starts.
4. Record skipped issues and why in the investigation page's "Adversarial review" section. Do not record them in memory.

**This phase checks the design before coding.** It finds schema defects, missing taxonomy categories, and issues at service boundaries. Repairs are easier before implementation. Run `/pr-review-toolkit:review-pr` when the PR opens to check the code.

## Phase 2 — Code (interactive pause)

Hand control back to the user. They will:

1. Point his editor at the worktree
2. Make the change with your help for as many turns as necessary.
3. Run the project's test suite during iteration and before pushing
4. Signal readiness with a phrase like *"push"*, *"ready to push"*, *"done coding"*, *"ship it"*

Wait for that signal before Phase 3. Do not prompt again.

**Pre-flight after the user's signal**: If `config.engineering_principles_paths` is non-null, check the cumulative diff against the base branch. Find files at configured paths and files with ≥20 lines changed. Run `config.engineering_principles_skill` on those files before `/push`. The default is `/engineering-principles-python`.

`/push` runs its own pre-flight on the paths in `config.engineering_principles_paths`. Run the check here too. The `/push` list excludes large diffs at unlisted paths.

## Phase 3 — Push + Adversarial Review (auto after ready signal)

Run these steps in sequence without a pause:

1. `/coderails:push` adds files to the index, commits, pushes, and opens the PR with branch-protection reviewers. If `config.jira` is non-null, it also resolves JIRA when the PR opens. Record the PR URL from the output.
2. `/pr-review-toolkit:review-pr <PR#>` runs the applicable specialists: code-reviewer, pr-test-analyzer, silent-failure-hunter, and type-design-analyzer. Use the PR number from `/coderails:push`. The hook requires it at the start of the arguments. Give the number alone to run all checks.

2b. Run `/engineering-principles` on the cumulative diff against the base branch. Apply the `/push` pre-flight rules. Deviations from documented architectural conventions block. Style notes do not block. Apply blocking changes in step 3.

2c. **Simplify**. Run the built-in `/simplify` command on the diff. The `review-pr` agent `code-simplifier` only runs "after passing review" and can be unavailable. Use the explicit pass and apply its changes through step 3.

3. Apply worthwhile changes inline. Do not prompt again for each change. Push the follow-up commit. Classify the results as follows:
   - **Blocking** (apply silently): bug, protocol violation, silent-failure pattern, missing test for a changed public contract, or missing dependency-injection registration.
   - **Worthwhile** (apply silently): readability wins, better names, extracted helpers that clearly reduce duplication
   - **Cosmetic/subjective** (skip, note in PR body): style preferences, naming opinions without a concrete defect
4. Post a ledger comment on the PR summarising what was applied vs. skipped and why.
5. Use `/coderails:post-review <PR#>` to post the SHA-bound artifact from the reviewer. The command writes the temporary reviewer output to a durable GitHub comment that `/merge` can check automatically. Post it after you apply the changes and push the follow-up commit. This binds the comment to the head SHA after the changes. The chain is `review-pr → (apply findings) → post-review → (Phase 4 ship-it pause) → /merge`.
6. Run `/coderails:task-evals` if the plan did not freeze evals in `superpowers:writing-plans` at "Freeze evals after stress-test, before implementation". Then run `/coderails:post-evals <PR#>` to post the eval artifact. `/merge` requires that artifact. The artifact does not satisfy the `enforce_pr_workflow` hook's `review-pr` requirement. The eval gate is in `merge.py`. The `PreToolUse` hook is a different check. See "What this command is NOT" below.

Report the PR URL, reviewer summary, and resolved JIRA key if applicable.

## Phase 4 — Ship-It (interactive pause)

Wait for the user's merge approval. Signals: *"ship it"*, *"merge"*, *"ok to merge"*, *"lgtm go"*.

While you wait, you can answer questions about reviewer results, help debug CI errors, act on reviewer comments, and push more commits. Wait for approval before Phase 5.

## Phase 5 — Merge + Wiki (auto after ship signal)

Run these steps in sequence:

1. `/coderails:merge` — merges the PR, switches back to `main`, pulls latest. Do not re-ask about merge strategy flags.
2. **If `config.wiki_path` is non-null**, run `/wiki-ingest`. It writes the source page to `<config.wiki_path>/sources/pr_<N>_*.md`, updates affected pages and the index, and appends to the log. Use the skill for all wiki page writes.
3. **If `config.wiki_path` is non-null and `config.wiki_git_worktree` is `false` (direct write)**, run `/wiki-lint`. It checks for contradictions, stale pages, orphans, and missing cross-references. Correct the issues directly related to this PR. Defer other issues.
   **If `config.wiki_git_worktree` is `true` or the config has no such key, wait for the wiki-ingest PR to merge before you run `/wiki-lint`.** Step 0 of wiki-ingest defaults to `true` for PR flow. `/wiki-lint` audits the merged vault on `origin/main`. An open ingest PR is not part of that audit. See Step 8 of wiki-ingest.

Report the merge commit SHA. If the project uses the wiki, report the wiki source page path. If lint ran, report issues for follow-up.

## Worktree cleanup

After Phase 5 completes and the PR is merged, clean up the worktree without asking first:

```bash
git worktree remove <worktree-path>
git branch -d <branch-name>
```

If `git branch -d` refuses because the branch is not fully merged into local `main`, investigate before you use `-D`. Do not force-delete to clear the refusal.

## Escape hatches

- **Docs-only change:** skip `/workflow` and edit directly on `main`. The `no_edit_on_main.py` hook blocks code files (`.py/.ts/.tsx/.js/.jsx/.go`) on `main`/`master`. In a plugin repo it also blocks Markdown plugin source (`skills/*/SKILL.md`, `commands/*.md`). The hook permits plain docs and config, such as README, `docs/*.md`, and JSON. It blocks edits to `SKILL.md` or a command `.md` on `main`. For a code or plugin-source hotfix, run `/coderails:prep` or use a `settings.json` Write/Edit permission override. The hook blocks a one-line change too.
- **Phase skip:** if the user says to skip a phase or go back to a phase, follow that instruction. The user can stop the sequence at each step.
- **Standalone sub-commands:** use a phase's command on its own when necessary. These commands are `/coderails:prep`, `/coderails:push`, `/pr-review-toolkit:review-pr`, `/coderails:merge`, `/wiki-ingest`, and `/wiki-lint`. `/coderails:workflow` runs the usual sequence.

## What this command is NOT

- Slash commands are advisory. Claude decides when to invoke them. `PreToolUse` hooks do the mechanical checks. `enforce_pr_workflow.py` blocks `gh pr create` unless `/coderails:push` ran in this session. It blocks `gh pr merge` unless `/pr-review-toolkit:review-pr` ran in this session.
- This command invokes `/coderails:task-evals` and `/coderails:post-evals` in Phase 3, step 6. `scripts/merge.py` checks evals when `/coderails:merge` runs. The `PreToolUse` hooks above do other checks.
- Read CLAUDE.md too. The project rules in `projects/<name>/CLAUDE.md` are authoritative.
- If the user gives no branch name, prompt one time. Do not invent a name.
