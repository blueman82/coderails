---
name: finishing-a-development-branch
description: Use when implementation is complete and all tests pass - autonomously ships the work (push + create PR by default) and cleans up the workspace, with no human checkpoint
effort: high
---

# Finishing a Development Branch

## Overview

Autonomously complete development work: verify, ship, clean up. No human
checkpoint — the default outcome (push + create PR) requires no decision,
so this skill runs to completion without asking.

**Core principle:** Verify tests → Detect environment → Auto-select outcome → Execute → Clean up.

**Announce at start:** "I'm using the finishing-a-development-branch skill to complete this work."

## The Process

### Step 1: Verify Tests

**Before shipping, verify tests pass:**

```bash
# Run project's test suite
npm test / cargo test / pytest / go test ./...
```

**If tests fail:**
```
Tests failing (<N> failures). Must fix before completing:

[Show failures]

Cannot proceed with merge/PR until tests pass.
```

Stop. Don't proceed to Step 2.

**If tests pass:** Continue to Step 2.

### Step 2: Detect Environment

**Determine workspace state before selecting the outcome:**

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
```

This determines which outcomes are available and how cleanup works:

| State | Available outcomes | Cleanup |
|-------|------|---------|
| `GIT_DIR == GIT_COMMON` (normal repo) | Push+PR (default), Merge locally, Discard | No worktree to clean up |
| `GIT_DIR != GIT_COMMON`, named branch | Push+PR (default), Merge locally, Discard | Provenance-based (see Step 6) |
| `GIT_DIR != GIT_COMMON`, detached HEAD | Push+PR (default), Discard (no local merge — no named branch to merge from) | No cleanup (externally managed) |

### Step 3: Determine Base Branch

```bash
# Try common base branches
git merge-base HEAD main 2>/dev/null || git merge-base HEAD master 2>/dev/null
```

Or ask: "This branch split from main - is that correct?"

### Step 4: Auto-Select Outcome

No human checkpoint here — this skill runs to completion autonomously.
Tests already passed (Step 1) and the workspace is verified (Step 2), so
the default outcome is always **push and create a Pull Request**: it's
the only outcome that doesn't require a human decision (unlike
local-merge, which needs base-branch confirmation and hook authorization;
or discard, which is destructive and requires explicit authorization if
ever taken).

Report the outcome, don't ask for it:
```
Implementation complete. Pushing <branch-name> and creating a Pull Request.
```

**Only deviate from push+PR when the caller's own instructions explicitly
authorize a different outcome for this run** (e.g. an orchestrating flow
that has already decided to merge locally, or to discard because the work
was rejected upstream). In that case, follow the authorized outcome
instead — this is not a human prompt, it's the calling context's own
prior decision, already made.

### Step 5: Execute Outcome

#### Push and Create PR (default outcome)

**Detached HEAD only:** there is no named branch to push. Create one first —
`git checkout -b <new-branch-name>` (derive a name from the work done, e.g.
`feature/<short-description>`) — before running the push below. Named-branch
worktrees and normal repos already have `<feature-branch>`; skip this.

```bash
# Push branch
git push -u origin <feature-branch>
```

**Do NOT clean up worktree** — the PR needs it alive to iterate on feedback.
This is the terminal step for the default outcome; do not continue to
Step 6.

#### Merge Locally (authorized-alternative outcome only)

Only run this when the calling context's own instructions explicitly
authorized a local merge instead of push+PR for this run.

```bash
# Get main repo root for CWD safety
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
cd "$MAIN_ROOT"

# Merge first — verify success before removing anything
git checkout <base-branch>
git pull
git merge <feature-branch>
# Note: if the repo has a workflow.config.yaml, the enforce_pr_workflow hook
# blocks `git merge` on main/master unless /pr-review-toolkit:review-pr ran this
# session — run it first, or use the default push+PR outcome instead.

# Verify tests on merged result
<test command>

