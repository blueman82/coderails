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
is available (e.g. `ExitWorktree`) **and it owns this worktree**, prefer it over the
`git worktree remove` mechanics above. The git path below is the fallback both for
worktrees the native tool does not own, and for worktrees it does own but a lock
resolution below says to defer instead of remove.

**Scope limit — `ExitWorktree` only owns what it created this session.** It operates
only on a worktree created by `EnterWorktree` *in this same session*. A worktree
switched into via `EnterWorktree`'s `path` parameter (e.g. one created by
`git worktree add` per `using-git-worktrees` Step 1b, then entered by path) is NOT owned
by it — calling `ExitWorktree` there yields `action: "keep"` only, never `"remove"`.
Called with no active `EnterWorktree` session at all, it is a silent no-op: it reports no
active worktree session and changes nothing on disk. In either case, do not treat a
`"keep"` result or a no-op as removal — fall back to the git path: `cd` to the main repo
root, then `git worktree remove` (Step 6 mechanics above).

**Caveat — never remove the worktree that is the shell's current cwd, via `git worktree
remove`.** `git worktree remove` fails when run from inside the worktree being removed
(per `finishing-a-development-branch`'s Common Mistakes). If using the git fallback,
`cd` to the main repo root FIRST, then remove — mandatory, not optional, when the loop's
own cwd is inside the worktree being finished.

**Caveat — a locked worktree splits into two cases that need opposite actions, and the
cwd check takes precedence.** Step 6 checks lock state before removing. The operative
test is executable directly: is the locked worktree path this session's own cwd? Nothing
in this repo gives an agent its own harness session pid to compare against the lock's
pid, so pid-naming is explanation, not the check to run.

- **The locked path is this session's own cwd** — NOT a defer case, even if the lock
  reason also happens to name a pid. The lock exists because the harness locked the
  worktree on the calling session's behalf, not because another session is using it. Use
  the native `ExitWorktree` tool with `action: "remove"` (subject to the scope limit
  above), which exits the session from the worktree and removes it in one step — `git
  worktree remove` cannot do this from inside the worktree it's removing, and forcing the
  git path would break the running session.
- **The locked path is NOT this session's own cwd** — some other session is still
  working in the worktree. Report and defer, never force, regardless of whether the
  worktree is also this session's cwd for some other reason. A merged PR does not by
  itself mean the worktree is safe to remove — forcing it out mid-loop would yank that
  other session. This precedence holds even when the lock also happens to be reachable
  from this session: a live pid naming a different session always wins over any other
  fact about the worktree.

Locked by a dead pid still means: clear the stale lock and remove, with a notice.

**Caveat — the squash-merge safety check must use content identity, not ancestry.**
`ExitWorktree` with `action: "remove"` refuses when the worktree has uncommitted files or
commits not on the original branch, reporting them as work that would be discarded. After
a SQUASH merge those commits are legitimately merged, but `git log --oneline
origin/main..HEAD` being empty is NOT the right confirmation — it can never pass here.
Squash rewrites the SHAs that land on `origin/main`, so the branch's own original commit
SHAs never appear in `origin/main`'s ancestry, and `origin/main..HEAD` keeps listing them
forever, even though their content already landed. Checking ancestry after a squash
reproduces the exact failure this caveat exists to prevent: the agent can never pass
`discard_changes: true`, so it defers forever on work that is genuinely done.

Confirm the content actually merged instead: `git diff origin/main HEAD` shows no
differences (the worktree's content is already present on `origin/main`, byte for byte —
squash preserves content identity even though it discards ancestry) AND the PR reports
`state: MERGED` (`gh pr view <n> --json state`). Only pass `discard_changes: true` once
both hold. Never pass `discard_changes: true` on a refusal you haven't verified this way.
