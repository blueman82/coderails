---
name: post-review
description: Post a fail-closed, SHA-bound GitHub PR artifact from a completed review by spawned Codex custom agents.
---

# Post review

Create the durable review comment consumed by the Coderails merge gate.

## Input gate

Require an explicitly supplied PR number. Inspect it before using it in any command: it must be non-empty and contain digits only. The script validates it again in code (`pr_number_invalid`) before any network call; never paste a non-numeric value into a command.

## Native Codex review evidence

Resolve the PR's current `headRefOid`, then use `spawn_agent` to run the relevant installed Codex custom reviewer agents against that exact PR head. Wait for every reviewer. Use only their observed findings; never invent or silently omit a finding.

Stop without posting when:

- no spawned Codex custom reviewer completed successfully;
- any reviewer result is missing or ambiguous;
- the PR head changes before posting; or
- findings were fixed after the review, making the review stale. Review the new head first.

The merge gate computes which reviews the diff needs from `policy/review_policy.json`: a diff touching `hooks/`, `scripts/`, `install.py`, `uninstall.py`, `.claude-plugin/` or the Codex hook/script trees needs a `security-review` pass (spawn `security-reviewer`); `launchd/`, `scripts/integrity-gate/`, `scripts/installer/`, `.github/workflows/` or `skills/dashboard/runner/` needs a `deploy-safety` pass (spawn `deploy-safety-reviewer`). A pass verdict is derived from the validated summary text (a bullet under `## Critical` fails it), never asserted.

Record the reviewer-reported counts. Write one summary file per pass. If a reviewer reports no findings, its file must contain only:

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

## Package helper

Resolve [post_review.py](../../scripts/post_review.py) relative to this `SKILL.md`, never relative to the repository working directory. It must exist and load. Stop if it is missing or fails; do not substitute another helper or build the marker by hand.

## Post

Write the summary files with the file-writing tool (not a shell heredoc), then run the one command, replacing `<PR>` with the validated number:

```bash
python3 <resolved post_review.py> post <PR> --summary <review-summary-file> --pass security-review=<security-summary-file>
```

Omit `--pass NAME=FILE` for passes the diff does not need. The script validates every file, resolves the head, builds the marker and the passes line, reuses an identical existing artifact, refuses if the head moved before or after posting (`stale`), and posts with `gh api`. A non-zero exit means nothing usable was posted; fix the cause and re-run.

The GitHub PR comment is authoritative. Do not read or write local review caches.

Report the PR number, reviewed SHA, spawned reviewer names and counts, whether the artifact was reused or posted, and the comment URL.