# Only after merge succeeds: cleanup worktree (Step 6), then delete branch
```

Then: Cleanup worktree (Step 6), then delete branch:

```bash
git branch -d <feature-branch>
```

#### Discard (authorized-alternative outcome only)

Only run this when the calling context's own instructions explicitly
authorized discarding this work for this run (e.g. the work was rejected
upstream). This is destructive — report exactly what will be deleted
before proceeding:

```
Discarding this work — permanently deleting:
- Branch <name>
- All commits: <commit-list>
- Worktree at <path>
```

```bash
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
cd "$MAIN_ROOT"
```

Then: Cleanup worktree (Step 6), then force-delete branch:
```bash
git branch -D <feature-branch>
```

### Step 6: Cleanup Workspace

**Only runs for the Merge Locally and Discard outcomes.** The default
push+PR outcome always preserves the worktree.

```bash
GIT_DIR=$(cd "$(git rev-parse --git-dir)" 2>/dev/null && pwd -P)
GIT_COMMON=$(cd "$(git rev-parse --git-common-dir)" 2>/dev/null && pwd -P)
WORKTREE_PATH=$(git rev-parse --show-toplevel)
```

**If `GIT_DIR == GIT_COMMON`:** Normal repo, no worktree to clean up. Done.

**If worktree path is under `.worktrees/` or `worktrees/`:** Coderails created this worktree — we own cleanup.

**Check lock state before removing** — a worktree can be locked (e.g. by the
harness, to protect a live session using it):

```bash
MAIN_ROOT=$(git -C "$(git rev-parse --git-common-dir)/.." rev-parse --show-toplevel)
cd "$MAIN_ROOT"
LOCK_REASON=$(git worktree list --porcelain | awk -v p="$WORKTREE_PATH" '
  $0 == "worktree " p { f=1; next }
  f && /^locked / { sub(/^locked /, ""); print; exit }
  f && /^worktree / { exit }
')
```

**Not locked (`LOCK_REASON` empty):** Remove normally.

```bash
git worktree remove "$WORKTREE_PATH"
git worktree prune  # Self-healing: clean up any stale registrations
```

**Locked:** Parse a pid out of the reason string (harness-written lock
reasons look like `claude session <name> (pid NNNNN start <date>)`) and
check whether that process is alive:

```bash
LOCK_PID=$(echo "$LOCK_REASON" | grep -oE '\(pid [0-9]+ ' | grep -oE '[0-9]+')
if [ -z "$LOCK_PID" ]; then
  echo "Worktree $WORKTREE_PATH is locked with no parseable pid (reason: $LOCK_REASON) — leaving in place, not removing."
elif ! kill -0 "$LOCK_PID" 2>/dev/null; then
  echo "Worktree $WORKTREE_PATH is locked by stale pid $LOCK_PID (dead) — clearing lock and removing."
  git worktree unlock "$WORKTREE_PATH"
  git worktree remove "$WORKTREE_PATH"
  git worktree prune
else
  echo "Worktree $WORKTREE_PATH is locked by live pid $LOCK_PID (reason: $LOCK_REASON) — determine below whether this is THIS session's own lock or another session's before acting."
fi
```

**A live pid alone doesn't say whose it is — there is no reliable shell
test for it here.** `$$` is this snippet's own subshell pid, not the
Claude session's pid, so it can't be compared against `LOCK_PID`. And
Step 5's Merge Locally and Discard snippets `cd` to `MAIN_ROOT` before
handing off to Step 6, in a separate command invocation each time — cwd
isn't guaranteed to persist between them, so `$WORKTREE_PATH` computed
above may no longer be this shell's actual cwd either; comparing cwd to
it is not a dependable test. Don't invent a shell one-liner for this.
The real signal is procedural, not computed: **was this session already
working in `$WORKTREE_PATH` before Step 6 started** — i.e. is this the
worktree this whole invocation of the skill has been running in? If you
know that (you do — you know what worktree you've been operating in
this session), use it directly:

- **This worktree is NOT the one this session has been working in** —
  some other session holds it. Report and defer, never force. A merged
  PR does not by itself mean the worktree is safe to remove; forcing it
  out would yank that other session mid-work. This holds regardless of
  which pid the lock names.
- **This worktree IS the one this session has been working in** — NOT a
  defer case, regardless of which pid the lock names. `git worktree
  remove` cannot remove the worktree it is run from, and forcing it
  (e.g. `-f`, or removing the `.git` file by hand) would break the
  running session. Use the native `ExitWorktree` tool instead, with
  `action: "remove"` — but only if it owns this worktree: with no
  `EnterWorktree` session active at all it's a no-op (nothing removed),
  and for a worktree entered via `EnterWorktree`'s `path` parameter
  (switching into an existing worktree, as opposed to creating one)
  `ExitWorktree` will not remove it — only `action: "keep"` is
  supported for that case. In either situation, fall back to `cd` to
  the main repo root, then `git worktree remove` from there.

  When `ExitWorktree` does own the worktree: it exits the session from
  the worktree and removes it in one step, but refuses when the worktree
  has uncommitted files or commits not on the original branch, reporting
  them as work that would be discarded — check this before overriding
  with `discard_changes: true`. If the branch was squash-merged, `git log
  --oneline origin/main..HEAD` being empty is NOT the right confirmation
  — squash rewrites the SHAs that land on `origin/main`, so the branch's
  own original commit SHAs never appear in its ancestry, and this check
  can never pass, no matter how genuinely merged the branch is. Confirm
  content identity instead: `git diff origin/main HEAD` shows no
  differences, **and** the PR reports `state: MERGED` (`gh pr view <n>
  --json state`). Only override the refusal once both hold. Never pass
  `discard_changes: true` on a refusal you haven't verified this way.

**Never force-remove a lock you can't attribute to a dead pid or to this
session's own worktree.** No parseable pid and a live pid on another
session both mean: report and leave the worktree alone. A confirmed-dead
pid clears the lock via the git path above; a live pid on this session's
own worktree clears it via `ExitWorktree`.

**Otherwise:** The host environment (harness) owns this workspace. Do NOT remove it. If your platform provides a workspace-exit tool, use it. Otherwise, leave the workspace in place.

## Quick Reference

| Outcome | Merge | Push | Keep Worktree | Cleanup Branch |
|--------|-------|------|---------------|----------------|
| Push + PR (default) | - | yes | yes | - |
| Merge locally (authorized-alternative) | yes | - | - | yes |
| Discard (authorized-alternative) | - | - | - | yes (force) |

## Common Mistakes

**Skipping test verification**
- **Problem:** Ship broken code, create failing PR
- **Fix:** Always verify tests before auto-selecting the outcome

**Asking instead of deciding**
- **Problem:** Introducing a human checkpoint defeats the point of this skill
- **Fix:** Default to push+PR; only deviate when the calling context's own instructions explicitly authorized a different outcome for this run

**Cleaning up worktree for the default outcome**
- **Problem:** Remove worktree the PR needs for iteration
- **Fix:** Only cleanup for the Merge Locally and Discard outcomes

**Deleting branch before removing worktree**
- **Problem:** `git branch -d` fails because worktree still references the branch
- **Fix:** Merge first, remove worktree, then delete branch

**Running git worktree remove from inside the worktree**
- **Problem:** Command fails silently when CWD is inside the worktree being removed
- **Fix:** Always `cd` to main repo root before `git worktree remove`

**Cleaning up harness-owned worktrees**
- **Problem:** Removing a worktree the harness created causes phantom state
- **Fix:** Only clean up worktrees under `.worktrees/` or `worktrees/`

**Force-removing a locked worktree without checking the pid**
- **Problem:** A locked worktree can be a live session in progress (harness lock reasons embed a pid); force-removing it yanks a running session
- **Fix:** Parse the pid from the lock reason and `kill -0` it — only remove if confirmed dead; report and leave alone otherwise

**Deferring on a live-pid lock that is this session's own**
- **Problem:** The lock reason always shows a live pid when the worktree is the one this session has been working in (the harness locks it on the session's behalf) — treating every live pid as "another session, defer" means this session can never finish its own worktree
- **Fix:** There's no reliable pid or cwd comparison to run (see Step 6) — know which worktree this session has been operating in, and if it's the locked one, use `ExitWorktree` with `action: "remove"`, not `git worktree remove`, and not a defer

**Passing `discard_changes: true` to `ExitWorktree` on an unverified refusal**
- **Problem:** `ExitWorktree` refuses when the worktree has uncommitted files or commits not on the original branch — after a squash merge those commits are real (legitimately landed on `origin/main`) but an ancestry check (`git log --oneline origin/main..HEAD`) can never see them there, since the squash rewrote the SHAs; checking ancestry means the agent can never pass the override, no matter how genuinely merged the branch is
- **Fix:** Before overriding the refusal, confirm content identity — `git diff origin/main HEAD` shows no differences — AND the PR reports `state: MERGED`

**Using `ExitWorktree` on a worktree it doesn't own**
- **Problem:** With no `EnterWorktree` session active, `ExitWorktree` is a no-op; for a worktree entered via `EnterWorktree`'s `path` parameter, it will not remove — only `action: "keep"` is supported. Either way `action: "remove"` doesn't remove anything, leaving the agent with a locked worktree and no next step
- **Fix:** When `ExitWorktree` can't remove the worktree, `cd` to the main repo root and use `git worktree remove` instead

**Discarding without reporting what's deleted**
- **Problem:** Destructive action with no record of what was lost
- **Fix:** Always report the branch, commits, and worktree path being deleted before proceeding

## Red Flags

**Never:**
- Proceed with failing tests
- Merge without verifying tests on result
- Discard work without reporting what's being deleted
- Force-push without explicit request
- Remove a worktree before confirming merge success
- Clean up worktrees you didn't create (provenance check)
- Run `git worktree remove` from inside the worktree
- Force-remove a locked worktree without confirming the lock's pid is dead or the worktree is this session's own
- Defer on a live-pid lock without checking whether the worktree is the one this session has been working in
- Pass `discard_changes: true` to `ExitWorktree` without verifying a squash-merge landed
- Introduce a human prompt/menu — this skill runs to completion autonomously

**Always:**
- Verify tests before auto-selecting the outcome
- Detect environment before selecting the outcome
- Default to push+PR unless the calling context authorized otherwise
- Report a discard's deletions before executing it
- Clean up worktree for Merge Locally & Discard outcomes only
- `cd` to main repo root before worktree removal
- Check lock state before removing; report live/unattributable locks instead of forcing
- Run `git worktree prune` after removal
