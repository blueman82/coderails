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
check lock state, `git worktree remove <path>`, `git worktree prune` — gated by the
provenance check: only remove worktrees the loop itself created (under
`.worktrees/`/`worktrees/`), never a harness-owned workspace. This runs per-work-unit at
Phase 4b, not deferred to the loop-level teardown.

**Native-first, same as entry.** `using-git-worktrees` Step 1a prefers a native worktree
tool over `git worktree add` for entry; teardown mirrors that. If a native worktree tool
is available (e.g. `ExitWorktree`), prefer it over the `git worktree remove` mechanics
above. The git path is the fallback for worktrees the native tool does not own.

**Caveat — never remove the worktree that is the shell's current cwd, via `git worktree
remove`.** `git worktree remove` fails when run from inside the worktree being removed
(per `finishing-a-development-branch`'s Common Mistakes). If using the git fallback,
`cd` to the main repo root FIRST, then remove — mandatory, not optional, when the loop's
own cwd is inside the worktree being finished.

**Caveat — a locked worktree splits into two cases that need opposite actions.** Step 6
checks lock state before removing. The lock reason embeds a pid
(`claude session <name> (pid NNNNN ...)`); which pid it names determines the action:

- **Locked by ANOTHER session's live pid** — some other session is still working in the
  worktree. Report and defer, never force. A merged PR does not by itself mean the
  worktree is safe to remove — forcing it out mid-loop would yank that other session.
- **Locked by THIS session's own pid, because the worktree is this session's own cwd** —
  this is NOT a defer case. The lock exists because the harness locked the worktree on
  the calling session's behalf, not because another session is using it. Use the native
  `ExitWorktree` tool with `action: "remove"`, which exits the session from the worktree
  and removes it in one step — `git worktree remove` cannot do this from inside the
  worktree it's removing, and forcing the git path would break the running session.

A locked-and-live worktree at Phase 4b where the live pid is a DIFFERENT session still
means defer, never force — that rule is unchanged. Locked by a dead pid still means:
clear the stale lock and remove, with a notice.

**Caveat — `ExitWorktree` can misfire right after a squash merge.** `ExitWorktree` with
`action: "remove"` refuses when the branch has commits, reporting them as work that
would be discarded. After a SQUASH merge those commits are legitimately merged — the
squash rewrote the SHAs, so a SHA-based check cannot see them on `origin/main` even
though their content landed. Before passing `discard_changes: true`, confirm the content
actually merged: `git log --oneline origin/main..HEAD` empty AND the PR reports `state:
MERGED`. Never pass `discard_changes: true` on an unverified refusal.
