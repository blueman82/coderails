---
name: loop-retro-promotion
description: Scheduled promotion pipeline that mines accumulated agentic-loop retros for repo-agnostic lessons and promotes them into learned-failure-modes.md. Runs on a schedule, NOT for interactive use — do not invoke this for a single loop's retro or from inside an active agentic-loop session.
---

# Loop Retro Promotion

Machine-run pipeline. It is dormant until enough loop history exists, then
promotes durable, repo-agnostic lessons out of `standing-orders.md` /
`retro.json` and into `skills/agentic-loop/learned-failure-modes.md`.

## 1. Predicate evaluation (always runs, even when dormant)

Every scheduled run evaluates the graduation predicate first, before doing
anything else:

1. Resolve the repo-key dir: `dirname` of `dirname` of the path printed by
   `hooks/scripts/lib/agentic_loop_path.sh`.
2. Count `<repo-key-dir>/*/retro.json` — must be **>= 10**.
3. Confirm `standing-orders.md` has **>= 1** entry whose `last_recurred` !=
   `created` — one full lifecycle (created, then recurred at least once).
4. Confirm `standing-orders-decayed.md` has **>= 1** entry — one clean decay.

Append one line to `<repo-key-dir>/promotion-runs.log`:

```
<ISO8601> predicate=<met|unmet> retros=<n> lifecycle=<0|1> decay=<0|1>
```

If the predicate is unmet, STOP here. This is a dormant run — the log line
IS the run's artifact. No branch, no PR, no gate chain.

## 2. Mining

If the predicate is met, read all `retro.json` files under
`<repo-key-dir>/*/retro.json` plus `standing-orders.md` (the overlay).
Select ONLY failure modes that:

- recurred **>= 2** times, and
- across **>= 2** distinct `session_id`s, and
- whose lesson is **repo-agnostic** — it would apply to any repo running the
  agentic-loop skill, not just this one.

Reject repo-specific lessons even if they meet the recurrence bar — they
stay in the overlay (`standing-orders.md`), they do not get promoted.

## 3. Drafting

For each selected lesson, append one entry to `learned-failure-modes.md`
under `## Promoted lessons`, containing:

- **Failure mode** — what went wrong.
- **Lesson** — stated as an imperative.
- **Evidence** — the contributing session ids and the recurrence count.
- **Promotion date** — ISO8601.

## 4. Delivery — full gate chain, manifest-locked

1. Fetch `origin/main`; branch off the freshly-fetched tip.
2. Run `/coderails:task-evals` (scope: `pr`) and freeze it — BEFORE making
   the edit.
3. Make the edit (the append from step 3, above).
4. Assert `git diff origin/main --name-only` equals EXACTLY:
   `skills/agentic-loop/learned-failure-modes.md`
   If any other file appears in that diff: **ABORT WITH CLEANUP** — close
   the PR if one was opened, delete the branch both locally and on the
   remote, and append an `abort=<reason>` line to `promotion-runs.log`. Do
   not leave orphaned branches, PRs, or partial state.
5. `/coderails:push`
6. `/pr-review-toolkit:review-pr <PR#>`
7. `/coderails:post-review <PR#>`
8. `/coderails:post-evals <PR#>`
9. `/coderails:merge`

Append a timestamped per-stage line to `promotion-runs.log` after each gate
step above (fetch/branch, evals frozen, edit made, manifest check, push,
review, post-review, post-evals, merge).

## 5. Prohibitions

This pipeline writes exactly one repo file. It never edits SKILL.md, hook scripts, gate logic, its own skill definition, the routine config, or the graduation predicate. It never relaxes, reorders, or skips a gate. It merges ONLY via /coderails:merge — never raw gh pr merge: PreToolUse hooks do not fire in this headless execution mode, so merge.sh's script-internal artifact gates are the merge rail.
