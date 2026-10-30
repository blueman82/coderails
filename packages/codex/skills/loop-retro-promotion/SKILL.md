---
name: loop-retro-promotion
description: On-demand promotion routine that mines accumulated agentic-loop retros for repo-agnostic lessons and promotes them into learned-failure-modes.md. Invoke only on an explicit promotion request, never for a single loop's retro or from inside an active agentic-loop session.
---

# Loop Retro Promotion

On-demand pipeline. It is dormant until enough loop history exists, then
promotes durable, repo-agnostic lessons out of `standing-orders.md` /
`retro.json` and into `skills/agentic-loop/learned-failure-modes.md`.
A user-owned external scheduler may invoke this routine in the future, but the
native Codex plugin includes and configures no scheduler.

**State machine.** The run log, stage order, manifest check, gate refusals and
cleanup are one script, `routine_run.py`, shared with `docs-sync` (spec:
`routines/loop-retro-promotion.json`; policy:
`policy/retro-promotion.policy.json`). It needs no hooks. Set `SKILL_DIR` to the
absolute directory containing this `SKILL.md` and write `RR` for
`python3 "$SKILL_DIR/../../scripts/routine_run.py" --log <repo-key-dir>/promotion-runs.log loop-retro-promotion`
(`--log` is required because the loop-history directory is resolved at run
time, below). `routine_run.py` appends a JSONL event row (closed outcomes
`stage_ok`, `run_ok`, `run_abort`, `run_refused`, `run_incomplete`; closed
reason codes in the spec) and derives the legacy marker line (`run=ok`,
`abort=<code>`, `refused=<gate>`, `abort=incomplete-run`). Do not write terminal
markers by hand; an outcome or code outside the closed lists exits 2.
`RR begin` refuses an open run even across midnight. Explicit `RR begin --new`
first aborts the previous open id. `log_unwritable` refuses state advancement;
inspect both logs and state for partial writes. Same-user forgery and runner
limits are in `docs/routines.md`.

## 1. Predicate evaluation (always runs, even when dormant)

Start the run log, then evaluate the graduation predicate before mining,
branching or editing:

1. Resolve the configured loop-history directory from
   `CODERAILS_AGENTIC_LOOP_DIR`; default to
   `$HOME/.coderails/agentic-loop`. The caller must scope this directory to
   the current repo. Do not call a root plugin hook or graph helper.
2. Run `RR begin`. It writes the provisional `run_incomplete` row before the
   predicate read, so an interrupted or refused read cannot look like a
   successful dormant run.
3. Run `python3 "$SKILL_DIR/../../scripts/lib/lessons.py" --dir <repo-key-dir> --session <native caller session id> predicate`
   (resolve the path from this `SKILL.md`) and read `graduation` from its JSON;
   do not count files or read Markdown by hand. It checks **>= 10 distinct completed retros**
   with owned validated progress and matching source hashes,
4. `recurred` **>= 1** — an order in `orders.json` whose typed `last_recurred` !=
   `created` (one full lifecycle: created, then recurred at least once), and
5. `decayed` **>= 1** — an order with `status: decayed` (one clean decay).
   `met` is true only when all three hold.

On exit 2, run `RR abort predicate_refused`. On exit 3, run
`RR abort predicate_degraded`. For malformed output or any other unexpected
result, run `RR abort predicate_unavailable`. Never turn these cases into
`finish no_drift`; do not use a generated view or ledger claim as fallback.
Schema3 history requires the matching `retro_check` validator; unavailable validation is an explicit refusal.
Pass the actual caller's native session id so degraded reads remain attributable; do not infer environment presence.

After a successful evaluation, append one line to `<repo-key-dir>/promotion-runs.log`:

```
<ISO8601> predicate=<met|unmet> retros=<n> lifecycle=<0|1> decay=<0|1>
```

If the predicate is unmet, this is a dormant run — the log line IS the run's
artifact. No branch, no PR, no gate chain. A dormant stop is a correct,
successful no-op, not a failure: run `RR finish no_drift` (emits `run_ok`, so a
last-marker reading of the log is green). STOP here.

If the predicate is met, continue to §2. The standing `run_incomplete` row from
`begin` is the fail-safe in-progress marker for the entire met-path — mining,
drafting AND delivery: any death anywhere after met-determination leaves
`abort=incomplete-run` as the last terminal marker, so the log records failure
regardless of which step it died in.

## 2. Mining

If the predicate is met, read all `retro.json` files under
`<repo-key-dir>/*/retro.json` plus the `candidates` list from the
`lessons.py ... predicate` output of §1 (the typed standing orders; the
generated `standing-orders.md` is only a view of them).
Candidates carry current, live, verified owner-cited lesson text from Muninn. Retros lacking complete owned sources
cannot inflate the graduation count; free-text notes cannot substitute for typed recurrence fields.
Select ONLY failure modes that:

