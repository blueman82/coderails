---
name: wiki-ingest
description: "Use this skill when the user wants wiki pages created or updated to document a change — a merged PR, shipped feature, or engineering decision. The user always has an artifact to record (PR number, description, decision) and wants it written into the project's LLM Wiki as permanent documentation. Trigger on any request to push content into the wiki: 'ingest this', 'create wiki pages for this PR', 'add to wiki', 'document this in the wiki', 'capture this change', 'file this in the wiki'."
context: fork
agent: coderails:wiki-writer
background: false
argument-hint: <PR# | description of the change to record>
model: sonnet
---

# Wiki Ingest

Add a new source to the project's LLM Wiki. One source usually changes 3–15 wiki pages. The number depends on how large the project is.

**Source:** $ARGUMENTS

This skill runs in a forked context with no access to the conversation that
invoked it. If the line above is empty, this skill got no source. Report that and stop.

## Instructions

### Step 0: Load the Schema

At session start, read the project's Git-root `AGENTS.md` as directed by its `CLAUDE.md`. Use it for conventions. For page types, page format, and the three layers, follow the link to `AGENTS-wiki-schema.md` in `AGENTS.md`. Read the full schema.

If the fork has no `AGENTS.md` in context, look in the current directory and its parents up to the Git root. Use the same pattern as `config_path` in `scripts/lib/config.py`. A fork can start in a subdirectory, so check the path to `AGENTS.md`. If you do not find `AGENTS.md` by the Git root, tell the user to run `/wiki-init` first.

Use the project's `AGENTS.md`. The wiki vault is a sibling repo such as `../coderails-wiki`. The project config `.coderails/workflow.config.yaml` points to it. You can run the fork from the project repo.

Get the Git, vault, and supervision settings from flat keys in the source project’s `.coderails/workflow.config.yaml`. This is the project where you found `AGENTS.md`. Follow the same pattern as `config_path` in `scripts/lib/config.py`.

From the project repo location, check each directory up to its Git root for `.coderails/workflow.config.yaml`. Use the first file you find.

- `wiki_path` gives the wiki vault path. If it is relative, resolve it from the directory with that `workflow.config.yaml`. Use `vault` for this value below.
- `wiki_git_worktree` selects a Git worktree and PR (`true`) or direct writes (`false`). If the config has no such key, use **`true`**. This prevents direct writes to a vault that expects approval through a PR.
- `wiki_git_bypass_flag` — env var to set when creating/merging PRs (e.g. `BYPASS_REVIEW=1`)
- `wiki_git_pull_path` — path to `git pull` from after a human merges the ingest PR (this
  skill no longer merges or pulls itself — see Step 6). Default when missing: no pull path is
  suggested in Step 7's report.
- `wiki_supervision` — `discuss` (default) or `autonomous`. See Step 3.

**Example `.coderails/workflow.config.yaml` (team repo with PR flow):**
```yaml
wiki_path: ../my-project-wiki
wiki_git_worktree: true
wiki_git_bypass_flag: BYPASS_REVIEW=1
wiki_git_pull_path: /path/to/your/source-repo
```

**Example `.coderails/workflow.config.yaml` (personal wiki, no PR ceremony, autonomous curation):**
```yaml
wiki_path: ../my-project-wiki
wiki_git_worktree: false
wiki_supervision: autonomous   # opt into autonomous curation
```
If no config file resolves, or it resolves but has no `wiki_supervision` key, or the key
is set to anything other than `autonomous`, treat it as `discuss` — the field must be
explicitly set to `autonomous` to skip Step 3's pause. Do not infer autonomy from context,
momentum, or a prior authorization earlier in the same turn.

Set `vault` to the resolved `wiki_path` for the remaining steps.

### Step 1: Set Up Workspace

**If `wiki_git_worktree` is `true`** (team repos — isolates writes from parallel sessions):
```bash
BRANCH="chore/wiki-$(date +%Y%m%d-%H%M%S)"
WORKTREE_PATH="${vault}-worktree-$(date +%Y%m%d-%H%M%S)"
git -C "$vault" worktree add -b "$BRANCH" "$WORKTREE_PATH" origin/main
# All file writes target WORKTREE_PATH
```

