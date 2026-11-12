---
name: loop-retro-promotion
description: On-demand promotion routine that mines accumulated agentic-loop retros for repo-agnostic lessons and promotes them into learned-failure-modes.md. Invoke only on an explicit promotion request, never for a single loop's retro or from inside an active agentic-loop session.
---

# Loop Retro Promotion

Invoke this skill on demand. It stays dormant until it has sufficient loop history.
Then it promotes durable lessons that apply across repositories from `standing-orders.md` and `retro.json` into `skills/agentic-loop/learned-failure-modes.md`.
A user-owned scheduler can invoke it in the future. The native Codex plugin includes and configures no scheduler.

**Run controller.** `routine_run.py` handles the log, step sequence, manifest check, gate refusals, and cleanup. This skill shares it with `docs-sync`.
The spec is `routines/loop-retro-promotion.json`. The policy is `policy/retro-promotion.policy.json`. The script needs no hooks.

Set `SKILL_DIR` to the absolute directory containing this `SKILL.md`. Use `RR` for:
`python3 "$SKILL_DIR/../../scripts/routine_run.py" --log <repo-key-dir>/promotion-runs.log loop-retro-promotion`.
The command needs `--log` because it resolves the loop history directory at run time (see below).

`routine_run.py` appends a JSONL row and derives the legacy marker.
The accepted results are `stage_ok`, `run_ok`, `run_abort`, `run_refused`, and `run_incomplete`. The spec lists the accepted codes.
The legacy markers are `run=ok`, `abort=<code>`, `refused=<gate>`, and `abort=incomplete-run`.
Do not write terminal markers by hand. An unlisted result or code gives exit 2.

`RR begin` refuses an open run across midnight too. Explicit `RR begin --new` first aborts the previous open ID.
If `log_unwritable` prevents an update, examine the two logs and the run file for unfinished writes.
See `docs/routines.md` for same-user forgery and runner limits.

## 1. Predicate evaluation (always runs, even when dormant)

Start the run log. Check the graduation predicate before you mine, branch, or edit:

1. Resolve the loop history directory from `CODERAILS_AGENTIC_LOOP_DIR`. The default is `$HOME/.coderails/agentic-loop`.
   The caller must scope this directory to the current repository. Do not invoke a root plugin hook or graph helper.

2. Run `RR begin`. It writes the provisional `run_incomplete` row before it reads the predicate.
   An interrupted or refused read does not count as a completed dormant run.
3. Run `python3 "$SKILL_DIR/../../scripts/lib/lessons.py" --dir <repo-key-dir> --session <native caller session id> predicate`.
   Find the script relative to this `SKILL.md`. Read `graduation` from its JSON.
   Do not count files or read Markdown by hand.
   It checks for **10 or more different completed retros** with owned and validated `progress.json` files and matching source hashes.

4. `recurred` **>= 1**. A record in `orders.json` has typed `last_recurred` different from `created`.
   This is one full lifecycle with one or more recurrences after creation.
5. `decayed` **>= 1**. A record has `status: decayed`, for one clean decay.
   The result is `met` only if all three conditions hold.

On exit 2, run `RR abort predicate_refused`. On exit 3, run `RR abort predicate_degraded`.
For malformed output or a different error, run `RR abort predicate_unavailable`.
Do not use `finish no_drift` for these results. Do not use a generated view or ledger claim as fallback.

Schema 3 history needs the matching `retro_check` validator. If the validator is unavailable, the tool refuses explicitly.
Give the caller's actual native session ID so the tool can identify the source of a degraded read.
Do not infer which environment values are available.

If the predicate check succeeds, append one line to `<repo-key-dir>/promotion-runs.log`:

```
<ISO8601> predicate=<met|unmet> retros=<n> lifecycle=<0|1> decay=<0|1>
```

If the predicate is unmet, the run is dormant. The log line is the artifact.
Do not make a branch or PR, or run the gate sequence.
Run `RR finish no_drift`. It writes `run_ok`, so the last-marker rule reports success. Stop here.

If the predicate is met, continue to §2. The `run_incomplete` row from `begin` applies to mining, drafting, and publication.
If the run ends before one of these steps finishes, `abort=incomplete-run` stays as the last terminal marker.

## 2. Mining

If the predicate is met, read all `retro.json` files at `<repo-key-dir>/*/retro.json`.
Also read the typed `candidates` list from `lessons.py ... predicate` in §1. The generated `standing-orders.md` is only a view.

Keep each candidate's `memory` metadata with revision, body, source records, and expiry.
A conditional or condition-expiring Note gives `learning_conditional_use_unsupported`. Do not promote it.
Do not turn an unresolved free-text condition into unconditional guidance.

