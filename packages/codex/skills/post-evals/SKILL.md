---
name: post-evals
description: Validate and post a fail-closed, SHA-bound eval summary as durable evidence on a GitHub pull request.
---

# Post evals

Post an existing `evals.json` as a machine-marked pull-request comment. Local or committed eval files are working material, not PR-readiness evidence.

Accept a pull-request number from the user's request. Before running any command, inspect it and require a non-empty digits-only value. Stop without interpolating it if invalid.

Use the package-local [post_evals.sh](../../scripts/post_evals.sh) and [eval-artifact.sh](../../scripts/lib/eval-artifact.sh), resolving both paths from this `SKILL.md` rather than from the current working directory.

## Procedure

1. Locate the existing `evals.json` produced for this pull request. Do not create or rewrite its claimed results.
2. Fetch the current head with `gh pr view <pr> --json headRefOid -q .headRefOid`. Treat an empty value or fetch failure as `NO-GO` and stop.
3. Run `post_evals.sh validate-structure <evals_json> <pr> <current_head_sha>`. This is the fail-closed structure gate, including PR-head binding, recorded smoke evidence, and current command/control execution. Stop on any failure.
4. Run `post_evals.sh validate-discriminating <evals_json>`. Stop on any malformed, environmental, or non-discriminating result.
5. Run `post_evals.sh compute-result <evals_json>` and read `.verification_level` with `jq`. Never accept a hand-written result. Stop unless the result is exactly `GO` or `NO-GO` and the verification level is `0`, `1`, or `2`.
6. Source `eval-artifact.sh` and call `eval_artifact::marker <pr> <current_head_sha> <result> <verification_level>`. The marker must remain bound to the validated pull request and its currently fetched head.
7. Build a temporary comment body that starts with that exact marker, summarizes P0/P1 pass and fail outcomes, includes amendments for human context, and ends with the complete source `evals.json` in one fenced `json` block. Do not hand-summarize or alter the embedded JSON.
8. Run `post_evals.sh validate-embed <evals_json> <comment_body>`. Stop without posting if it fails.
9. Resolve `owner/repo` with `gh repo view --json nameWithOwner -q .nameWithOwner`. Fetch issue comments with `gh api`, and compare their opening line to the exact marker. If an exact marker already exists, do not post a duplicate; report its URL.
10. Otherwise post with `gh api repos/<owner>/<repo>/issues/<pr>/comments -F body=@<comment_body>`. Do not use `gh pr comment`. Treat any fetch or post failure as `NO-GO` and do not claim an artifact exists.
11. Report the comment URL, computed result, verification level, and current head SHA.

Use securely created temporary files and remove them on success or failure. Never treat missing, stale, mismatched, rejected, untrusted, or unavailable evidence as success.
