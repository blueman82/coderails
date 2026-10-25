# Phase 4b — PR review, in full

This file gives the Phase 4b review steps for [SKILL.md](SKILL.md). Invoke
`/pr-review-toolkit:review-pr <PR#>`, then `/coderails:post-review <PR#>`
before merge. Use the rules below for the six reviewers, security and
deployment safety, clean-break checks, and worktree cleanup.

**Graph dispatch boundary.** `U4b-review` and `U4b-merge-gate` have no direct target
in `graph_dispatch.py`. Each is a workflow gate that requires several actions.
The native graph CLI `plan` command reports them as `unresolved:true`. Follow the
Skill-based review, artifact, eval, and merge sequence below.

After a `/workflow` agent pushes a PR and before merge, invoke the
**`/pr-review-toolkit:review-pr <PR#>`** Skill with the PR number. It dispatches
six specialised reviewers and a security pass. Use the Skill invocation. Do
not spawn those reviewers yourself as separate `Agent` or `Task` calls.

**Invoke `/pr-review-toolkit:review-pr <PR#>` with the PR number to satisfy the
merge gate.** `enforce_pr_workflow` accepts only the `review-pr` Skill with the
PR number in its args as review evidence. A manually spawned agent fanout
leaves no evidence the gate recognises, so merge blocks. The gate checks
`scripts/merge.py <PR#>` as well as raw `gh pr merge`. The wrapper script does
not bypass this rule.

**Apply the review level rule.** At every verification_level, invoke
`/pr-review-toolkit:review-pr <PR#>` and `/coderails:post-review <PR#>`.
The toolkit sets its reviewer set from the change. The eval artifact's
verification_level is a separate check.

At verification_level 0, you can skip the separate `/security-review` pass
only after you inspect the actual file list. Use `gh pr diff <PR#>
--name-only` or `git diff origin/main...HEAD --name-only`. Run the security
pass if the diff touches `hooks/`, `scripts/`, or authentication, command
execution, or network fetch code. The diff takes precedence over a declared
level. At levels 1 and 2, run the full security pass.

**After `review-pr` completes, apply the blocking and worthwhile findings.
Commit and push them. Then invoke `/coderails:post-review <PR#>`.** It posts the
SHA-bound review artifact as a machine-marked GitHub comment. The `/merge` gate
requires that artifact for the final head SHA. `/coderails:workflow` Phase 3
uses the same `post-review` artifact gate outside a loop.

Before `/coderails:merge`, grade the PR-scope eval suite frozen in Phase 2.7d. Docs-only or single-unit PRs that meet its verification_level-0 predicate can use the lightweight exemption path. Then invoke `/coderails:post-evals`. If the frozen suite is missing, stop and disclose the gap; do not claim a new suite was frozen before build. `scripts/merge.py` gates on this artifact separately from the review artifact, with no config opt-out.

**Clean up the worktree after merge.** First, confirm that `/coderails:merge`
merged this unit's PR. Then apply Step 6 of
`superpowers:finishing-a-development-branch` to this unit's worktree. See
[finishing-out.md](finishing-out.md) for the commands, provenance check, and
locked-worktree case. If the orchestrator runs from that worktree, use the
native exit-worktree tool (for example, `ExitWorktree`). Do not call `git
worktree remove` on the current worktree. Do this for each unit in Phase 4b.
Phase 9 and 13 handle wiki and retrospective work, not unit worktrees.

The six review dimensions the Skill covers:

| # | Reviewer | Reviews | Runs when |
|---|---|---|---|
| 1 | `code-reviewer` | General quality + CLAUDE.md compliance, bugs | always |
| 2 | `pr-test-analyzer` | Behavioural test coverage, mock-tautology, critical gaps | test files changed (almost always) |
| 3 | `silent-failure-hunter` | Swallowed exceptions, message-loss, spurious-success error paths | error handling / catch blocks / queue-delete semantics changed |
| 4 | `type-design-analyzer` | Protocol/type invariants, illegal-states-unrepresentable | new/changed types or protocol surfaces |
| 5 | `comment-analyzer` | Comment/docstring accuracy, comment rot | comments/docstrings added or behaviour-changing extractions |
| 6 | `code-simplifier` | Dead code from extractions, duplication, over-engineering (report-only, no edits) | always (polish pass) |

Collect all reports, aggregate into Critical / Important / Suggestion, and feed any MERGE-BLOCKER back to a fix agent (Phase 5/10) BEFORE merge.

**Run the native `/security-review` pass when the level rule requires it.**
Run Claude Code's review in the worktree so it sees the branch diff. It checks
authentication, injection, secret exposure, unsafe deserialisation, and SSRF.
Add its findings to the Critical, Important, and Suggestion report. A security
MERGE-BLOCKER prevents merge until Phase 5 or 10 resolves it.

**Plus `subagent_type: general-purpose` with explicit instructions from `agents/deploy-safety-reviewer.md` when the change has a runtime/production surface.** This is a coderails repo agent, not one of the six `pr-review-toolkit` reviewers above, and does not substitute for the `review-pr` Skill invocation the merge gate requires. Spawn it as a separate `Agent` call, alongside the six and the security pass, for any change with a runtime/production surface — not just schema/migration or flag/infra-config diffs, but any change that ships to production (matching the agent's own wrong-agent tripwire, which returns NOT APPLICABLE for docs-only/comment-only/test-only diffs). It reviews rollback risk, blast radius, deploy-time observability coverage, and migration/rollout safety, none of which the six reviewers or `/security-review` cover. Fold its findings into the same Critical / Important / Suggestion aggregation; a DO NOT SHIP verdict blocks merge exactly like a code finding (Phase 5/10) BEFORE merge.

**Clean-break gate (when the unit's disposition is `clean-break`).** The `code-simplifier` pass — already independent of the worker (separately spawned, read-only) — is additionally instructed to hunt **relabelled compatibility**: a surviving old code path renamed to "fallback", "adapter", "guard", "transitional", or "bridge". It checks whether an **old code path still executes**, not whether the literal word "shim" appears. On a clean-break unit, its findings of surviving compat are **MERGE-BLOCKERS**, not row 6's default report-only suggestions. **The orchestrator cannot downgrade this finding unilaterally.** Its only two moves: (a) fix it — remove the compat path, or (b) declare a hard-stop and hand it to a human, logged with who/when/SHA/reason. If a fully-unattended envelope cannot tolerate ever hard-stopping here, the human must grant auto-demote authority explicitly **at envelope-authorisation time** (Phase 0) — never something the orchestrator grants itself mid-run. The why: letting the orchestrator grade an independent reviewer's finding reintroduces the same self-attestation loophole one level up.

**Do not substitute the generic `architect-review` + `debugger` + `ai-engineer` trio here.** That trio is a separate general-purpose adversarial pattern for design stress-tests before a thing is built — it is NOT the PR-review step. The canonical review step is `/pr-review-toolkit:review-pr all` = the six agents above. PR review is a specialised gate requiring knowledge of the codebase's review culture and the PR's own change shape; a generic agent cannot carry that context.
