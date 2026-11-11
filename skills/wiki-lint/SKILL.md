---
name: wiki-lint
description: "Use this skill to audit the quality and structural integrity of the project's LLM Wiki — not to read or query it for information. Trigger when the user says 'wiki-lint', wants to lint the wiki, run a wiki health check, find contradictions or stale pages, detect orphaned pages or dead links, discover missing cross-references, or identify coverage gaps. The user's intent is diagnosing wiki health or improving wiki quality. Do not trigger when the user wants to look up what the wiki says about a topic, query wiki content, or read a wiki page."
context: fork
agent: coderails:wiki-writer
argument-hint: "[scope — e.g. a subdirectory or page prefix; omit to lint the whole vault]"
model: sonnet
---

# Wiki Lint

**Scope:** $ARGUMENTS

If the scope is empty, lint the full vault. This is the default. The skills `wiki-ingest` and `wiki-query` stop when they have no argument. This skill continues.

The agent can write and commit. Report the results before making broad changes to pages the user did not name.

Check the wiki at intervals for inconsistencies, missing information, and new connections. Suggest questions and sources for the next check.

## Instructions

### Step 0: Load the Schema

At session start, read the project's Git-root `AGENTS.md` as directed by its `CLAUDE.md`. Use it for conventions. For page types, page format, and the three layers, follow the link to `AGENTS-wiki-schema.md` in `AGENTS.md`. Read the full schema.

If the fork has no `AGENTS.md` in context, look in the current directory and its parents up to the Git root. Use the same pattern as `config_path` in `scripts/lib/config.py`. A fork can start in a subdirectory, so check the path to `AGENTS.md`. If you do not find `AGENTS.md` by the Git root, tell the user to run `/wiki-init` first.

Use the project's `AGENTS.md`. The wiki vault is a sibling repo such as `../coderails-wiki`. The project config `.coderails/workflow.config.yaml` points to it. You can run the fork from the project repo.

Set `repo` to the absolute path of the **code** repo root that contains `AGENTS.md`. Step 2 reads its Git history. Use the path you found, which can be different from cwd.

Get the Git and vault settings from flat keys in `repo`’s `.coderails/workflow.config.yaml`. Follow the same pattern as `config_path` in `scripts/lib/config.py`. From `repo`, check each directory up to the Git root for `.coderails/workflow.config.yaml`. Use the first file you find.

- `wiki_path` gives the wiki vault path. If it is relative, resolve it from the directory with that `workflow.config.yaml`. Use `vault` for this value below.
- `wiki_git_worktree` selects a worktree and PR (`true`) or direct writes (`false`). If the config has no such key, use **`true`**. This prevents direct writes to a vault that expects approval through a PR.
- `wiki_git_bypass_flag` — env var for PR creation/merge (e.g. `BYPASS_REVIEW=1`)
- `wiki_git_pull_path` — path to pull after merge. Default when missing: skip the post-merge pull.
- `wiki_stale_days` — age in days before a page becomes a **candidate** for the
  staleness check (default: 30). Age only selects candidates. Use the date-only fallback in Step 2 if no repo source is comparable. See Step 2.

Set `vault` to the resolved `wiki_path` for the remaining steps.

**If `wiki_git_worktree` is `true`** (team repos):
```bash
BRANCH="chore/wiki-lint-$(date +%Y%m%d-%H%M%S)"
WORKTREE_PATH="${vault}-lint-$(date +%Y%m%d-%H%M%S)"
git -C "$vault" worktree add -b "$BRANCH" "$WORKTREE_PATH" origin/main
# All file writes target WORKTREE_PATH
```

**If `wiki_git_worktree` is `false`** (personal wikis):
```bash
WORKTREE_PATH="$vault"
```

### Step 1: Analyse the Wiki

Read all markdown files in `$vault` (without `.obsidian/`, `templates/`, `inbox/`). Parse each file's YAML frontmatter and all `[[wiki-links]]`.

### Step 2: Check

**Contradictions**: Pages with `⚠️ CONTRADICTION` flags. Also look for claims that newer sources have superseded.

