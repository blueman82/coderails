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

An empty scope means lint the whole vault — that is the intended default, not a
missing argument. Unlike `wiki-ingest` and `wiki-query`, this skill has a
meaningful behaviour with no argument, so it does not stop. Be aware the whole
vault is in scope, and that the agent you run as can write and commit: report
findings before making sweeping changes across pages you were not asked about.

Periodically health-check the wiki. The LLM is good at finding inconsistencies, gaps, and new connections — and at suggesting further questions to ask and sources to look for.

## Instructions

### Step 0: Load the Schema

`AGENTS.md` at the project's git root is loaded into context at session start (per the project's `CLAUDE.md`) — use that content. The wiki schema itself (page types, page format, the three layers) lives in `AGENTS-wiki-schema.md`, which `AGENTS.md` links to; read it for the full schema. If `AGENTS.md` isn't present in context (e.g. a fresh fork with no prior context), do not assume cwd: walk up from the current directory, checking each level for `AGENTS.md`, up to the git repository root (same pattern as `config_path` in `scripts/lib/config.py`) — a fork's cwd may be a subdirectory of the project repo. If no `AGENTS.md` is found by the git root, tell the user to run `/wiki-init` first. (The wiki vault itself, e.g. `../coderails-wiki`, is a separate sibling repo the project's `.coderails/workflow.config.yaml` points to; it is not where `AGENTS.md` lives, and a fork should never need to be running from inside it.)

`repo` — absolute path to the **code** repo root: the directory containing the `AGENTS.md` you just located. Step 2's staleness check compares against its git history, so resolve this explicitly rather than assuming cwd.

The git/vault settings below are **not** read from AGENTS.md — they are flat keys in that same `repo`'s `.coderails/workflow.config.yaml`, resolved with the same walk-up pattern as `config_path` in `scripts/lib/config.py`: starting from `repo`, check each directory up to its git root for `.coderails/workflow.config.yaml`; the first one found wins.

- `wiki_path` — the wiki vault path; resolved relative to the directory containing that `workflow.config.yaml` unless already absolute. This is `vault` below.
- `wiki_git_worktree` — whether to use worktree/PR flow (`true`) or write directly (`false`). Default when absent: **`true`** (PR flow) — the fail-safe choice, since defaulting to direct-write would silently start committing straight to the vault for a project that expected review.
- `wiki_git_bypass_flag` — env var for PR creation/merge (e.g. `BYPASS_REVIEW=1`)
- `wiki_git_pull_path` — path to pull after merge. Default when absent: skip the post-merge pull.
- `wiki_stale_days` — age in days before a page becomes a **candidate** for the
  staleness check (default: 30). Age alone never makes a page stale; see Step 2.

Set `vault` to the resolved `wiki_path` for the rest of this skill.

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

Read all markdown files in `$vault` (excluding `.obsidian/`, `templates/`, `inbox/`). Parse each file's YAML frontmatter and all `[[wiki-links]]`.

### Step 2: Check

**Contradictions**: Pages with `⚠️ CONTRADICTION` flags. Also look for claims that newer sources have superseded.

**Stale pages**: run the script; it owns the rule, so do not re-derive it by hand.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/wiki_lint.py" stale --repo "$repo" --vault "$vault"
```

It prints JSON `{stale_days, candidates, stale, data_gaps}`. `stale_days` is `wiki_stale_days`, read through the
typed config loader (default 30). A page is a **candidate** when `last_updated` is more than `stale_days` old; it is
**stale** only when a source also moved. Date alone is not staleness, and `sources/`, `investigations/` and the other
point-in-time or structural directories are excluded by the script.

How the script decides, so the report can cite it: each `sources:` entry resolves in this order and stops at the first
hit: `$repo/<entry>`, then `$repo/<entry-without-.md>/SKILL.md` (the `skills/foo.md` shorthand), then a vault page
(another wiki page, skipped, tested by existence); nothing existing is unresolvable. Repo forms are tried before the
vault because a wiki page that mirrors a repo file has the same path in both trees. For each repo source it compares
`git log -1 --format=%cs` (commit date, never mtime; an empty result is a gap, not "unchanged") with `last_updated`,
and counts a source as moved when its commit date is more than 7 days after the page date. The 7-day window covers
authoring lag between a source commit and a page's date stamp; a source committed on day 7 remains in grace.

Classify each entry of `stale`:
- `basis: sources` — read each `moved` source's diff over the drifted span before reporting. Find the base commit
  first, and check it:

  ```bash
  base=$(git -C "$repo" log -1 --format=%H --before="<page's last_updated>" -- "$source_path")
  ```

  If `base` is **empty**, the source has no commit before the page's stamp: its whole history postdates the page,
  the strongest drift signal there is. Diff the whole history (`git -C "$repo" log -p -- "$source_path"`); never run
  `"$base"..HEAD` with an empty `base`, which collapses to an empty diff with exit 0. Otherwise
  `git -C "$repo" diff "$base"..HEAD -- "$source_path"`. If it changed only formatting, a rename, or a line the page
  does not cover, it is not drift. If it changed something the page states, report a **source-drift** finding naming
  every moved source and its exact commit, so the follow-up is a real `/wiki-ingest` rather than a date edit. Count it
  under **missing cross-references** in Step 5's total; say "source drift" in the prose.
- A candidate absent from `stale` is not a finding: do not report it and do not bump `last_updated`; a blind bump
  turns "unverified" into "verified" with no verification.
- Every `data_gaps` entry (unresolvable source, empty commit date, missing `last_updated`, `no_repo_sources`) is a **data gap**: name the
  page and entry. Never treat it as unchanged, and never let it clear a page other sources already flagged.
  Pages without any comparable repo source remain data gaps. This lint is advisory and trusts the supplied page dates,
  sources and configuration. A missing repo or vault is reported unavailable with exit 2; repair the input and rerun.

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

Immediately after that line, append a structured findings-count record on its
own line: `<!-- lint-findings: N -->`, where `N` is the total number of
findings from Step 2 (contradictions + stale pages + orphan pages + missing
concepts + missing cross-references + data gaps + inbox backlog items — sum
every category, 0 if the pass was clean). This is a machine-readable summary
for tooling (the dashboard's LINT FINDINGS tile) — it does not change what
gets reported to the user in Step 3, and it is never derived by re-parsing
the prose summary.

### Step 6: Commit

**If `wiki_git_worktree` is `true`**:
```bash
cd "$WORKTREE_PATH"
git add -A
git commit -m "wiki(lint): <summary of fixes>"
git push -u origin "$BRANCH"
${wiki_git_bypass_flag} gh pr create --title "wiki(lint): <summary>" --body "Findings: <list>"
${wiki_git_bypass_flag} gh pr merge --squash --delete-branch
# Note: enforce_pr_workflow gates `gh pr create`/`gh pr merge` only in a repo that has a
# workflow.config.yaml (a wiki vault usually has none → no-op). When it does apply, the
# satisfier is /coderails:push (create) or /pr-review-toolkit:review-pr (merge) having run
# this session, or a settings.json Bash permission. ${wiki_git_bypass_flag} is the wiki's own
# delivery bypass, separate from that hook.
git -C "${wiki_git_pull_path}" pull
git -C "$vault" worktree remove "$WORKTREE_PATH"
```

**If `wiki_git_worktree` is `false`**:
```bash
cd "$vault"
git add -A
git commit -m "wiki(lint): <summary of findings>"
```

If `qmd` is available, reindex after committing: `qmd update && qmd embed` (`update` must run first to pick up new/changed files; `embed` alone only refreshes already-known content hashes).

### Step 7: Pairing note

Lint does not need to trigger a follow-up ingest — this direction is
one-way. It's `coderails:wiki-ingest` that pairs forward into a lint pass
(see that skill's own Step 8) — immediately for direct-write
(`wiki_git_worktree: false`), or as a separate follow-up once the ingest
PR merges for PR flow (`wiki_git_worktree: true`, the default); this
skill is the target of that pairing, not a source of a new obligation
back onto ingest.