Candidates have current, live, verified owner-cited lesson text from Muninn.
Retros without full owned sources do not increase the graduation count. Free-text notes cannot replace typed recurrence fields.
Select problems only if all these conditions hold:

- They recurred **>= 2** times.
- They recurred across **>= 2** different `session_id`s.
- The lesson applies across repositories that use the agentic-loop skill.

Do not promote lessons for one repository, regardless of recurrence. They stay in the typed records with `scope: repo`.
`lessons.py predicate` checks recurrence, different sessions, and `scope: agnostic`.
Check here that the lesson actually applies across repositories.

## 3. Drafting

For each selected lesson, append one entry to `learned-failure-modes.md` in `## Promoted lessons`. Give these fields:

- **`Failure mode`** — what went incorrect.
- **Lesson** — write it as an imperative.
- **`Evidence`** — the contributing session IDs and recurrence count.
- **Promotion date** — ISO8601.

## 4. Delivery — full gate chain, manifest-locked

Use the sequence below. `RR stage NAME` and `RR run-gate STAGE -- ARGV` check it.
A step out of sequence aborts the run with `stage_out_of_order`.

1. `fetch_branch`: Fetch `origin/main`. Make the branch from that fetched head.
   Run `RR stage fetch_branch` to record the branch for cleanup.
2. `evals_frozen`: Invoke `$coderails-codex:task-evals` with scope `pr` and freeze it before you edit.
   Then run `RR stage evals_frozen`.
3. `edit_made`: Append the entry from Step 3. Use `git add skills/agentic-loop/learned-failure-modes.md` and commit it.
   Then run `RR stage edit_made`.

   The manifest check compares two commits. It cannot see an uncommitted working-tree edit.
   Without the commit, the range is empty and the one-path check aborts the run.
   Add only the named path to the Git index. Do not use `git add -A`, which can add unrelated changes.

4. `manifest_check`: Run `RR stage manifest_check`.
   It runs `diff_manifest.py --policy policy/retro-promotion.policy.json` against `origin/main...HEAD`.
   The policy permits only one path with status `M`: `skills/agentic-loop/learned-failure-modes.md`.

   A second path gives `too_many_paths`. If a file is renamed, copied, removed, or added, the check gives `status_not_allowed` or `out_of_manifest`.
   A violation ends the run with `run_abort`, the applicable code, and cleanup. **Abort without continuing.**

   The three-dot diff avoids a moving two-dot base when a sibling PR merges during the run.
   Rename detection shows the source in `git mv scripts/gate.sh skills/agentic-loop/learned-failure-modes.md`.

   **This check looks only at paths.** An `M` for `learned-failure-modes.md` can satisfy it with content other than a mined lesson.
   The mining rules in section 2 and the inspection and eval gates in steps 6–8 check the content.
   A path-based manifest cannot check it.

5. `push`: `RR run-gate push -- python3 "$SKILL_DIR/../../scripts/push.py"`.
6. `review`: Start the installed `spec-reviewer` custom agent. It examines the current PR head against the mined records and one-file manifest.
   Wait for it and close it. Then run `RR stage review`.
7. `post_review`: `RR run-gate post_review -- python3 "$SKILL_DIR/../../scripts/post_review.py" post <PR#> --summary <file>`.
8. `post_evals`: `RR run-gate post_evals -- python3 "$SKILL_DIR/../../scripts/post_evals.py" post <PR#> <evals.json>`.
9. `merge`: `RR run-gate merge -- python3 "$SKILL_DIR/../../scripts/merge.py" <PR#>`.
   Then run `RR finish ok`. Only this command writes `run_ok` for a publication run, after the `merge` row.

`run-gate` exits non-zero if a gate does not succeed and the PR stays open.
It writes `run_refused` for that gate and runs cleanup. It does not write `run_ok`.
For merge, it checks the named PR and head after the command.
A confirmed merge can continue despite a CLI error. An unknown result stays red and blocks cleanup.

Do not close a merged PR or log it as an abort.
Do not wait, poll, or try again for a gate. Do not invent a marker.
`RR abort CODE` and `RR refuse GATE` accept only codes listed in the spec.

The code runs cleanup one time with only `git` and `gh`.
It closes an open PR. It removes the current local branch only if it is the branch recorded at `fetch_branch`.
It keeps the remote branch.

## 5. Prohibitions

This pipeline writes only the named repository file.
Do not edit SKILL.md, hook scripts, gate logic, this skill definition, external scheduler configuration, or the graduation predicate.
Do not relax, change the sequence of, or skip gates.
Merge only through `$coderails-codex:merge` so the package-local script checks the artifacts. Do not use raw `gh pr merge`.
