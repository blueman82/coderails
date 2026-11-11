# Phase 4b — PR review, in full

This file gives the Phase 4b steps for [SKILL.md](SKILL.md).
Before merge, invoke `/pr-review-toolkit:review-pr <PR#>` and then `/coderails:post-review <PR#>`.
Follow the rules below for reviewer selection, deployment safety, clean-break checks, and worktree cleanup.

**Boundary for graph dispatch.** Nodes `U4b-review` and `U4b-merge-gate` have no direct target in `graph_dispatch.py`.
Each gate has multiple steps.
The native graph CLI `plan` command reports them as `unresolved:true`.
Follow the Skill invocation, artifact, eval, and merge steps below.

When a phase says "review the PR", invoke **`/pr-review-toolkit:review-pr <PR#>`** as a Skill.
Give the PR number as its argument.
Do this after the `/workflow` agent pushes the PR and before merge.
The skill selects from six specialized reviewers based on the changes and does a check for vulnerabilities.
Do not start those reviewers in individual `Agent` or `Task` calls.

**The merge gate needs the Skill invocation and the PR number.**
The `enforce_pr_workflow` hook accepts only the `review-pr` Skill invocation with the PR number as an argument.
Individual agents do not give the gate this record, so it blocks merge.
The hook checks `scripts/merge.py <PR#>` and `gh pr merge`.
The wrapper script does not bypass this rule.

**Use verification_level to select the checks.**
All levels use `/pr-review-toolkit:review-pr <PR#>` and `/coderails:post-review <PR#>`.
The toolkit selects reviewers for the type of change.
Apply this check without using the eval artifact’s verification_level.

At verification_level 0, you can skip the native `/security-review` pass only after checking the diff.
Use `gh pr diff <PR#> --name-only` or `git diff origin/main...HEAD --name-only`.
Run the pass if the diff touches `hooks/`, `scripts/`, or code for authentication, authorization, command execution, or network fetches.
Use the diff to select the checks, regardless of the declared verification_level.
At verification_level 1 or 2, run all Phase 4b steps with `/security-review`.

**Post the SHA-bound artifact after the corrections.**
Finish `review-pr`.
Commit and push corrections for the blocking issues and other issues you select.
Then invoke `/coderails:post-review <PR#>`.
It posts a machine-marked GitHub comment for the last head SHA.
The `/merge` gate checks that comment.

Phase 3 of `/coderails:workflow` posts the same artifact for work without a loop.
The `/merge` gate applies the same check to each artifact.

**Post the eval artifact before merge.**
Run `/coderails:task-evals` at scope `pr`, then run `/coderails:post-evals`.
Docs-only or single-unit PRs can use the lightweight path if they satisfy its verification_level-0 predicate.
The `scripts/merge.py` gate checks the eval artifact independently of the reviewer artifact.
It blocks if the check does not succeed.
There is no config opt-out.

**Remove the worktree immediately after its PR merges.**
After `/coderails:merge` checks that the unit’s PR merged, finish the worktree for that unit.
The worktree based on `origin/main` serves one PR.
Remove it during Phase 4b for that unit.
Phases 9 and 13 handle wiki and retro artifacts.

Use Step 6 of `superpowers:finishing-a-development-branch` for cleanup.
See [finishing-out.md](finishing-out.md) for commands, worktree provenance, and lock checks.
If the worktree is the orchestrator’s cwd, use the native exit tool such as `ExitWorktree` as described there.
Do not run `git worktree remove` from the worktree.
Do the Step 6 cleanup only. The PR has merged.

Use the six reviewer roles below:

| # | Reviewer | Checks | Runs when |
|---|---|---|---|
| 1 | `code-reviewer` | General quality, CLAUDE.md compliance, and bugs | Always |
| 2 | `pr-test-analyzer` | Behavioral test coverage, mock tautology, and important missing tests | Test files change, which is usual |
| 3 | `silent-failure-hunter` | Errors suppressed by catch blocks, message loss, and error paths that report success | Error handling, catch blocks, or queue deletion changes |
| 4 | `type-design-analyzer` | Protocol and type invariants. Can the types admit invalid combinations? | New or changed types or protocol surfaces |
| 5 | `comment-analyzer` | Incorrect or stale comments and docstrings | New comments or docstrings, or code moves that change behavior |
| 6 | `code-simplifier` | Dead code from code moves, duplication, and code that is more complex than necessary | Always. It reports issues without editing. |

Collect all reports. Group results as `Critical`, `Important`, or `Suggestion`.
Send each `MERGE-BLOCKER` to a correction agent in Phase 5 or 10 before merge.

**Use the native `/security-review` pass when the rules above call for it.**
Run the built-in Claude Code command in the worktree on the same branch diff.
It checks authentication, authorization, attacks through injected input, secret leakage, and deserialization of untrusted data, and SSRF.
The six general reviewers do not specialize in those checks.
Group these results with the others.
A `MERGE-BLOCKER` from this pass blocks merge and goes to Phase 5 or 10.

**For a change with a runtime or production surface, start a deployment safety reviewer.**
Use its own `Agent` call with `subagent_type: general-purpose` and the instructions from `agents/deploy-safety-reviewer.md`.
Run this Coderails agent alongside the toolkit Skill invocation, its six reviewer roles, and the `/security-review` pass.
Run it for all changes that ship to production, such as migrations, flags, or infrastructure config changes.
The agent gives `NOT APPLICABLE` for docs-only, comment-only, or test-only changes.

It checks rollback risk, blast radius, deploy-time observability, and migration and rollout safety.
The six toolkit reviewers and `/security-review` do not check those areas.
Group the result with the other reports.
A `DO NOT SHIP` verdict blocks merge and goes to Phase 5 or 10.

**For `clean-break`, check for surviving compatibility paths.**
Start the read-only `code-simplifier` pass independently of the worker.
Tell it to check for a surviving code path renamed to "fallback", "adapter", "guard", "transitional", or "bridge".
Check if the previous path can run. The word "shim" is only a label.
A surviving path is a `MERGE-BLOCKER` for `clean-break`.

The orchestrator must correct it by removing the path or declare a hard stop for the user.
For a hard stop, log who, when, the SHA, and why.
The orchestrator cannot downgrade the blocker without authority from the user.
If a fully unattended loop cannot stop for this, the user must explicitly grant auto-demote authority in Phase 0 when they give the envelope.
The orchestrator cannot grant this authority to itself during the loop.
That would let the orchestrator approve its own response to a check by a different agent.

**Use `/pr-review-toolkit:review-pr all` for the six roles above.**
The generic `architect-review`, `debugger`, and `ai-engineer` trio is for design stress tests before implementation.
Do not use that trio for this gate.
The reviewer roles need the repo’s reviewer conventions and the PR diff.
