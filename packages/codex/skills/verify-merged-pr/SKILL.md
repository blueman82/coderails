---
name: verify-merged-pr
description: 'Use when an agent, teammate, CI report, or session summary claims a PR is merged and you are about to rely on that — before building on top of "it''s merged", trusting a headless builder''s report, or accepting a "done, PR landed" hand-off. Symptoms: someone gives you ONE PR number as the thing that landed, a status message says merged/shipped/live, or you need to confirm changes are actually on origin/main.'
---

# Verify Merged PR

## Overview

Check a reported PR merge before you rely on it.

Check the PR's merge status. Check its content on `origin/main`.
Check other PRs that merged in the same period.

A builder can report one PR after it merges multiple PRs. Check related PRs
so the handoff covers the full set of changes.

## When to Use

- An agent, teammate, CI report, or session summary says a PR merged,
  shipped, or went live.
- You will build, deploy, or hand off work that depends on that merge.
- A builder or loop reports one merged PR number.
- You must make sure that the changed content is on `origin/main`.

Do not use this skill if you completed and observed the merge in this
session. An open or draft PR has no merge to check.

## The Three Checks

Run all three checks. Report CONFIRMED only if all three succeed.
Use the actual PR number and author. Select a lookup string unique to the change.

### 1. Re-derive the merge STATE from gh

```bash
gh pr view <N> --json state,mergedAt,mergeCommit,author,headRefName,baseRefName,url
```

Make sure that `state` is `MERGED` and `mergedAt` is not null.
Record `mergeCommit.oid`, `author.login`, and `baseRefName`.
The PR could be closed without a merge. It could target a different base.
Use the JSON fields to tell these conditions apart.

### 2. Confirm the CONTENT is actually on origin/main

A merge commit alone does not show that the branch you build from contains its changes.
`scripts/verify_merged.py` applies the rule, runs check 1 again, and fetches the base.
Do not trust the local snapshot. Find the script relative to this `SKILL.md` (`../../scripts/verify_merged.py`):

```bash
python3 <path to scripts/verify_merged.py> <N> --grep '<string unique to the change>' --path <expected path>
```

The script prints a JSON verdict (`confirmed`, `method`, `reasons`) and exits 0 only when the checks succeed.
The script must find `MERGED` and a value for `mergedAt`.
It fetches the base. The merge commit must be reachable from `origin/<base>`.

The content check (`method: content`) must find the lookup string on `origin/<base>`.
The merge commit's first parent must not contain that string. If it does, the script gives `content_preexisting`.
An unreadable parent or other grep error gives `content_check_failed`. Fetch missing history before you try again.

Without `--grep`, the script can check only a merge commit with two parents and a PR head that is an ancestor of `origin/<base>`.
That check gives `method: merge-commit-ancestry`. A squash rewrites the SHA and needs `--grep` without a PR-head ancestry check.
The claim stays unconfirmed if content is unavailable (`content_absent`) or a necessary lookup string is unavailable (`content_check_required`).
A string added to the base after the merge can satisfy the content rule. The check cannot show which PR added the string.

### 3. Enumerate SIBLING PRs by author and time window

The reporter named one PR. Find other PRs that merged in the same period.

```bash
gh pr list --state merged --limit 20 \
  --search "author:<author.login> sort:updated-desc" \
  --json number,title,mergedAt,headRefName,mergeCommit
```

Read the `mergedAt` timestamps. Find PRs by the same author that merged minutes before or after the named PR.
List each one in your verdict.

A long time interval can mark a different work stream. Include earlier merges only when the facts link them to the named PR.

## Quick Reference

| Check | Command | Result |
|---|---|---|
| Status | `gh pr view <N> --json state,mergedAt,mergeCommit,author,baseRefName` | The PR has status `MERGED` and the correct base |
| Content | `scripts/verify_merged.py <N> --grep '<change>' --path <path>` (fetch, reachability, `git grep` at `origin/<base>`) | The branch contains the change |
| Siblings | `gh pr list --state merged --search "author:<login> sort:updated-desc"` | No unreported PRs landed in the same window |

## Reporting the Verdict

Give the verdict `CONFIRMED` or `NOT CONFIRMED`. Then report:

- The merge commit and `mergedAt` for the named PR.
- If `origin/<base>` contains its content. Give the script's `method` and `reasons`.
- **Each sibling PR** in the same author/time cluster, with numbers and timestamps. Identify PRs the reporter omitted.
- What you could not check from source, such as runtime behavior. A content check cannot show that the change works.

## Common Mistakes

| Mistake | Correction |
|---|---|
| Checking only the named PR | Always run check 3 to find related PRs. |
| Trusting `state: MERGED` alone | A merge marker is not the content. Run the `git grep` on `origin/<base>`. |
| Skipping `git fetch` | The local snapshot can be stale. Fetch before checking ancestry. |
| Guessing the base branch | Read `baseRefName` from the JSON. The PR can target a branch other than `main`. |
| Reporting "merged, works" | Report the content result and runtime behavior independently. |
