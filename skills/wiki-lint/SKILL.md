---
name: wiki-lint
description: "Use this skill to audit the quality and structural integrity of the project's LLM Wiki — not to read or query it for information. Trigger when the user says 'wiki-lint', wants to lint the wiki, run a wiki health check, find contradictions or stale pages, detect orphaned pages or dead links, discover missing cross-references, or identify coverage gaps. The user's intent is diagnosing wiki health or improving wiki quality. Do not trigger when the user wants to look up what the wiki says about a topic, query wiki content, or read a wiki page."
context: fork
---

# Wiki Lint

Periodically health-check the wiki. The LLM is good at finding inconsistencies, gaps, and new connections — and at suggesting further questions to ask and sources to look for.

## Instructions

### Step 0: Load the Schema

`AGENTS.md` at the project's git root is loaded into context at session start (per the project's `CLAUDE.md`) — use that content. If it isn't present in context (e.g. a fresh fork with no prior context), find the git repository root with `git rev-parse --show-toplevel` (not the current working directory — a fork's cwd may be a subdirectory, and may even be inside the wiki vault's own repo rather than the project repo) and read `AGENTS.md` there. If it doesn't exist there either, tell the user to run `/wiki-init` first.

Extract:
- `vault` — absolute path to the wiki vault
- `git.worktree` — whether to use worktree/PR flow (`true`) or write directly (`false`)
- `git.bypass_flag` — env var for PR creation/merge (e.g. `BYPASS_REVIEW=1`)
- `git.pull_path` — path to pull after merge
- `git.stale_days` — days before a page is considered stale (default: 30)

**If `git.worktree` is `true`** (team repos):
```bash
BRANCH="chore/wiki-lint-$(date +%Y%m%d-%H%M%S)"
WORKTREE_PATH="${vault}-lint-$(date +%Y%m%d-%H%M%S)"
git -C "$vault" worktree add -b "$BRANCH" "$WORKTREE_PATH" origin/main
# All file writes target WORKTREE_PATH
```

**If `git.worktree` is `false`** (personal wikis):
```bash
WORKTREE_PATH="$vault"
```

### Step 1: Analyse the Wiki

Read all markdown files in `$vault` (excluding `.obsidian/`, `templates/`, `inbox/`). Parse each file's YAML frontmatter and all `[[wiki-links]]`.

### Step 2: Check

**Contradictions**: Pages with `⚠️ CONTRADICTION` flags. Also look for claims that newer sources have superseded.

**Stale pages**: Where `last_updated` is more than `git.stale_days` (default 30) days ago.

**Orphan pages**: Zero inbound links (exclude index.md, log.md, AGENTS.md).

**Missing concepts**: Important terms mentioned across multiple pages but lacking their own page.

**Missing cross-references**: Pages that mention a concept by name but don't wiki-link it, when a page for that concept exists.

**Data gaps**: Topics the user cares about (based on existing pages) that aren't documented. Compare wiki coverage against the project's actual structure.

**Inbox backlog**: Files in `$vault/inbox/` that haven't been ingested yet (no corresponding source page).

### Step 3: Report

Summary with counts per category, then details for each finding.

### Step 4: Suggest

After reporting findings:
- New questions to investigate that would fill gaps
- New sources to look for that would strengthen coverage
- Interesting connections for new article candidates

### Step 5: Update Log

Append to `$vault/log.md`: `## [YYYY-MM-DD] lint | <summary of findings>`

### Step 6: Commit

**If `git.worktree` is `true`**:
```bash
cd "$WORKTREE_PATH"
git add -A
git commit -m "wiki(lint): <summary of fixes>"
git push -u origin "$BRANCH"
${git.bypass_flag} gh pr create --title "wiki(lint): <summary>" --body "Findings: <list>"
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
git commit -m "wiki(lint): <summary of findings>"
```