**Stale pages**: run the script. It owns the rule, so do not re-derive it by hand.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wiki_lint.py" stale --repo "$repo" --vault "$vault"
```

It prints JSON `{stale_days, candidates, stale, data_gaps}`. The typed config loader reads `wiki_stale_days` as `stale_days` (default 30). A page is a **candidate** if its `last_updated` is older than `stale_days` days. It is **stale** if a source moved, or if no repo source is comparable and the date-only fallback applies. The script skips `sources/`, `investigations/`, and other point-in-time or structural directories.

For each `sources:` entry, the script checks `$repo/<entry>` first. Then it checks `$repo/<entry-without-.md>/SKILL.md`, which is the `skills/foo.md` shorthand. If the script finds a vault page, it skips the entry. It stops at the first match. If it finds no match, it marks the entry unresolvable. It checks the repo paths before the vault because a wiki page can share a path with a repo file.

For each repo source, the script compares its commit date from `git log -1 --format=%cs` with `last_updated`. It does not use mtime. An empty result means missing data, not "unchanged". The script counts a source as moved if the commit date is more than 7 days after the page date. The window accounts for the time between the source commit and the page date. Day 7 is in the window.

Classify each entry of `stale`:
- `basis: sources` — before you report drift, read the diff for each `moved` source. Find the base commit first.

  ```bash
  base=$(git -C "$repo" log -1 --format=%H --before="<page's last_updated>" -- "$source_path")
  ```

  If `base` is empty, all commits for the source are newer than the page. This is the strongest drift signal. Read the full history with `git -C "$repo" log -p -- "$source_path"`. Do not use `"$base"..HEAD` with empty `base`. That gives an empty diff and exit 0.

  If `base` has a value, run `git -C "$repo" diff "$base"..HEAD -- "$source_path"`. Formatting changes, renames, and changes to lines that the page does not discuss do not count as drift. If a change affects a claim on the page, report **source drift**. Name each moved source and its commit. Use `/wiki-ingest` as the follow-up to update the page content.

  In Step 5, count it in **missing cross-references**. Say "source drift" in the prose.
- `basis: date_only` — report the page as stale because it has no comparable repo source and is older than
  `wiki_stale_days`. Say that the result uses only the date. Do not claim source drift or change `last_updated` to close the item.
- If `stale` does not list a candidate, do not report it or change `last_updated`. A date change alone turns "unverified" into "verified" without a check.
- For each `data_gaps` entry, report **missing data** with the page and entry. This includes an unresolvable source, empty commit date, missing `last_updated`, or `no_repo_sources`. Do not report the page as unchanged. Keep flags from other sources.

  If a page has no comparable repo source, use the date-only stale fallback. The lint gives advice and trusts the supplied dates, sources, and configuration. If the repo or vault is unavailable, the script reports that and exits with code 2. Correct the input and run it again.

**Orphan pages**: Pages with no inbound links, without index.md, log.md, and AGENTS.md.

**Missing concepts**: Important terms that appear on multiple pages and have no page of their own.

**Missing cross-references**: Pages that name a concept without a wiki link when the wiki has a page for it.

**Data missing parts**: Topics important to the user that the wiki does not document. Use current pages to identify the topics. Compare the wiki coverage with the project's structure.

**Inbox backlog**: Files in `$vault/inbox/` without a source page.

### Step 3: Report

Give counts for each category. Then give information for each item.

### Step 4: Suggest

After the report, suggest these items.
- New questions to fill missing parts
- New sources that can give better coverage
- Connections that could become new wiki pages

### Step 5: Update Log

Append to `$vault/log.md`: `## [YYYY-MM-DD] lint | <summary of findings>`

On the next line, append `<!-- lint-findings: N -->`. Set `N` to the sum of the Step 2 counts. Include contradictions, stale pages, orphan pages, missing concepts, missing cross-references, data missing parts, and inbox backlog items. Use 0 if there are no items.

The dashboard’s `LINT FINDINGS` tile reads this record. It does not change the report in Step 3. Use the category counts directly. Do not parse the prose summary to get them.

### Step 6: Commit

**If `wiki_git_worktree` is `true`**:
```bash
cd "$WORKTREE_PATH"
git add -A
git commit -m "wiki(lint): <summary of fixes>"
git push -u origin "$BRANCH"
${wiki_git_bypass_flag} gh pr create --title "wiki(lint): <summary>" --body "Findings: <list>"
${wiki_git_bypass_flag} gh pr merge --squash --delete-branch
# enforce_pr_workflow gates `gh pr create`/`gh pr merge` only in a repo that has a
# workflow.config.yaml (a wiki vault usually has none → no-op). When it does apply, the
# satisfier is /coderails:push (create) or /pr-review-toolkit:review-pr (merge) having run
# this session, or a settings.json Bash permission.
# The wiki uses ${wiki_git_bypass_flag} when it publishes a PR. The flag operates independently of that hook.
git -C "${wiki_git_pull_path}" pull
git -C "$vault" worktree remove "$WORKTREE_PATH"
```

**If `wiki_git_worktree` is `false`**:
```bash
cd "$vault"
git add -A
git commit -m "wiki(lint): <summary of findings>"
```

If `qmd` is available, reindex after committing with `qmd update && qmd embed`. Run `update` first to find new or changed files. Used alone, `embed` refreshes only known content hashes.

### Step 7: Pairing note

After `coderails:wiki-ingest`, run lint as specified in that skill’s Step 8. For `wiki_git_worktree: false`, run it immediately after the direct write. For `wiki_git_worktree: true`, the default, run it after the PR merges. The lint does not start a new wiki update.
