---
name: verify-merged-pr
description: 'Use when an agent, teammate, CI report, or session summary claims a PR is merged and you are about to rely on that — before building on top of "it''s merged", trusting a headless builder''s report, or accepting a "done, PR landed" hand-off. Symptoms: someone gives you ONE PR number as the thing that landed, a status message says merged/shipped/live, or you need to confirm changes are actually on origin/main.'
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

A merge commit existing is not the same as its changes being present on the branch you build from. `scripts/verify_merged.py` applies the one rule set (it also re-runs check 1 and fetches, so never trust the local snapshot). Resolve it relative to this `SKILL.md` (`../../scripts/verify_merged.py`):

```bash
python3 <path to scripts/verify_merged.py> <N> --grep '<string unique to the change>' --path <expected path>
```

It prints a JSON verdict (`confirmed`, `method`, `reasons`) and exits 0 only when confirmed. State must be `MERGED` with `mergedAt` set; the base is fetched; the merge commit must be reachable from `origin/<base>`. Content verification requires the needle on `origin/<base>` and absent at the merge commit's first parent (`method: content`). A preexisting needle is refused (`content_preexisting`); an unreadable parent or other grep error is `content_check_failed`. Restore missing history before retrying. Without `--grep` it can confirm only a true merge commit (two parents) whose PR head is an ancestor of `origin/<base>` (`method: merge-commit-ancestry`). A squash requires `--grep`; it rewrites the SHA and never requires PR-head ancestry. Missing content (`content_absent`) or a missing required needle (`content_check_required`) leaves the claim unconfirmed. A needle added later on base can satisfy the content rule; it does not prove which PR added it.

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
| Content | `scripts/verify_merged.py <N> --grep '<change>' --path <path>` (fetch, reachability, `git grep` at `origin/<base>`) | The actual change is on the branch, not just a marker |
| Siblings | `gh pr list --state merged --search "author:<login> sort:updated-desc"` | No unreported PRs landed in the same window |

## Reporting the Verdict

State CONFIRMED or NOT CONFIRMED. Then report:
- The merge commit and `mergedAt` for the named PR.
- Whether its content is present on `origin/<base>` (the script's `method` and `reasons`).
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
