---
name: verify-merged-pr
description: Use when an agent, teammate, CI report, or session summary claims a PR is merged and you are about to rely on that — before building on top of "it's merged", trusting a headless builder's report, or accepting a "done, PR landed" hand-off. Symptoms: someone gives you ONE PR number as the thing that landed, a status message says merged/shipped/live, or you need to confirm changes are actually on origin/main.
model: sonnet
---

# Verify Merged PR

## Overview

Check a reported PR merge before you rely on it.

Check three things independently: the PR's merge state, its content on
`origin/main`, and other PRs that merged in the same period.

A builder may report one PR even when it merged several. Check related PRs
so the handoff covers the full set of changes.

## When to Use

- An agent / teammate / CI report / session summary says a PR is merged, shipped, live, or landed.
- You are about to build on top of, deploy, or hand off work that depends on the merge being real.
- A headless builder or loop reports "done — PR merged" and gives you one PR number.
- You need to confirm the *changed content* — not just a merge marker — is present on `origin/main`.

**When NOT to use:** you performed the merge yourself this session and watched it complete, or the claim is about an open/draft PR (nothing to verify as merged yet).

## The Three Checks

Run all three. The claim is confirmed only when state, content, and siblings all check out. Substitute the real PR number, author, and a grep string unique to the change.

### 1. Re-derive the merge STATE from gh

```bash
gh pr view <N> --json state,mergedAt,mergeCommit,author,headRefName,baseRefName,url
```

Confirm `state` is `MERGED`, `mergedAt` is non-null, and note `mergeCommit.oid`, `author.login`, and `baseRefName`. A PR can be closed-not-merged, or merged into a branch other than the one you assumed — the JSON tells you which.

### 2. Confirm the CONTENT is actually on origin/main

A merge commit existing is not the same as its changes being present on the branch you build from. Fetch first — never trust the local snapshot.

```bash
git fetch origin <base> --quiet
git merge-base --is-ancestor <mergeCommit.oid> origin/<base> && echo "on origin/<base>" || echo "NOT on origin/<base>"
git grep -n '<string unique to the change>' origin/<base> -- <expected path>
```

Ancestry proves the merge commit is reachable from the branch tip. The `git grep` proves the substantive change — not just a merge marker — is in the tree. If the grep finds nothing, the claim is not confirmed even if state says MERGED.

### 3. Enumerate SIBLING PRs by author and time window

The reporter named one PR. Find the others that landed in the same burst, so you build on the full picture, not a fragment.

```bash
gh pr list --state merged --limit 20 \
  --search "author:<author.login> sort:updated-desc" \
  --json number,title,mergedAt,headRefName,mergeCommit
```

Read the `mergedAt` timestamps. Look for PRs by the same author that merged within minutes of the named PR. They are likely part of the same stream of work. List each PR in that window in your verdict. A wide time gap marks the start of the cluster. Treat earlier merges as a separate stream unless you have a reason to include them.

## Quick Reference

| Check | Command | Confirms |
|---|---|---|
| State | `gh pr view <N> --json state,mergedAt,mergeCommit,author,baseRefName` | The PR is MERGED, into the base you expect |
| Content | `git fetch origin <base>` → `git merge-base --is-ancestor <oid> origin/<base>` + `git grep '<change>' origin/<base>` | The actual change is on the branch, not just a marker |
| Siblings | `gh pr list --state merged --search "author:<login> sort:updated-desc"` | No unreported PRs landed in the same window |

## Reporting the Verdict

State the verdict as CONFIRMED or NOT CONFIRMED, then:
- The merge commit and `mergedAt` for the named PR.
- Whether its content is present on `origin/<base>` (ancestry + grep result).
- **Every sibling PR** in the same author/time cluster, with numbers and timestamps — call out any the reporter did not mention.
- Anything you could not check from source (e.g. runtime behaviour of the change — verifying content is present is not verifying it works).

## Common Mistakes

| Mistake | Fix |
|---|---|
| Verifying only the named PR | Always run check 3 — the sibling enumeration is the point. |
| Trusting `state: MERGED` alone | A merge marker isn't the content. Run the `git grep` on `origin/<base>`. |
| Skipping `git fetch` | The local snapshot can be stale. Fetch before checking ancestry. |
| Assuming the base branch | Read `baseRefName` from the JSON; the PR may not target `main`. |
| Reporting "merged, works" | You verified presence, not behaviour. Separate the two in the verdict. |
