---
name: wiki-ingest
description: "Use this skill when the user wants wiki pages created or updated to document a change — a merged PR, shipped feature, or engineering decision. The user always has an artifact to record (PR number, description, decision) and wants it written into the project's LLM Wiki as permanent documentation. Trigger on any request to push content into the wiki: 'ingest this', 'create wiki pages for this PR', 'add to wiki', 'document this in the wiki', 'capture this change', 'file this in the wiki'."
---

# Wiki Ingest

Add a new source to the project's LLM Wiki. A single source usually changes 3–15 wiki pages, depending on the project.

**Source:** $ARGUMENTS

If the source above is empty, report that and stop. Do not guess which artifact to record.

Start the installed `wiki-writer` custom agent with `spawn_agent`.
Give it the source and project location in a self-contained prompt.
Collect its result with `wait_agent`. Use `send_input` only if you can name a missing check.
Then use `close_agent`.

## Instructions

### Step 0: Load the Schema

At session start, Codex reads the project root's `AGENTS.md` into context. Use that file for project instructions.
Read its linked `AGENTS-wiki-schema.md` for the full schema, which defines page types, page format, and the three layers.

If the context does not contain `AGENTS.md`, start at the current directory and check each parent up to the Git root.
If you find no `AGENTS.md`, tell the user to invoke `$coderails-codex:wiki-init` first.
The vault is a sibling repository, for example `../coderails-wiki`. Find `AGENTS.md` in the project repository.
The session can use the vault from the project directory.

Read the flat keys below from `.coderails/workflow.config.yaml` in the project that owns the source, where you found `AGENTS.md`.
Check for that config from the project repository location up to its Git root. Use the first config you find.

- `wiki_path` — the vault path. If relative, resolve it from the directory containing `workflow.config.yaml`.
  Use that value for `vault` below.
- `wiki_git_worktree` — worktree/PR flow (`true`) or direct writes (`false`).
  If there is no setting, use `true` so changes go through a PR before a commit goes into the vault.
- `wiki_git_bypass_flag` — environment assignment for PR creation or merge (e.g. `BYPASS_REVIEW=1`)
- `wiki_git_pull_path` — directory for `git pull` after a person merges the ingest PR.
  This skill does not merge or pull (see Step 6).
  If there is no setting, give no pull path in Step 7.
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
If the config explicitly sets `wiki_supervision` to `autonomous`, skip Step 3's pause.
If the file or key is unavailable, or the key has a different value, use `discuss`.
Do not infer autonomy from context, momentum, or earlier authorization in the same turn.

### Step 1: Set Up Workspace

**If `wiki_git_worktree` is `true`** (team repositories, to isolate parallel sessions):
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

**From description**: Get the changed file names from the user, or use `git log` to find related commits.

### Step 3: Discuss Key Takeaways (unless `wiki_supervision: autonomous`)

**If the project's `.coderails/workflow.config.yaml` sets `wiki_supervision` to `autonomous` (Step 0):** Go to Step 4.
Curate and commit without pausing. Do not add a confirmation step before Step 6's commit.
`autonomous` applies to the full ingest.

**If Step 0 selects `discuss`:** Discuss these points with the user before you write:

- What are the key changes or primary ideas?
- What should the wiki emphasise?
- Are there decisions or patterns worth capturing?
- Which wiki pages include a related topic?

In `discuss` mode, discuss the wiki content with the user before you add it.
Approval earlier in the same turn for the code change, PR, or merge does not satisfy this step.

### Step 4: Check What's Already Known

Read `$vault/index.md` and check existing coverage before you add content.
Add only new information that is not obvious.

### Step 5: Write/Update Pages

1. **Source page** in `$vault/sources/`. Give YAML frontmatter with `title`, `type`, `origin`, `date`, and `tags`.
   Give the key takeaways, context, and effect.
2. **Update pages** for concepts, entities, and services as necessary. Update `last_updated` in frontmatter
3. **Make new pages** if the source introduces something deserving its own page. Use `[[wiki-links]]`
4. **Update `$vault/index.md`** — new entries, updated summaries, source table
5. **Append to `$vault/log.md`**: `## [YYYY-MM-DD] ingest | <description>`

Use `[[wiki-links]]` to connect the related pages. Flag contradictions with `> ⚠️ CONTRADICTION: <description>`.

### Step 6: Commit

**If `wiki_git_worktree` is `true`**:
```bash
cd "$WORKTREE_PATH"
git add -A
git commit -m "wiki: ingest <description>"
git push -u origin "$BRANCH"
${wiki_git_bypass_flag} gh pr create --title "wiki: ingest <description>" --body "Pages created/updated: <list>"
# STOP here. Do not merge the PR in interactive, autonomous, background, or detached mode.
# Report the PR URL or number (Step 7) and end. A person or explicit follow-up instruction handles the merge.
# Keep WORKTREE_PATH on disk. It holds the branch for the open PR.
# Report its path in Step 7. The person or session that merges the PR removes it after the merge with:
#   git -C "$vault" worktree remove "$WORKTREE_PATH"
# enforce_pr_workflow gates `gh pr create` only in a repository with workflow.config.yaml.
# A wiki vault usually has no such file, so the hook does nothing there.
# If the hook applies, invoke `$coderails-codex:push` in this session or get explicit Bash permission.
# The wiki uses ${wiki_git_bypass_flag} for its own publication bypass independently of the hook.
```

**If `wiki_git_worktree` is `false`**:
```bash
cd "$vault"
git add -A
git commit -m "wiki: ingest <description>"
```

### Step 7: Report

Report the pages you made or updated, new wiki links, and missing coverage.

**For worktree flow, report the PR URL or number and stop.**
This skill does not merge the PR. A person or an explicit follow-up
instruction handles the merge. Also report `WORKTREE_PATH` and the cleanup
command from Step 6.

### Step 8: Run wiki-lint

**If `wiki_git_worktree` is `false` (direct-write), run `$coderails-codex:wiki-lint` immediately after ingest.**
The write and lint steps are mandatory. Lint checks the new and updated pages.
If `agentic-loop` ingests multiple PRs, it can lint the cluster together. If you invoke this skill alone, lint immediately.

**If `wiki_git_worktree` is `true` (PR flow), wait to run wiki-lint.**
The ingest PR from Step 6 stays open.
`wiki-lint` checks the vault's `origin/main`, which does not include pages from an open PR.
Invoke `$coderails-codex:wiki-lint` as a follow-up after the ingest PR merges.
