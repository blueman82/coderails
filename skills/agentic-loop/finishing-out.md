# Finishing out

This file gives two procedures from the loop skill.
The first checks the orchestrator’s Phase 13 claim.
The second removes worktrees for merged work units in Phase 4b.

## Orchestrator-level superpowers:verification-before-completion at loop finish-out

The graph’s `S13-complete` node and the two `superpowers:verification-before-completion` instructions in SKILL.md apply to worker claims in Phases 3 and 3a.
The orchestrator must check its own claim too.
Before you record the Phase 13 `complete` stop with `graph.py stop --category complete`, apply `superpowers:verification-before-completion`.
Then write the status line for the user.

The claim "all authorised work done, all gates passed" must come from new verification results.
Before you declare `complete`, do these checks again:

- Use `gh pr view` to read each merged PR's `mergedAt`. Check each unit's terminal artifact.
- Read the loop-scope eval `result` from `post_evals.py grade-loop`.
- Check that the wiki and sync-docs artifacts are on `origin/main`.

Do this aggregate check only for the Phase 13 `complete` declaration.
Phase 12 checks the claim for each unit’s merge.

## Per-unit branch finishing via superpowers:finishing-a-development-branch

After a work unit’s PR merges, follow Step 6 of `superpowers:finishing-a-development-branch`.
Do this for each unit in Phase 4b before loop teardown.
Remove only worktrees that the loop made in `.worktrees/` or `worktrees/`.
Do not remove a workspace that belongs to the harness.

For the Git procedure, `cd` to the primary repo root and check the lock status.
If the checks below allow removal, run `git worktree remove <path>` and `git worktree prune`.

**Use the native tool first if it owns the worktree.**
Step 1a of `superpowers:using-git-worktrees` prefers the native worktree tool to `git worktree add` for entry.
Follow the same rule for teardown.
If a native tool such as `ExitWorktree` owns this worktree, use it.
Use the Git procedure if the native tool does not own the worktree.
If a lock means you must defer removal, follow the lock procedure below.

**`ExitWorktree` owns only worktrees made by `EnterWorktree` in this session.**
The `path` parameter lets `EnterWorktree` select an existing worktree without owning it.
For example, Step 1b of `superpowers:using-git-worktrees` uses `git worktree add` before selecting a path.
For that worktree, `ExitWorktree` gives only `action: "keep"`.
It cannot use `"remove"`.
Without an active `EnterWorktree` session, it reports that there is no active worktree and makes no changes.

If you get a `"keep"` result or a no-op, the worktree remains.
Use the Git procedure.
Run `cd` to the primary repo root, then run `git worktree remove` as described in Step 6.

**Change out of the worktree before using Git to remove it.**
As the `Common Mistakes` section in `superpowers:finishing-a-development-branch` says, `git worktree remove` fails if the shell’s cwd is the worktree it removes.
For the Git procedure, `cd` to the primary repo root first.

**Check a locked worktree against this session’s cwd.**
Step 6 checks the lock before removal.
The repo does not give the agent its harness session PID. You cannot compare it to the PID in a lock.
Check if the locked path is this session’s cwd.

- **The path is this session’s cwd.** The harness can lock it for this session. A PID in the lock text alone does not change the check. If the native tool owns this worktree, use `ExitWorktree` with `action: "remove"`. It exits the worktree and removes it in one step. Do not use Git to override a lock from that worktree.
- **The path is different from this session’s cwd.** If a different live session owns the lock, report it and defer removal. Do not override the lock. A merged PR does not make removal safe while that session uses the worktree.

If the lock identifies a different live session, defer removal regardless of access from this session.
If the lock identifies a dead PID, clear the stale lock, remove the worktree, and report it.

**For a squash merge, check content identity.**
With `action: "remove"`, `ExitWorktree` refuses to discard uncommitted files or commits missing from the initial branch.
A squash merge can include the changes in `origin/main` with different commit SHAs.
Then `git log --oneline origin/main..HEAD` continues to list the branch commits.
It cannot show that the content merged.
A check that requires this list to be empty can defer removal indefinitely.

Run `git diff origin/main HEAD` to check that the content matches byte for byte.
Use `gh pr view <n> --json state` to check for `state: MERGED`.
Use `discard_changes: true` only if the diff has no differences and the PR has that status.
If a check fails, do not use `discard_changes: true`.
