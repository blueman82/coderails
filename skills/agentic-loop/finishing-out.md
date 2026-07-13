# Finishing out

Detail-carrier for two loop-finish mechanics referenced from the main skill by a one-line
link each: the orchestrator's own completion claim (Phase 13), and per-work-unit branch
cleanup (Phase 4b).

## Orchestrator-level verification-before-completion at loop finish-out

SKILL.md's two existing `verification-before-completion` references (Phase 3/3a worker
construction-discipline lines) discipline the WORKERS' claims. Nothing disciplines the
ORCHESTRATOR's own final completion claim. Before the Phase 13 `complete` LOOP-STOP
declaration, the orchestrator applies `coderails:verification-before-completion` to its
OWN completion claim — "all authorised work done, all gates passed" is itself a
completion claim that requires fresh verification evidence, not recall.

Concretely, before declaring `complete`, re-run the evidence the claim rests on:
- each merged PR's `mergedAt` via `gh pr view` — the single final aggregate check that
  every unit's terminal artifact actually exists;
- the loop-scope eval `result` from `post_evals.sh grade-loop`;
- the wiki/sync-docs artifacts landed on origin/main.

**Scoping.** This gates ONLY the Phase 13 `complete` declaration, NOT each per-unit merge
claim — Phase 12 already covers per-unit merge-claim re-checks, and adding VBC per-merge
here would duplicate Phase 12. This is the single aggregate check at loop end, not a
repeat of the per-merge one.

## Per-unit branch finishing via finishing-a-development-branch

When a work-unit's PR is merged, finish the branch/worktree using
`coderails:finishing-a-development-branch`'s Step 6 mechanics: `cd` to main repo root,
`git worktree remove <path>`, `git worktree prune` — gated by the provenance check: only
remove worktrees the loop itself created (under `.worktrees/`/`worktrees/`), never a
harness-owned workspace. This runs per-work-unit at Phase 4b, not deferred to the
loop-level teardown.

**Caveat — never remove the worktree that is the shell's current cwd.** Removing the
session's own cwd-pinned worktree breaks the shell. `cd` to the main repo root FIRST,
then remove. If the loop's own cwd is inside the worktree being finished, this is
mandatory, not optional — a real failure this subsystem hit.
