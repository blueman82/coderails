---
name: verify-merged-pr
description: Use when an agent, teammate, CI report, or session summary claims a PR is merged and you are about to rely on that — before building on top of "it's merged", trusting a headless builder's report, or accepting a "done, PR landed" hand-off. Symptoms: someone gives you ONE PR number as the thing that landed, a status message says merged/shipped/live, or you need to confirm changes are actually on origin/main.
model: sonnet
---

# Verify Merged PR

## Overview

Check a reported PR merge before you rely on it.

Check the PR's merge status. Check its content on `origin/main`.
Check other PRs that merged in the same period.

A builder can merge multiple PRs and report only one. Check related PRs
so the handoff covers the full set of changes.

## When to Use

- An agent, teammate, CI report, or session summary says a PR merged,
  shipped, or went live.
- You will build, deploy, or hand off work that depends on that merge.
- A builder or loop reports one merged PR number.
- You must check that the changed content is on `origin/main`.

Do not use this skill if you completed and observed the merge in this
session. An open or draft PR has no merge to check.

## The Three Checks

Run all three checks. Report CONFIRMED only if the merge status, content, and sibling checks are correct. Use the PR number, author, and a grep string unique to the change.

### 1. Re-derive the merge STATE from gh

```bash
gh pr view <N> --json state,mergedAt,mergeCommit,author,headRefName,baseRefName,url
```

Make sure that `state` is `MERGED` and `mergedAt` is not null.
Record `mergeCommit.oid`, `author.login`, and `baseRefName`.
The PR could be closed without a merge. It could target a different base.
Use the JSON fields to tell which condition applies.

### 2. Confirm the CONTENT is actually on origin/main

The branch you build from can have the merge commit without the changed content. Run `scripts/verify_merged.py` to check the content. The script fetches the base and does check 1 again. Do not use only a local snapshot.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify_merged.py" <N> --grep '<string unique to the change>' --path <expected path>
```

It prints a JSON verdict (`confirmed`, `method`, `reasons`). Exit code 0 means the check succeeded. The merge status must be `MERGED` with `mergedAt` set. The script fetches the base. The merge commit must be reachable from `origin/<base>`.

For the content check, the needle must be on `origin/<base>`. It must not be at the merge commit's first parent (`method: content`). The script refuses a preexisting needle (`content_preexisting`). An unreadable parent or other grep error gives `content_check_failed`. Put back missing history before retrying.

Without `--grep`, the script can check only a merge commit with two parents. The PR head must be an ancestor of `origin/<base>` (`method: merge-commit-ancestry`). For a squash, use `--grep`. A squash rewrites the SHA and the check does not use PR-head ancestry.

Missing content (`content_absent`) or a missing mandatory needle (`content_check_required`) leaves the claim unconfirmed. A subsequent commit on the base can add a needle that satisfies the content rule. The rule does not identify the PR that added the needle.

### 3. Enumerate SIBLING PRs by author and time window

The reporter named one PR. Find other PRs that merged in the same period.

```bash
gh pr list --state merged --limit 20 \
  --search "author:<author.login> sort:updated-desc" \
  --json number,title,mergedAt,headRefName,mergeCommit
```

Read the `mergedAt` timestamps. Find PRs by the same author that merged
a small number of minutes before or after the named PR. List each one in your verdict.

A long time between merges can show a different work stream. Include earlier merges only if you can show why they apply.

## Quick Reference

| Check | Command | Result |
|---|---|---|
| Merge status | `gh pr view <N> --json state,mergedAt,mergeCommit,author,baseRefName` | The PR is MERGED into the correct base |
| Content | `scripts/verify_merged.py <N> --grep '<change>' --path <path>` (fetch, reachability, `git grep` at `origin/<base>`) | The actual change is on the branch, not only a marker |
| Siblings | `gh pr list --state merged --search "author:<login> sort:updated-desc"` | No unreported PRs landed in the same window |

## Reporting the Verdict

Use the verdict `CONFIRMED` or `NOT CONFIRMED`. Then report:
- The merge commit and `mergedAt` for the named PR.
- If its content is available on `origin/<base>` (the script's `method` and `reasons`).
- **Each sibling PR** in the same author/time cluster, with numbers and timestamps. Identify the PRs the reporter omitted.
- Anything you could not check from source (e.g. runtime behaviour of the change — checking content is available is not checking it works).

## Common Mistakes

| Mistake | Correct |
|---|---|
| Checking only the named PR | Always run check 3 — the sibling enumeration is the point. |
| Trusting `state: MERGED` alone | A merge marker is not the content. Run the `git grep` on `origin/<base>`. |
| Skipping `git fetch` | The local snapshot can be stale. Fetch before checking ancestry. |
| Guessing the base branch | Read `baseRefName` from the JSON. The PR may not target `main`. |
| Reporting "merged, works" | Say that you checked the branch content. Report runtime behavior only if you tested it. |
