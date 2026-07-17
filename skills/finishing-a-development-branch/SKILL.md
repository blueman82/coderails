---
name: finishing-a-development-branch
description: Use when implementation is complete and all tests pass - autonomously ships the work (push + create PR by default) and cleans up the workspace, with no human checkpoint
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
elif kill -0 "$LOCK_PID" 2>/dev/null; then
  echo "Worktree $WORKTREE_PATH is locked by live pid $LOCK_PID (reason: $LOCK_REASON) — deferred until that session ends, not removing."
else
  echo "Worktree $WORKTREE_PATH is locked by stale pid $LOCK_PID (dead) — clearing lock and removing."
  git worktree unlock "$WORKTREE_PATH"
  git worktree remove "$WORKTREE_PATH"
  git worktree prune
fi
```

**Never force-remove a lock you can't attribute to a dead pid.** No
parseable pid and a live pid both mean: report and leave the worktree
alone. Only a confirmed-dead pid clears the lock.

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
- Introduce a human prompt/menu — this skill runs to completion autonomously

**Always:**
- Verify tests before auto-selecting the outcome
- Detect environment before selecting the outcome
- Default to push+PR unless the calling context authorized otherwise
- Report a discard's deletions before executing it
- Clean up worktree for Merge Locally & Discard outcomes only
- `cd` to main repo root before worktree removal
- Run `git worktree prune` after removal
