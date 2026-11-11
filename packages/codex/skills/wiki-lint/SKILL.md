---
name: wiki-lint
description: "Use this skill to audit the quality and structural integrity of the project's LLM Wiki — not to read or query it for information. Trigger when the user says 'wiki-lint', wants to lint the wiki, run a wiki health check, find contradictions or stale pages, detect orphaned pages or dead links, discover missing cross-references, or identify coverage gaps. The user's intent is diagnosing wiki health or improving wiki quality. Do not trigger when the user wants to look up what the wiki says about a topic, query wiki content, or read a wiki page."
---

# Wiki Lint

**Scope:** $ARGUMENTS

If the scope is empty, lint the full vault. This skill can run without an argument, unlike `wiki-ingest` and `wiki-query`.
Start the installed `wiki-writer` custom agent with `spawn_agent`.
Give it the scope and project location in a self-contained prompt.

Collect its result with `wait_agent`. Use `send_input` only if you can name a missing check. Then use `close_agent`.

The agent can write and commit. Report results before you make broad changes to pages the user did not name.
Check wiki health at intervals. Look for inconsistencies, missing topics, connections, new questions, and sources to examine.

## Instructions

### Step 0: Load the Schema

At session start, Codex reads the project root's `AGENTS.md` into context. Use that file for project instructions.
Read its linked `AGENTS-wiki-schema.md` for the full schema, which defines page types, page format, and the three layers.

If the context does not contain `AGENTS.md`, start at the current directory and check each parent up to the Git root.
If you find no `AGENTS.md`, tell the user to invoke `$coderails-codex:wiki-init` first.
The vault is a sibling repository, for example `../coderails-wiki`. Find `AGENTS.md` in the project repository.
The session can use the vault from the project directory.

Set `repo` to the absolute path of the code repository directory that contains the `AGENTS.md` you found.
Step 2 checks its Git history. Find that path explicitly. Do not use the current directory by default.

Read the flat keys below from that project's `.coderails/workflow.config.yaml`.
Check for that config from `repo` up to its Git root. Use the first config you find.

- `wiki_path` — the vault path. If relative, resolve it from the directory containing `workflow.config.yaml`.
  Use that value for `vault` below.
- `wiki_git_worktree` — worktree/PR flow (`true`) or direct writes (`false`).
  If there is no setting, use `true` so changes go through a PR before a commit goes into the vault.
- `wiki_git_bypass_flag` — environment assignment for PR creation or merge (e.g. `BYPASS_REVIEW=1`)
- `wiki_git_pull_path` — path to pull after merge. If there is no setting, skip the pull.
- `wiki_stale_days` — age in days to select **candidates** for the staleness check (default: 30).
  Age alone selects candidates. See Step 2 for the check and date-only fallback.

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

Read all Markdown files in `$vault`. Skip `.obsidian/`, `templates/`, and `inbox/`.
Parse each file's YAML frontmatter and all `[[wiki-links]]`.

### Step 2: Check

**Contradictions**: Pages with `⚠️ CONTRADICTION` flags. Also look for claims that newer sources have superseded.

**Stale pages**: run the script. It owns the rule, so do not re-derive it by hand.

```bash
python3 <path to scripts/wiki_lint.py, relative to this SKILL.md: ../../scripts/wiki_lint.py> stale --repo "$repo" --vault "$vault"
```

The script prints JSON `{stale_days, candidates, stale, data_gaps}`.
The typed config loader reads `stale_days` from `wiki_stale_days` (default 30).
A page is a **candidate** if `last_updated` is more than `stale_days` earlier than today.
It is **stale** if a source moved or no comparable repository source is available and the date-only fallback applies.
The script skips `sources/`, `investigations/`, and other point-in-time or structural directories.

Use the script's rules to cite the result. It checks each `sources:` entry in this sequence:

1. `$repo/<entry>`.
2. `$repo/<entry-without-.md>/SKILL.md` for the `skills/foo.md` shorthand.
3. A page in the vault. If the page exists, skip it. If no path exists, the entry is unresolvable.

The script uses the first path it finds. It checks the repository first because a vault page can have the same path as a repository file.
For each repository source, it compares the commit date from `git log -1 --format=%cs` with `last_updated`.
It does not use mtime. If the command gives no date, report missing data and do not report "unchanged".

The script counts a source as moved when its commit date is more than 7 days after the page date.
The 7-day window accounts for writing time. A source committed on day 7 stays in that window.

Classify each entry of `stale`:

