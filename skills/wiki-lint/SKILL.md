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

`AGENTS.md` at the project's git root is loaded into context at session start (per the project's `CLAUDE.md`) — use that content. The wiki schema itself (page types, page format, the three layers) lives in `AGENTS-wiki-schema.md`, which `AGENTS.md` links to; read it for the full schema. If `AGENTS.md` isn't present in context (e.g. a fresh fork with no prior context), do not assume cwd: walk up from the current directory, checking each level for `AGENTS.md`, up to the git repository root (same pattern as `coderails::config_path` in `scripts/lib/config.sh`) — a fork's cwd may be a subdirectory of the project repo. If no `AGENTS.md` is found by the git root, tell the user to run `/wiki-init` first. (The wiki vault itself, e.g. `../coderails-wiki`, is a separate sibling repo the project's `.claude/workflow.config.yaml` points to; it is not where `AGENTS.md` lives, and a fork should never need to be running from inside it.)

`repo` — absolute path to the **code** repo root: the directory containing the `AGENTS.md` you just located. Step 2's staleness check compares against its git history, so resolve this explicitly rather than assuming cwd.

The git/vault settings below are **not** read from AGENTS.md — they are flat keys in that same `repo`'s `.claude/workflow.config.yaml`, resolved with the same walk-up pattern as `coderails::config_path` in `scripts/lib/config.sh`: starting from `repo`, check each directory up to its git root for `.claude/workflow.config.yaml`; the first one found wins.

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

**Stale pages**: Where `last_updated` is more than `wiki_stale_days` (default 30)
days ago **and** at least one of the page's `sources:` has changed since that
stamp. Date alone is not staleness — a page whose sources have not moved is
correctly dated, not stale.

Resolve each `sources:` entry, in this order. Stop at the first hit:

1. **It exists in the repo**, either as `$repo/<entry>` or as
   `$repo/<entry-without-.md>/SKILL.md` → use it. The first covers full paths
   like `hooks/scripts/lib/loop_cost.sh` and bare repo-root files like
   `AGENTS.md` or `install.sh`; the second covers the `skills/foo.md` shorthand
   for `skills/foo/SKILL.md`.

   **Try both repo forms before testing the vault.** A wiki page that mirrors a
   repo file has the same path in both trees — `commands/push.md` is a real file
   in the repo *and* a page in the vault, and `skills/dashboard.md` is a vault
   page whose repo form is `skills/dashboard/SKILL.md`. Testing the vault first
   classifies such a page's own source as "another wiki page" and silently drops
   it to date-only. That is the bug this ordering exists to prevent, and it
   applies to the shorthand exactly as it does to the exact path.
2. **It exists in the vault** (`$vault/<entry>`) and neither repo form hit → it
   names another wiki page. Not comparable; skip it. Test by existence, not by a
   `sources/` prefix — real entries also point at `design/…` and
   `investigations/…` pages.
3. **Nothing exists** → the entry resolves to nothing. Do **not** treat that as
   "not moved" — it is unresolvable, which is its own outcome below. Some real
   entries point outside the repo entirely (`~/.claude/settings.json`, another
   repo's slug).

Step 1 is the only comparable outcome. A page whose entries all land on 2 or 3
has nothing to compare and falls through to the date-only rule below.

"Present in both trees means the repo file" holds in this vault — every
colliding entry is a repo file the wiki mirrors — but it is a property of how
this vault names its sources, not a law. Re-check it against your own vault
before relying on it, the same way you re-check the grace window.

Check **every** entry that resolves, not just the first. One moved source is
enough to make the page a finding; the rest still need checking, because the
report must name each source that moved. For each, compare the last commit
date on the current branch against the page's `last_updated`:

```bash
git -C "$repo" log -1 --format=%cI -- "$source_path"
```

**An empty result is not a date.** This command prints nothing and still exits
0 when the path is untracked or misspelled. Never compare an empty string
against `last_updated` — an empty value silently reads as "not moved", which is
a fail-open on the one check this rule exists to perform. Treat empty as
unresolvable and use the branch below.

Use the commit date, never filesystem mtime — `git clone`/`checkout`/`pull`
stamp mtime at checkout time, so in a fresh clone every file looks equally
new and the check silently stops discriminating.

Compare with a **7-day grace window**: treat a source as moved only if its
commit date is more than 7 days after the page's `last_updated`. A page is
written from a source in the same week it lands, and `last_updated` is a date
while the commit is a timestamp, so a 0-7 day gap is authoring lag, not drift.
Without the window, a bulk commit (an import, a mass reformat, a rename sweep)
re-dates hundreds of files at once and flags every page written just before it.

7 is calibrated, not derived — it was set against one repo whose bulk commit
touched 133 files at a single timestamp and produced 5 false positives on a
1-day gap. Re-check it against your own vault: if authoring lag there routinely
exceeds a week, raise it, and say in the report which value the pass used.

Classify the result:
- **No source moved past the window** → not a finding. Do not report it, and do
  not bump `last_updated`; a blind bump converts "unverified" into "verified"
  with no verification.
- **Any source moved past the window** → read that source's diff over the
  drifted span before reporting. Find the base commit first, and check it:

  ```bash
  base=$(git -C "$repo" log -1 --format=%H \
      --before="<page's last_updated>" -- "$source_path")
  ```

  If `base` is **empty**, the source has no commit at all before the page's
  stamp — its entire history postdates the page. That is the strongest drift
  signal there is, not the weakest. Diff the whole history instead:
  `git -C "$repo" log -p -- "$source_path"`. Do not run `"$base"..HEAD` with an
  empty `base`: it collapses to `..HEAD`, which git reads as `HEAD..HEAD` and
  prints an empty diff with exit 0 — indistinguishable from "no change".

  Otherwise diff normally:

  ```bash
  git -C "$repo" diff "$base"..HEAD -- "$source_path"
  ```

  If it changed only formatting, a rename, or a line the page does not cover,
  it is not drift. If it changed something the page states, report it as a
  **source-drift** finding, naming every source that moved and its exact
  commit — so the follow-up is a real `/wiki-ingest` rather than a date edit.
  Count it under **missing cross-references** in Step 5's total; it is the
  closest existing category and the total is a sum, so nothing is lost or
  double-counted. Say "source drift" in the prose so it is not confused with an
  unlinked-concept finding.
- **A source resolved to nothing, or its commit date came back empty** → report
  it as a **data gap**: the page cites a source the linter cannot locate. Name
  the entry. Do not silently treat it as unchanged, and do not let it clear a
  page that other sources have already flagged.
- **Page has no repo-resolvable `sources:` at all** → fall back to the
  date-only rule and apply it: over `wiki_stale_days`, the page **is** a stale
  finding. Say in the report that the check was date-only, so the finding
  carries its own weaker provenance. Falling back is not clearing — a page
  nothing could be compared against is less verified than one whose sources
  were checked, not more. Do not bump `last_updated` to close it; that is the
  unverified-to-verified conversion this whole rule exists to prevent.

`sources/` and `investigations/` pages are point-in-time records; age is their
correct state. Exclude them from this check entirely.

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

### Step 7: Pairing note

Lint does not need to trigger a follow-up ingest — this direction is
one-way. It's `coderails:wiki-ingest` that always pairs forward into a
lint pass (see that skill's own Step 8); this skill is the target of that
pairing, not a source of a new obligation back onto ingest.
