---
name: workflow
description: Run the full Coderails Codex change workflow from worktree preparation through native review, evidence posting, merge, and optional wiki updates.
---

# Coderails workflow

Use this for a complete code-change workflow. Invoke Coderails Codex skills explicitly and use `spawn_agent` only with installed Codex custom agents.

Maintain the phases with `update_plan`. There are two required pauses: wait after preparation for the user to finish coding, then wait again for explicit merge approval.

## 1. Prepare

Obtain a branch name matching `feature/*`, `bug/*`, or `bugfix/*` and an optional summary. If the branch is missing or ambiguous, ask one focused question with `request_user_input`; never invent it.

Invoke `$coderails-codex:prep` with the branch and summary. Work only in the worktree it returns. Report the worktree path and any issue key it creates.

If a project wiki is configured, invoke `$coderails-codex:wiki-query` for known constraints, open gaps, adjacent behavior, and assumptions not enforced in code. Surface material findings before coding. For a substantial design, spawn two or three relevant Codex custom agents in parallel to challenge the design, record every finding as accepted or skipped with a reason, and update the design before coding.

Pause while the user implements and tests the change. Continue only when they say it is ready to push.

## 2. Preflight and push

Inspect the cumulative diff against the base branch. Invoke `$coderails-codex:engineering-principles` when configured paths are touched or any changed file has at least 20 changed lines. Treat architectural violations as blocking and style-only advice as non-blocking.

Invoke `$coderails-codex:push`. Capture the pull request number and URL. Stop if push, tests, or pull-request creation fails.

## 3. Native Codex review and evidence

Review only the final pull-request head. Spawn the applicable installed Codex custom agents in parallel, normally including:

- `source-auditor` for correctness and changed-code risks.
- `spec-reviewer` for requirement and contract coverage.
- `proof-author` for meaningful verification evidence.
- `deploy-safety-reviewer` when deployment, migration, configuration, or rollback risk exists.

Give each agent the pull-request number, exact head SHA, relevant requirements, and a distinct review focus. Cap a review wave at three concurrent agents.

Apply blocking and worthwhile findings, add or update tests where the public contract changed, then push the follow-up commit. Skip only cosmetic or subjective findings and record why. If the head changes, re-run the affected review and verification against the new exact head.

Post a pull-request ledger listing every finding and its disposition. Invoke `$coderails-codex:post-review` with the pull-request number only after fixes are pushed so the review artifact is bound to the final head SHA.

Invoke `$coderails-codex:task-evals` if graded evals were not already frozen, run the frozen checks and negative controls, then invoke `$coderails-codex:post-evals` with the pull-request number. Missing, stale, failing, or unverified evidence is a hard stop; never hand-write a passing result.

Report the pull-request URL, final head SHA, review summary, and eval result. Pause until the user explicitly approves merging.

## 4. Merge and wiki

After approval, invoke `$coderails-codex:merge` with the pull-request number. The merge must remain fail-closed on current-head review evidence, eval evidence, required status checks, or remote fetch failures.

If a wiki is configured, invoke `$coderails-codex:wiki-ingest`. Invoke `$coderails-codex:wiki-lint` immediately only for direct-write wiki mode; for wiki pull-request mode, defer lint until the ingest pull request has merged.

Report the merge commit SHA, wiki source path when applicable, and any follow-up lint work.

## 5. Cleanup

After confirming the pull request is merged and local main is current, remove the feature worktree and delete the local branch. If normal branch deletion refuses, investigate; do not force-delete it merely to silence the refusal.

The user may explicitly skip or revisit a phase. Otherwise preserve the order: prepare, code, push, native Codex review, post review and eval evidence, merge, then wiki.