- `basis: sources` — read the diff for each `moved` source since the page date before you report. First find and check the base commit:

  ```bash
  base=$(git -C "$repo" log -1 --format=%H --before="<page's last_updated>" -- "$source_path")
  ```

  If `base` is **empty**, all source commits come after the page date. This is the strongest signal of source drift.
  Diff the full history (`git -C "$repo" log -p -- "$source_path"`).
  Do not run `"$base"..HEAD` with an empty `base`. That gives an empty diff with exit 0.
  If `base` has a value, run `git -C "$repo" diff "$base"..HEAD -- "$source_path"`.

  Formatting, a rename, or a change to information the page does not include do not show source drift.
  If the diff changes a claim on the page, give a **source-drift** result. Name each moved source and its commit SHA.
  Use `/wiki-ingest` to follow up. Do not only change the date.

  Include the result in Step 5's count for missing cross-references. Say "source drift" in the prose.

- `basis: date_only` — report the page as stale because it has no comparable repository source and is older than `wiki_stale_days`.
  Say that the date is the only basis. Do not claim source drift or change `last_updated` to close the result.

- If `stale` does not contain a candidate, do not report it and do not change `last_updated`.
  A date change without a check turns "unverified" into "verified" without verification.

- For each `data_gaps` entry, name the page and entry.
  This includes an unresolvable source, empty commit date, missing `last_updated`, or `no_repo_sources`.
  Report missing data. Do not report the page as unchanged or clear it if other sources flagged it.

Pages with no comparable repository source also use the date-only stale fallback.
This lint is advisory and trusts the supplied page dates, sources, and config.
If the repository or vault is unavailable, the script exits 2 and reports the missing input. Correct it and run again.

**Orphan pages**: Zero inbound links (exclude index.md, log.md, AGENTS.md).

**Missing concepts**: Important terms that multiple pages name and that have no page of their own.

**Missing cross-references**: Pages that mention a concept by name but do not wiki-link it, when a page for that concept exists.

**Missing data**: Undocumented topics that existing pages show are important to the user.
Compare wiki coverage with the project's actual structure.

**Inbox backlog**: Files in `$vault/inbox/` with no corresponding source page.

### Step 3: Report

Give a summary with counts for each category. Then give the information for each result.

### Step 4: Suggest

After you report results, suggest:

- New questions to answer for missing topics
- New sources to look for that would strengthen coverage
- Connections that can become new pages

### Step 5: Update Log

Append to `$vault/log.md`: `## [YYYY-MM-DD] lint | <summary of findings>`

Immediately after that line, append `<!-- lint-findings: N -->` on its own line.
Set `N` to the total from Step 2. Add the counts for contradictions, stale pages, orphan pages, and missing concepts.
Also add the counts for missing cross-references, missing data, and inbox backlog items.
If there are no results, use 0.

This machine-readable record supplies the dashboard's `LINT FINDINGS` tile.
It does not change the user report in Step 3. Do not calculate it from the prose summary.

### Step 6: Commit

**If `wiki_git_worktree` is `true`**:
```bash
cd "$WORKTREE_PATH"
git add -A
git commit -m "wiki(lint): <summary of fixes>"
git push -u origin "$BRANCH"
${wiki_git_bypass_flag} gh pr create --title "wiki(lint): <summary>" --body "Findings: <list>"
${wiki_git_bypass_flag} gh pr merge --squash --delete-branch
# enforce_pr_workflow gates `gh pr create` and `gh pr merge` only in a repository with workflow.config.yaml.
# A wiki vault usually has no such file, so the hook does nothing there.
# If it applies, use `$coderails-codex:push` for creation.
# For merge, get a new inspection from the installed `spec-reviewer` custom agent.
# Explicit Bash permission can also satisfy the hook.
# The wiki uses ${wiki_git_bypass_flag} for its publication bypass independently of the hook.
git -C "${wiki_git_pull_path}" pull
git -C "$vault" worktree remove "$WORKTREE_PATH"
```

**If `wiki_git_worktree` is `false`**:
```bash
cd "$vault"
git add -A
git commit -m "wiki(lint): <summary of findings>"
```

### Step 7: Pairing note

A follow-up ingest is optional after lint.
`$coderails-codex:wiki-ingest` Step 8 specifies a lint after ingest.
For direct writes (`wiki_git_worktree: false`), lint immediately.
For PR flow (`wiki_git_worktree: true`, the default), lint after the ingest PR merges.
