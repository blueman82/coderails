---
name: verify-merged-pr
description: >-
  Use this skill before you rely on a reported PR merge. The report can
  come from an agent, teammate, CI run, or session summary. Check a claim
  that a PR merged, shipped, or went live. Use it when someone names one
  PR or when you need to confirm content on origin/main.
model: sonnet
---

# Verify Merged PR

## Overview

Check a reported PR merge before you rely on it.

Check the PR's merge state. Check its content on `origin/main`.
Check other PRs that merged in the same period.

A builder may report one PR even when it merged several. Check related PRs
so the handoff covers the full set of changes.

## When to Use

- An agent, teammate, CI report, or session summary says a PR merged,
  shipped, or went live.
- You will build, deploy, or hand off work that depends on that merge.
- A builder or loop reports one merged PR number.
- You need to confirm that the changed content is on `origin/main`.

Do not use this skill if you completed and observed the merge in this
session. An open or draft PR has no merge to verify.

## The Three Checks

Run all three checks. Confirm the claim only when each check passes.
Use the real PR number and author. Select a search string that is unique
to the change.

### 1. Re-derive the merge STATE from gh

```bash
gh pr view <N> --json state,mergedAt,mergeCommit,author,headRefName,baseRefName,url
```

Confirm that `state` is `MERGED` and `mergedAt` is not null.
Record `mergeCommit.oid`, `author.login`, and `baseRefName`.
The PR could be closed without a merge. It could target a different base.
Use the JSON fields to distinguish these cases.

### 2. Confirm the CONTENT is actually on origin/main

Fetch the base branch first. Its local copy can be stale.
Check that the merge commit and the change are on that branch.

```bash
git fetch origin <base> --quiet
git merge-base --is-ancestor <mergeCommit.oid> origin/<base> && echo "on origin/<base>" || echo "NOT on origin/<base>"
git grep -n '<string unique to the change>' origin/<base> -- <expected path>
```

Ancestry shows that the base branch contains the merge commit.
`git grep` checks for the selected change in the tree. If it finds no
match, leave the content claim unconfirmed even when the PR state is
`MERGED`.

### 3. Enumerate SIBLING PRs by author and time window

The reporter named one PR. Find other PRs that merged in the same period.

```bash
gh pr list --state merged --limit 20 \
  --search "author:<author.login> sort:updated-desc" \
  --json number,title,mergedAt,headRefName,mergeCommit
```

Read the `mergedAt` timestamps. Find PRs by the same author that merged
within minutes of the named PR. List each one in your verdict.
A wide time gap can mark a different work stream. Include earlier merges
only when you have a reason.

## Quick Reference

| Check | Command | Confirms |
|---|---|---|
| State | `gh pr view <N> --json state,mergedAt,mergeCommit,author,baseRefName` | The PR is MERGED, into the base you expect |
| Content | `git fetch origin <base>` → `git merge-base --is-ancestor <oid> origin/<base>` + `git grep '<change>' origin/<base>` | The actual change is on the branch, not just a marker |
| Siblings | `gh pr list --state merged --search "author:<login> sort:updated-desc"` | No unreported PRs landed in the same window |

## Reporting the Verdict

State CONFIRMED or NOT CONFIRMED. Then report:
- The merge commit and `mergedAt` for the named PR.
- The ancestry and content search result for `origin/<base>`.
- Each sibling PR in the same author and time group. Include its number
  and merge time. Mark any PR that the reporter did not name.
- Any limit of the checks. Presence in the tree does not prove that the
  change works at runtime.

## Common Mistakes

| Mistake | Fix |
|---|---|
| Verifying only the named PR | Always run check 3 — the sibling enumeration is the point. |
| Trusting `state: MERGED` alone | A merge marker isn't the content. Run the `git grep` on `origin/<base>`. |
| Skipping `git fetch` | The local snapshot can be stale. Fetch before checking ancestry. |
| Assuming the base branch | Read `baseRefName` from the JSON; the PR may not target `main`. |
| Reporting "merged, works" | You verified presence, not behaviour. Separate the two in the verdict. |
