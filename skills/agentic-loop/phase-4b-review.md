# Phase 4b — PR review, in full

Detail-carrier for [SKILL.md](SKILL.md)'s Phase 4b. The main skill keeps the imperative (invoke
`/pr-review-toolkit:review-pr <PR#>`, then `/coderails:post-review <PR#>`, before merge); this file
is the six-reviewer breakdown, the security/deploy-safety add-ons, the clean-break gate, and the
worktree-teardown mechanics you consult while running it.

**Graph dispatch boundary.** `U4b-review` and `U4b-merge-gate` deliberately have no direct target
in `graph_dispatch.sh`: each is a workflow gate with several required actions, not one agent job.
`graph_dispatch_plan` therefore reports them as `unresolved:true`. Use the Skill-based review,
artifact, eval, and merge sequence documented below.

When a phase reaches "review the PR" (after a `/workflow` agent has pushed a PR, before merge), invoke the **`/pr-review-toolkit:review-pr <PR#>`** Skill — passing the PR number as the argument — which itself fans out the six specialised reviewers plus a security pass. Do NOT hand-roll the reviewers as separate `Agent` or `Task` spawns; use the Skill invocation.

**Invoking `/pr-review-toolkit:review-pr <PR#>` with the PR number is REQUIRED to satisfy the merge gate, because `enforce_pr_workflow` only accepts the `review-pr` Skill (with the PR number in args) as merge evidence — a manually-spawned agent fanout leaves no evidence the gate recognises and the merge will block.** The gate also recognises `scripts/merge.sh <PR#>` invocations (not just raw `gh pr merge`) as the same merge subcommand, so a hand-rolled review cannot merge through the wrapper script either.

**Review verification_level ladder.** All verification levels — regardless of the PR's own eval-artifact verification_level (a separate, orthogonal check) — invoke `/pr-review-toolkit:review-pr <PR#>` (the toolkit self-scales its reviewer fan-out by change shape) plus `/coderails:post-review <PR#>`. Only at verification_level 0 MAY the separate `/security-review` pass below be skipped, and only after checking the actual diff file list (`gh pr diff <PR#> --name-only` or `git diff origin/main...HEAD --name-only`): any path under `hooks/` or `scripts/`, or any change touching auth/exec/network-fetch code, FORCES the security pass regardless of declared verification_level. The override keys off the diff, never the self-assigned verification_level label. Verification level 1/2 PRs run the full Phase 4b unchanged, security pass included.

**After `review-pr` completes and all applied findings (blocking and worthwhile) are committed and pushed, invoke `/coderails:post-review <PR#>`.** This posts the SHA-bound review artifact — a machine-marked GitHub comment — that the `/merge` gate requires before merging. Loop symmetry: this is the same artifact gate that `/coderails:workflow`'s Phase 3 wires in for non-loop use. Both paths produce the same artifact; `/merge` checks both the same way. Run `post-review` after findings are applied and the follow-up commit is pushed, so the artifact is stamped against the final head SHA.

Before `/coderails:merge`, the loop must also produce a second, independent artifact: run `/coderails:task-evals` (scope: `pr`; docs-only/single-unit PRs that meet its verification_level-0 predicate get the lightweight exemption path) then `/coderails:post-evals`. `scripts/merge.sh` hard-gates on this eval artifact separately from the review artifact above — same fail-closed posture, no config opt-out.

**Worktree teardown, immediately after `/coderails:merge` confirms this work-unit's PR is merged.** A work-unit's worktree (created per the `origin/main`-based instruction above) is scoped to that one PR — once it's merged, the worktree has no further purpose and must not be left to accumulate across a multi-work-unit loop. Clean up the worktree using `superpowers:finishing-a-development-branch`'s Step 6 mechanics — the commands, provenance check, and cwd-pinned-worktree caveat are in [finishing-out.md](finishing-out.md). When the worktree is the orchestrator's own cwd, teardown uses the native exit-worktree tool (e.g. `ExitWorktree`) rather than `git worktree remove` — see finishing-out.md for the lock-case split. (The PR is already merged via `/coderails:merge` at this point, so this is the Step 6 cleanup only, not the skill's push/PR outcome-selection.) This runs per-work-unit at this point in Phase 4b — not deferred to Phase 9/13's loop-level teardown, which handles wiki/retro artifacts, not worktrees.

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

**Plus the native `/security-review` pass.** Alongside the six agents, run Claude Code's built-in `/security-review` on the same branch diff as part of this gate — it is a dedicated security review (auth/authz surfaces, injection, secret leakage, unsafe deserialisation, SSRF) that the six general reviewers do not specialise in. Run it in the worktree so it sees the branch's pending changes. Fold its findings into the same Critical / Important / Suggestion aggregation; any security MERGE-BLOCKER blocks merge exactly like a code finding (Phase 5/10) BEFORE merge.

**Plus `subagent_type: coderails:deploy-safety-reviewer` when the change has a runtime/production surface.** This is a coderails repo agent, not one of the six `pr-review-toolkit` reviewers above, and does not substitute for the `review-pr` Skill invocation the merge gate requires. Spawn it as a separate `Agent` call, alongside the six and the security pass, for any change with a runtime/production surface — not just schema/migration or flag/infra-config diffs, but any change that ships to production (matching the agent's own wrong-agent tripwire, which returns NOT APPLICABLE for docs-only/comment-only/test-only diffs). It reviews rollback risk, blast radius, deploy-time observability coverage, and migration/rollout safety, none of which the six reviewers or `/security-review` cover. Fold its findings into the same Critical / Important / Suggestion aggregation; a DO NOT SHIP verdict blocks merge exactly like a code finding (Phase 5/10) BEFORE merge.

**Clean-break gate (when the unit's disposition is `clean-break`).** The `code-simplifier` pass — already independent of the worker (separately spawned, read-only) — is additionally instructed to hunt **relabelled compatibility**: a surviving old code path renamed to "fallback", "adapter", "guard", "transitional", or "bridge". It checks whether an **old code path still executes**, not whether the literal word "shim" appears. On a clean-break unit, its findings of surviving compat are **MERGE-BLOCKERS**, not row 6's default report-only suggestions. **The orchestrator cannot downgrade this finding unilaterally.** Its only two moves: (a) fix it — remove the compat path, or (b) declare a hard-stop and hand it to a human, logged with who/when/SHA/reason. If a fully-unattended envelope cannot tolerate ever hard-stopping here, the human must grant auto-demote authority explicitly **at envelope-authorisation time** (Phase 0) — never something the orchestrator grants itself mid-run. The why: letting the orchestrator grade an independent reviewer's finding reintroduces the same self-attestation loophole one level up.

**Do not substitute the generic `architect-review` + `debugger` + `ai-engineer` trio here.** That trio is a separate general-purpose adversarial pattern for design stress-tests before a thing is built — it is NOT the PR-review step. The canonical review step is `/pr-review-toolkit:review-pr all` = the six agents above. PR review is a specialised gate requiring knowledge of the codebase's review culture and the PR's own change shape; a generic agent cannot carry that context.