**If `wiki_git_worktree` is `false`** (personal wikis — write directly):
```bash
# Write directly to vault path — no worktree needed
WORKTREE_PATH="$vault"
```

### Step 2: Read the Source

**From inbox file**: Read `$vault/inbox/<filename>` directly.

**From PR number**: `gh pr view <number> --json title,body,files,mergedAt` and `gh pr diff <number>`.

**From description**: Ask which files changed, or use `git log` to find related commits.

### Step 3: Discuss Key Takeaways (unless `wiki_supervision: autonomous`)

**If `wiki_supervision` (from the project's `.coderails/workflow.config.yaml`, see Step 0) is
`autonomous`:** skip straight to Step 4. Curate and commit without pausing — that is what this
setting means. The `autonomous` setting applies to the full wiki update. Do not add a confirmation checkpoint before the commit in Step 6.

**If not (the default — `discuss`, the field missing, or no config file resolved):** before
writing anything, discuss
with the user:
- What are the key changes or ideas?
- What should the wiki emphasise?
- Are there decisions or patterns worth capturing?
- Does this relate to pages in the wiki?

Discuss the wiki content with the user before you continue. Approval for a code change, PR, or merge in this turn does not satisfy this step.

### Step 4: Check What's Already Known

Read `$vault/index.md`. Before adding content, check existing coverage. Curator principle: add only what's new and non-obvious.

### Step 5: Write/Update Pages

1. **Source page** in `$vault/sources/` — YAML frontmatter (title, type, source, date, tags), key takeaways, context, and effects
2. **Update affected pages** — concept, entity, service pages as needed. Update `last_updated` in frontmatter
3. **Make new pages** if the source introduces something deserving its own page. Use `[[wiki-links]]`
4. **Update `$vault/index.md`** — new entries, updated summaries, source table
5. **Append to `$vault/log.md`**: `## [YYYY-MM-DD] ingest | <description>`

Cross-reference aggressively with `[[wiki-links]]`. Flag contradictions: `> ⚠️ CONTRADICTION: <description>`.

### Step 6: Commit

**If `wiki_git_worktree` is `true`**:
```bash
cd "$WORKTREE_PATH"
git add -A
git commit -m "wiki: ingest <description>"
git push -u origin "$BRANCH"
${wiki_git_bypass_flag} gh pr create --title "wiki: ingest <description>" --body "Pages created/updated: <list>"
# STOP here. Do not merge the PR — not in interactive, autonomous, or
# backgrounded/detached execution. wiki-ingest does not merge its own PR. Report
# the PR URL/number back (Step 7) and end. A human, or an explicit different
# follow-up instruction, merges it.
# WORKTREE_PATH is deliberately left on disk here — it holds the branch backing
# the open PR above. If you remove it at this point, you remove work for that PR. Report its path in Step 7.
# After the merge, the person who merged the PR removes it with this command:
#   git -C "$vault" worktree remove "$WORKTREE_PATH"
# enforce_pr_workflow gates `gh pr create` only in a repo that has a
# workflow.config.yaml (a wiki vault usually has none → no-op). When it does apply, the
# satisfier is /coderails:push having run this session, or a settings.json Bash permission.
# The wiki uses ${wiki_git_bypass_flag} when it publishes a PR. The flag operates independently of that hook.
```

**If `wiki_git_worktree` is `false`**:
```bash
cd "$vault"
git add -A
git commit -m "wiki: ingest <description>"
```

### Step 7: Report

Report the pages changed, new wiki links, and missing parts. **For worktree flow, report the PR URL or number and stop.** This skill does not merge the PR. A human or an explicit follow-up instruction handles that step. Also report `WORKTREE_PATH` and the Step 6 cleanup command.

### Step 8: Run wiki-lint

**If `wiki_git_worktree` is `false` (direct-write), run `coderails:wiki-lint` immediately after the wiki update.** It checks new and updated pages. The update and lint are one mandatory step.

For multiple PRs in one loop, `agentic-loop` runs the lint for the cluster. When you invoke this skill on its own, run the lint immediately after the update.

**If `wiki_git_worktree` is `true` (PR flow), wait to run wiki-lint.** The ingest PR is open. `wiki-lint` reads merged `origin/main`, which does not contain the new pages before the merge. Run `coderails:wiki-lint` after the ingest PR merges.
