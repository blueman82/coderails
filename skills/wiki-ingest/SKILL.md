---
name: wiki-ingest
description: "Use this skill when the user wants wiki pages created or updated to document a change — a merged PR, shipped feature, or engineering decision. The user always has an artifact to record (PR number, description, decision) and wants it written into the project's LLM Wiki as permanent documentation. Trigger on any request to push content into the wiki: 'ingest this', 'create wiki pages for this PR', 'add to wiki', 'document this in the wiki', 'capture this change', 'file this in the wiki'."
---

# Wiki Ingest

Ingest a new source into the project's LLM Wiki. A single source typically touches 3-15 wiki pages depending on project size.

## Instructions

### Step 0: Load the Schema

`AGENTS.md` at the project's git root is loaded into context at session start (per the project's `CLAUDE.md`) — use that content. If it isn't present in context (e.g. a fresh fork with no prior context), do not assume cwd: walk up from the current directory, checking each level for `AGENTS.md`, up to the git repository root (same pattern as `coderails::config_path` in `scripts/lib/config.sh`) — a fork's cwd may be a subdirectory of the project repo. If no `AGENTS.md` is found by the git root, tell the user to run `/wiki-init` first. (The wiki vault itself, e.g. `../coderails-wiki`, is a separate sibling repo the project's `AGENTS.md` points to by absolute path — it is not where `AGENTS.md` lives, and a fork should never need to be running from inside it.)

This is the single source of truth for:
- `vault` — absolute path to the wiki vault
- `git.worktree` — whether to use git worktree/PR flow (`true`) or write directly (`false`)
- `git.bypass_flag` — env var to set when creating/merging PRs (e.g. `BYPASS_REVIEW=1`)
- `git.pull_path` — path to pull after merge
- `wiki.supervision` — `discuss` (default when absent) or `autonomous`; see Step 3

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

**Example AGENTS.md wiki supervision section (opt into autonomous curation):**
```yaml
wiki:
  supervision: autonomous
```
If `wiki.supervision` is absent from AGENTS.md, treat it as `discuss` — the field must be
explicitly set to `autonomous` to skip Step 3's pause. Never infer autonomy from context,
momentum, or a prior authorization earlier in the same turn.

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

### Step 3: Discuss Key Takeaways (unless `wiki.supervision: autonomous`)

**If `wiki.supervision` is `autonomous`:** skip straight to Step 4. Curate and commit without
pausing — that is what this setting means. Do not add your own confirmation checkpoint before
Step 6's commit either; `autonomous` covers the whole ingest, not just this step.

**Otherwise (the default — `discuss`, or the field absent):** before writing anything, discuss
with the user:
- What are the key changes / main ideas?
- What should the wiki emphasise?
- Are there decisions or patterns worth capturing?
- Does this relate to existing wiki pages?

Don't auto-ingest silently. The human stays involved. A prior authorization earlier in the same
turn (e.g. approving the code change, PR, or merge this source documents) does not satisfy this
step — the wiki content itself has not been discussed yet, regardless of momentum from a chain of
already-approved actions.

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

### Step 8: Run wiki-lint

**Always run `coderails:wiki-lint` immediately after ingest completes.** An ingest without a follow-up lint leaves the new/updated pages unverified — treat ingest and lint as one combined step, not two independently optional ones. (`agentic-loop` batches this at the cluster level when running many ingests across a loop's PRs; a solo invocation of this skill still pairs immediately, since there's no larger batch to wait for.)
