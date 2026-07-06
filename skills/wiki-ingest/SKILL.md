---
name: wiki-ingest
description: "Use this skill when the user wants wiki pages created or updated to document a change — a merged PR, shipped feature, or engineering decision. The user always has an artifact to record (PR number, description, decision) and wants it written into the project's LLM Wiki as permanent documentation. Trigger on any request to push content into the wiki: 'ingest this', 'create wiki pages for this PR', 'add to wiki', 'document this in the wiki', 'capture this change', 'file this in the wiki'."
---

# Wiki Ingest

Ingest a new source into the project's LLM Wiki. A single source typically touches 3-15 wiki pages depending on project size.

## Instructions

### Step 0: Load the Schema

`AGENTS.md` at the project's git root is loaded into context at session start (per the project's `CLAUDE.md`) — use that content. If it isn't present in context (e.g. a fresh fork with no prior context), read `AGENTS.md` at the git repository root directly, not the current working directory — a fork's cwd may be a subdirectory. If it doesn't exist there either, tell the user to run `/wiki-init` first.

This is the single source of truth for:
- `vault` — absolute path to the wiki vault
- `git.worktree` — whether to use git worktree/PR flow (`true`) or write directly (`false`)
- `git.bypass_flag` — env var to set when creating/merging PRs (e.g. `BYPASS_REVIEW=1`)
- `git.pull_path` — path to pull after merge

**Example AGENTS.md git section (team repo with PR flow):**
```yaml
git:
  worktree: true
  bypass_flag: BYPASS_REVIEW=1
  pull_path: /path/to/your/source-repo
```

**Example AGENTS.md git section (personal wiki, no PR ceremony):**
```yaml
git:
  worktree: false
```

### Step 1: Set Up Workspace

**If `git.worktree` is `true`** (team repos — prevents parallel session conflicts):
```bash
BRANCH="chore/wiki-$(date +%Y%m%d-%H%M%S)"
WORKTREE_PATH="${vault}-worktree-$(date +%Y%m%d-%H%M%S)"
git -C "$vault" worktree add -b "$BRANCH" "$WORKTREE_PATH" origin/main
# All file writes target WORKTREE_PATH
```

**If `git.worktree` is `false`** (personal wikis — write directly):
```bash
# Write directly to vault path — no worktree needed
WORKTREE_PATH="$vault"
```

### Step 2: Read the Source

**From inbox file**: Read `$vault/inbox/<filename>` directly.

**From PR number**: `gh pr view <number> --json title,body,files,mergedAt` and `gh pr diff <number>`.

**From description**: Ask which files changed, or use `git log` to find relevant commits.

### Step 3: Discuss Key Takeaways

Before writing anything, discuss with the user:
- What are the key changes / main ideas?
- What should the wiki emphasise?
- Are there decisions or patterns worth capturing?
- Does this relate to existing wiki pages?

Don't auto-ingest silently. The human stays involved.

### Step 4: Check What's Already Known

Read `$vault/index.md`. Before adding content, check existing coverage. Curator principle: add only what's new and non-obvious.

### Step 5: Write/Update Pages

1. **Source page** in `$vault/sources/` — YAML frontmatter (title, type, origin, date, tags), key takeaways, context, impact
2. **Update affected pages** — concept, entity, service pages as needed. Update `last_updated` in frontmatter
3. **Create new pages** if the source introduces something deserving its own page. Use `[[wiki-links]]`
4. **Update `$vault/index.md`** — new entries, updated summaries, source table
5. **Append to `$vault/log.md`**: `## [YYYY-MM-DD] ingest | <description>`

Cross-reference aggressively with `[[wiki-links]]`. Flag contradictions: `> ⚠️ CONTRADICTION: <description>`.

### Step 6: Commit

**If `git.worktree` is `true`**:
```bash
cd "$WORKTREE_PATH"
git add -A
git commit -m "wiki: ingest <description>"
git push -u origin "$BRANCH"
${git.bypass_flag} gh pr create --title "wiki: ingest <description>" --body "Pages created/updated: <list>"
${git.bypass_flag} gh pr merge --squash --delete-branch
# Note: enforce_pr_workflow gates `gh pr create`/`gh pr merge` only in a repo that has a
# workflow.config.yaml (a wiki vault usually has none → no-op). When it does apply, the
# satisfier is /coderails:push (create) or /pr-review-toolkit:review-pr (merge) having run
# this session, or a settings.json Bash permission. ${git.bypass_flag} is the wiki's own
# delivery bypass, separate from that hook.
git -C "${git.pull_path}" pull
git -C "$vault" worktree remove "$WORKTREE_PATH"
```

**If `git.worktree` is `false`**:
```bash
cd "$vault"
git add -A
git commit -m "wiki: ingest <description>"
```

### Step 7: Report

Pages created/updated, new wiki-links added, gaps identified. If worktree flow: include PR URL.