- recurred **>= 2** times, and
- across **>= 2** distinct `session_id`s, and
- whose lesson is **repo-agnostic** — it would apply to any repo running the
  agentic-loop skill, not just this one.

Reject repo-specific lessons even if they meet the recurrence bar — they
stay in the typed standing orders (`scope: repo`), they do not get promoted.
`lessons.py predicate` already applies the recurrence, distinct-session and
`scope: agnostic` bars; the repo-agnostic judgement is confirmed here.

## 3. Drafting

For each selected lesson, append one entry to `learned-failure-modes.md`
under `## Promoted lessons`, containing:

- **Failure mode** — what went wrong.
- **Lesson** — stated as an imperative.
- **Evidence** — the contributing session ids and the recurrence count.
- **Promotion date** — ISO8601.

## 4. Delivery — full gate chain, manifest-locked

Run the stages in this order; `RR stage NAME` and `RR run-gate STAGE -- ARGV`
enforce it (a call out of order aborts the run: `stage_out_of_order`).

1. `fetch_branch`: fetch `origin/main`, branch off the freshly-fetched tip,
   then `RR stage fetch_branch` (records the branch for cleanup).
2. `evals_frozen`: invoke `$coderails-codex:task-evals` with scope `pr` and
   freeze it — BEFORE making the edit — then `RR stage evals_frozen`.
3. `edit_made`: make the edit (the append from step 3, above), then **commit
   it** — `git add skills/agentic-loop/learned-failure-modes.md` and commit —
   then `RR stage edit_made`. The manifest check is a **commit-range** diff: it
   compares two commits, so it cannot see an uncommitted working-tree edit.
   Skip the commit and the range is empty, the one-path check fails, and the
   run aborts every time. Stage the ONE target path by name, never
   `git add -A`: a stray would otherwise be swept into the same commit.
4. `manifest_check`: `RR stage manifest_check`. It runs
   `diff_manifest.py --policy policy/retro-promotion.policy.json` over
   `origin/main...HEAD` (three-dot, with rename detection). The policy allows
   exactly one path, modified (`M`):
   `skills/agentic-loop/learned-failure-modes.md`. A second path
   (`too_many_paths`), a rename or copy from any source, a deletion, or an
   addition of any other file (`status_not_allowed`, `out_of_manifest`) is an
   **ABORT WITH CLEANUP**: `run_abort` with that reason code. **ABORT, never
   warn-and-continue.** Three-dot because the base of a two-dot diff moves when
   a sibling PR merges mid-run; rename detection because
   `git mv scripts/gate.sh skills/agentic-loop/learned-failure-modes.md` would
   otherwise look like the permitted file.

   **What this check does NOT catch, stated plainly:** it is a PATH check, not
   a CONTENT check. A commit that legitimately modifies only
   `learned-failure-modes.md`, but fills it with something other than a mined
   lesson, is a lone `M` of the permitted path and PASSES here. That residual
   is held by the mining rules in section 2 and by the review/eval gates in
   steps 6-8 — not by this step. No path-based manifest can close it.
5. `push`: `RR run-gate push -- python3 "$SKILL_DIR/../../scripts/push.py"`.
6. `review`: spawn the installed `spec-reviewer` custom agent to review the
   current PR head against the mined evidence and one-file manifest (wait for
   it and close it), then `RR stage review`.
7. `post_review`: `RR run-gate post_review -- python3 "$SKILL_DIR/../../scripts/post_review.py" post <PR#> --summary <file>`.
8. `post_evals`: `RR run-gate post_evals -- python3 "$SKILL_DIR/../../scripts/post_evals.py" post <PR#> <evals.json>`.
9. `merge`: `RR run-gate merge -- python3 "$SKILL_DIR/../../scripts/merge.py" <PR#>`,
   then `RR finish ok` — the ONLY point that emits `run_ok` for a delivery run,
   after the `merge` stage row.

`run-gate` exits non-zero when a gate fails and the PR is still open: it
records `run_refused` for that gate, cleans up and never emits `run_ok`.
For merge, the runner checks the exact PR and head after the command. A
confirmed merge can advance despite a CLI error; an unknown result stays red
and blocks cleanup. A merged PR is never closed or logged as an abort. Never
wait, poll or retry for a gate, and never invent a marker (`RR abort CODE` /
`RR refuse GATE` accept only the spec's closed reason codes). Cleanup runs once,
in code, with `git` and `gh` only: close the PR and delete the current local
branch only while still on the branch recorded at `fetch_branch`. The remote
branch is left intact.

## 5. Prohibitions

This pipeline writes exactly one repo file.
It never edits SKILL.md, hook scripts, gate logic, its own skill definition, external scheduler configuration, or the graduation predicate.
It never relaxes, reorders, or skips a gate.
It merges only via `$coderails-codex:merge`, never raw `gh pr merge`, so the package merge script's artifact checks remain in force.
