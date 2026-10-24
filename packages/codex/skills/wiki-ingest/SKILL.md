---
name: wiki-ingest
description: "Use this skill when the user wants wiki pages created or updated to document a change — a merged PR, shipped feature, or engineering decision. The user always has an artifact to record (PR number, description, decision) and wants it written into the project's LLM Wiki as permanent documentation. Trigger on any request to push content into the wiki: 'ingest this', 'create wiki pages for this PR', 'add to wiki', 'document this in the wiki', 'capture this change', 'file this in the wiki'."
---

# Wiki Ingest

Ingest a new source into the project's LLM Wiki. A single source typically touches 3-15 wiki pages depending on project size.

**Source to ingest:** $ARGUMENTS

Spawn the installed `wiki-writer` custom agent with `spawn_agent`, passing the
source and project location in a self-contained prompt. Collect its result with
`wait_agent`. For a specific missing check, use `send_message` while it runs
or `followup_task` after it ends. If the source above is empty, report that
and stop.

## Instructions

### Step 0: Load the Schema

The git root's `AGENTS.md` loads at session start.
Read its wiki schema section, or the `AGENTS-wiki-schema.md` file it links to.
Coderails keeps the schema in `AGENTS.md` and the live page types in `wiki.schema.json`.
If `AGENTS.md` is not in context, walk up from the current directory to the git root.
Check each level for `AGENTS.md`; a fork can start in a project subdirectory.
If you do not find it, tell the user to invoke `$coderails-codex:wiki-init` first.
The wiki vault is a separate sibling repo, such as `../coderails-wiki`.
The project's `.coderails/workflow.config.yaml` points to it.
Do not look for `AGENTS.md` in the vault.
A fork does not need to run from inside the vault.

The git/vault/supervision settings below are **not** read from AGENTS.md — they are flat
keys in that same project's `.coderails/workflow.config.yaml` (the repo the source being
ingested belongs to, i.e. wherever `AGENTS.md` was found above), resolved by walking up
from the project repo location to its git root and checking for
`.coderails/workflow.config.yaml`; the first one found wins.

- `wiki_path` — the wiki vault path; resolved relative to the directory containing that
  `workflow.config.yaml` unless already absolute. Referred to as `vault` below.
- `wiki_git_worktree` — whether to use git worktree/PR flow (`true`) or write directly
  (`false`). Default when absent: **`true`** (PR flow) — the fail-safe choice, since
  defaulting to direct-write would silently start committing straight to the vault for a
  project that expected review.
- `wiki_git_bypass_flag` — env var to set when creating/merging PRs (e.g. `BYPASS_REVIEW=1`)
- `wiki_git_pull_path` — path to `git pull` from after a human merges the ingest PR (this
  skill no longer merges or pulls itself — see Step 6). Default when absent: no pull path is
  suggested in Step 7's report.
- `wiki_supervision` — `discuss` (default) or `autonomous`; see Step 3.

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
explicitly set to `autonomous` to skip Step 3's pause. Never infer autonomy from context,
momentum, or a prior authorization earlier in the same turn.

Set `vault` to the resolved `wiki_path` for the rest of this skill.

### Step 1: Set Up Workspace

**If `wiki_git_worktree` is `true`** (team repos — prevents parallel session conflicts):
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

**From description**: Ask which files changed, or use `git log` to find relevant commits.

### Step 3: Discuss Key Takeaways (unless `wiki_supervision: autonomous`)

**If `wiki_supervision` (from the project's `.coderails/workflow.config.yaml`, see Step 0) is
`autonomous`:** skip straight to Step 4. Curate and commit without pausing — that is what this
setting means. Do not add your own confirmation checkpoint before Step 6's commit either;
`autonomous` covers the whole ingest, not just this step.

**Otherwise (the default — `discuss`, the field absent, or no config file resolved):** before
writing anything, discuss
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

**If `wiki_git_worktree` is `true`**:
```bash
cd "$WORKTREE_PATH"
git add -A
git commit -m "wiki: ingest <description>"
git push -u origin "$BRANCH"
${wiki_git_bypass_flag} gh pr create --title "wiki: ingest <description>" --body "Pages created/updated: <list>"
# STOP here. Do not merge the PR — not in interactive, autonomous, or
# backgrounded/detached execution. wiki-ingest never merges its own PR: report
# the PR URL/number back (Step 7) and end. A human, or an explicit separate
# follow-up instruction, merges it.
# WORKTREE_PATH is deliberately left on disk here — it holds the branch backing
# the open PR above, so removing it now would delete work in flight. Report its
# path in Step 7; whoever merges the PR removes it afterward with:
#   git -C "$vault" worktree remove "$WORKTREE_PATH"
# Note: enforce_pr_workflow gates `gh pr create` only in a repo that has a
# workflow.config.yaml (a wiki vault usually has none → no-op). When it does apply, the
# satisfier is `$coderails-codex:push` having run this session, or an explicit Bash permission.
# ${wiki_git_bypass_flag} is the wiki's own delivery bypass, separate from that hook.
```

**If `wiki_git_worktree` is `false`**:
```bash
cd "$vault"
git add -A
git commit -m "wiki: ingest <description>"
```

### Step 7: Report

Report the pages created or updated, new wiki links, and gaps.
**For worktree flow, report the PR URL or number and stop.**
A human or a separate follow-up instruction merges the PR.
Also report `WORKTREE_PATH` and the cleanup command from Step 6.

### Step 8: Run wiki-lint

**If `wiki_git_worktree` is `false` (direct-write), run `$coderails-codex:wiki-lint` immediately after ingest.**
The lint checks the new or updated pages.
Treat ingest and lint as one step.
For an agentic loop with many ingests, run lint after the cluster.

**If `wiki_git_worktree` is `true` (PR flow), wait to run wiki-lint.**
The ingest PR from Step 6 is still open.
`wiki-lint` checks the vault's merged state (`origin/main`), which does not yet include these pages.
Run `$coderails-codex:wiki-lint` as a separate follow-up once the ingest PR has actually merged.
