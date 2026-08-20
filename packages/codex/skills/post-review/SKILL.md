---
name: post-review
description: Post a fail-closed, SHA-bound GitHub PR artifact from a completed review by spawned Codex custom agents.
---

# Post review

Create the durable review comment consumed by the Coderails merge gate.

## Input gate

Require an explicitly supplied PR number. Inspect it before using it in any command: it must be non-empty and contain digits only. Stop without making a network change if it is invalid.

## Native Codex review evidence

Resolve the PR's current `headRefOid`, then use `spawn_agent` to run the relevant installed Codex custom reviewer agents against that exact PR head. Wait for every reviewer. Use only their observed findings; never invent or silently omit a finding.

Stop without posting when:

- no spawned Codex custom reviewer completed successfully;
- any reviewer result is missing or ambiguous;
- the PR head changes before posting; or
- findings were fixed after the review, making the review stale. Review the new head first.

Record the reviewer-reported counts. If every reviewer reports no findings, the summary body must contain only:

```markdown
## No findings
```

Otherwise, use these headings in order, with at least one bullet or `None` under each:

```markdown
## Critical
None

## Important
- Observed finding.

## Suggestions
None
```

Keep the reviewer names and exact critical, important, and suggestion counts in the posting report. Do not add them to a no-findings body because the validator's no-findings form is intentionally exact.

## Package helpers

Resolve these links relative to this `SKILL.md`, never relative to the repository working directory:

- [post_review.sh](../../scripts/post_review.sh) validates the summary.
- [review-artifact.sh](../../scripts/lib/review-artifact.sh) constructs the marker shared with the merge gate.

The helpers must exist and load successfully. Stop if either is missing or fails. Do not substitute another helper or construct the marker by hand.

## Validate and post

1. Create private temporary summary and body files with `mktemp`, and register a cleanup trap.
2. Write the review summary using the required grammar.
3. Run the resolved `post_review.sh validate <summary-file>`. Stop on any non-zero result.
4. Fetch `headRefOid` again and require exact equality with the reviewed SHA.
5. Source the resolved `review-artifact.sh` and call `review_artifact::marker <PR> <reviewed-SHA>`. Require a non-empty marker.
6. Prepend the marker as the first line of the body file.
7. Resolve `nameWithOwner` with `gh repo view`. Require a non-empty value.
8. Fetch all issue comments for the PR with `gh api`. Treat any fetch or parse failure as fatal. If an existing comment starts with the exact marker, do not post a duplicate; use its URL.
9. Fetch `headRefOid` once more and require exact equality with the reviewed SHA.
10. If no matching artifact exists, post the body with `gh api` and require a returned comment URL. Do not use `gh pr comment`.
11. Fetch `headRefOid` after posting. If it changed, report that the new artifact is stale and must not satisfy the merge gate.

The GitHub PR comment is authoritative. Do not read or write local review caches.

Report the PR number, reviewed SHA, spawned reviewer names and counts, whether the artifact was reused or posted, and the comment URL.
