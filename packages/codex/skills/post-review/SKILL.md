---
name: post-review
description: Post a fail-closed, SHA-bound GitHub PR artifact from a completed review by spawned Codex custom agents.
---

# Post review

Create the durable review comment consumed by the Coderails merge gate.

## Input gate

Require an explicitly supplied PR number. Inspect it before using it in any command: it must be non-empty and contain digits only. Stop without making a network change if it is invalid.

## Native Codex review evidence

Resolve the PR's current `headRefOid`. Run guarded reviewers through `python3 "$SKILL_DIR/../../scripts/codex_role_session.py" --role <role> --prompt-file <file> --cwd <exact-head-worktree>` per [guarded role sessions](../using-coderails/references/guarded-role-sessions.md); use `spawn_agent` for other installed Codex custom reviewers. Wait for every reviewer. Use only their observed findings; never invent or silently omit a finding.

Stop without posting when:

- no Codex reviewer completed successfully;
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

- [post_review.py](../../scripts/post_review.py) validates the summary.
- [review_artifact.py](../../scripts/lib/review_artifact.py) constructs the marker shared with the merge gate.

The helpers must exist and load successfully. Stop if either is missing or fails. Do not substitute another helper or construct the marker by hand.

## Validate and post

1. Create private temporary summary and body files with `mktemp`, and register a cleanup trap.
2. Write the review summary using the required grammar.
3. Run the resolved `post_review.py validate <summary-file>`. Stop on any non-zero result.
4. Fetch `headRefOid` again and require exact equality with the reviewed SHA.
5. Run `python3 <resolved review_artifact.py> <PR> <reviewed-SHA>`. Require a non-empty marker.
6. Prepend the marker as the first line of the body file. Then run the resolved `post_review.py compat-line <PR> <reviewed-SHA> --count <K> --disposition <D>` and insert its single output line directly after the marker. `K` is the number of reviewer findings that flag retained backward-compatibility code; `D` is `preserve-compat` when a work unit of this change was registered with `--disposition preserve-compat`, else `clean-break`. Both are reviewer judgement, not measurements. The merge gate refuses `clean-break` with `K > 0` (`compat_findings_nonzero`). A missing current-head line blocks with `compat_findings_missing`; post the line even when `K` is zero.
7. Resolve `nameWithOwner` with `gh repo view`. Require a non-empty value.
8. Fetch `headRefOid` once more and require exact equality with the reviewed SHA.
9. Post each completed review body with `gh api` and require a returned comment URL, even if this SHA already has an artifact. A corrected compatibility finding count must not reuse an older verdict. Do not use `gh pr comment`. The merge gate treats any refusing same-SHA compatibility line as dominant; clearing one requires a new code SHA.
10. Fetch `headRefOid` after posting. If it changed, report that the new artifact is stale and must not satisfy the merge gate.

The GitHub PR comment is authoritative. Do not read or write local review caches.

Report the PR number, reviewed SHA, spawned reviewer names and counts, and the posted comment URL.
