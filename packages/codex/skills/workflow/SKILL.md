---
name: workflow
description: Run the full Coderails Codex change workflow from worktree preparation through native review, evidence posting, merge, and optional wiki updates.
---

# Coderails workflow

Use this for a complete code-change workflow. Invoke Coderails Codex skills explicitly.
Use the package-local `codex_role_session.py` for guarded reviewers.
Use `spawn_agent` for other installed Codex custom agents.

Keep the phases current with `update_plan`.
Pause after you prepare the worktree until the user finishes coding. Pause again before merge until the user gives explicit approval.

## 1. Prepare

Get a branch name that matches `feature/*`, `bug/*`, or `bugfix/*` and an optional summary.
If you have no branch name or it is ambiguous, use `request_user_input` to get it. Do not invent it.

Invoke `$coderails-codex:prep` with the branch and summary.
Work only in the worktree it gives. Report the worktree path and the issue key if it makes one.

If the project config has a wiki, invoke `$coderails-codex:wiki-query`.
Look for known constraints, open questions, related behavior, and assumptions the code does not check.
Give material results before coding.

For a substantial design, start two or three applicable Codex custom agents in parallel to challenge it.
Record the outcome for each result. Say why you accepted or skipped it.
Update the design before coding.

Pause while the user implements and tests the change. Continue only when they tell you to push.

## 2. Preflight and push

Examine the cumulative diff against the base branch.
Invoke `$coderails-codex:engineering-principles` if configured paths changed or if one file has a minimum of 20 changed lines.
Architectural violations block the workflow. Style-only advice does not block it.

Invoke `$coderails-codex:push`. Record the PR number and URL.
Stop if the push, tests, or PR creation do not succeed.

## 3. Native Codex review and evidence

Examine only the last PR head. Select the applicable reviewers from this usual set:

- `source-auditor` to check the changed code and identify risks.
- `spec-reviewer` for requirement and contract coverage.
- `proof-author` for meaningful verification records.
- `deploy-safety-reviewer` when deployment, migration, configuration, or rollback risk exists.

Follow [guarded role sessions](../using-coderails/references/guarded-role-sessions.md).
Run `source-auditor` and `deploy-safety-reviewer` with `python3 "$SKILL_DIR/../../scripts/codex_role_session.py" --role <role> --prompt-file <file> --cwd <exact-head-worktree>`.
Start `spec-reviewer` and `proof-author` as native custom agents.

Give each agent the PR number, current head SHA, related requirements, and a different topic to examine.
Use a maximum of three concurrent agents in a wave.

Correct blocking and worthwhile results. Add or update tests where the public contract changed. Then push the follow-up commit.
Skip only cosmetic or subjective results and record why.
If the head changes, run the applicable inspection and verification again against the new head SHA.

Post a PR ledger with each result and what you did about it.
Push the corrections before you invoke `$coderails-codex:post-review` with the PR number.
This binds the inspection artifact to the last head SHA.

If there are no frozen graded evals, invoke `$coderails-codex:task-evals`.
Run the frozen checks and negative controls. Then invoke `$coderails-codex:post-evals` with the PR number.
Stop if you have no check records or if they are stale, unsuccessful, or unverified.
Do not write a result by hand to claim a check passed.

Report the PR URL, last head SHA, inspection summary, and eval result.
Pause until the user explicitly approves the merge.

## 4. Merge and wiki

After approval, invoke `$coderails-codex:merge` with the PR number.
Merge only if the inspection and eval records for the current head satisfy the gate.
Mandatory status checks and remote fetches must also succeed.

If a wiki is configured, invoke `$coderails-codex:wiki-ingest`.
In direct-write wiki mode, invoke `$coderails-codex:wiki-lint` immediately.
In wiki PR mode, wait for the ingest PR to merge before you invoke it.

Report the merge commit SHA and wiki source path if applicable. Report follow-up lint work if necessary.

## 5. Cleanup

Check that the PR has merged and local `main` is current. Remove the feature worktree and remove the local branch.
If regular branch removal does not work, investigate the cause. Do not override the refusal only to suppress the error.

If the user explicitly tells you to skip or repeat a phase, follow that instruction.
Use this sequence by default: prepare, code, push, examine with native Codex, post inspection and eval records, merge, then update the wiki.
