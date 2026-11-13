---
name: loop-retro-promotion
description: Scheduled promotion pipeline that mines accumulated agentic-loop retros for repo-agnostic lessons and promotes them into learned-failure-modes.md. Runs on a schedule, NOT for interactive use — do not invoke this for a single loop's retro or from inside an active agentic-loop session.
effort: high
---

# Loop Retro Promotion

This pipeline waits for sufficient loop history.
Then it promotes durable lessons that apply across repos from `standing-orders.md` and `retro.json`.
It writes them to `skills/agentic-loop/learned-failure-modes.md`.

**Run controls.**
The `routine_run.py` script controls the run log, step sequence, manifest check, gate refusals, and cleanup.
The `docs-sync` skill uses the same script.
The spec is `routines/loop-retro-promotion.json` and the policy is `policy/retro-promotion.policy.json`.
The script works headless without hooks.

Here, `RR` means `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/routine_run.py" --log <repo-key-dir>/promotion-runs.log loop-retro-promotion`.
Supply `--log` because you get the repo-key directory at run time.

The script appends a JSONL row for `stage_ok`, `run_ok`, `run_abort`, `run_refused`, or `run_incomplete`.
Use only the codes in the spec.
The script derives the legacy marker for the artifact gate: `run=ok`, `abort=<code>`, `refused=<gate>`, or `abort=incomplete-run`.
Do not write a terminal marker by hand.
The script exits 2 for an outcome or code that is not in the lists.

The `RR begin` command refuses an open run across date changes too.
An explicit `RR begin --new` first aborts the previous open ID.
With `log_unwritable`, the run cannot move to the next step.
Check the log and run data for writes that did not finish.
See `docs/routines.md` for the limits of the runner and same-user forgery.

## 1. Predicate evaluation (always runs, even when dormant)

Start the run log and check the graduation predicate before mining, making a branch, or editing.

1. Find the repo-key directory. Use `dirname` of `dirname` of the path that `hooks/scripts/lib/agentic_loop_path.py` prints.
2. Run `RR begin`. It writes the provisional `run_incomplete` row before the predicate read. An interrupted or refused read cannot count as a satisfactory dormant run.
3. Run `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/lib/lessons.py" --dir <repo-key-dir> --session <native caller session id> predicate`. Read `graduation` from its JSON. Do not count files or read Markdown by hand. The first condition is 10 or more different completed retros with validated owner-bound loop data and matching source hashes.
4. The second condition is `recurred` **>= 1**. Check for a record in `orders.json` where the typed `last_recurred` differs from `created`. The record has recurred one or more times since it was made.
5. The third condition is `decayed` **>= 1**. Check for a record with `status: decayed`. The `met` field is `true` only if all three conditions apply.

For exit 2, run `RR abort predicate_refused`.
For exit 3, run `RR abort predicate_degraded`.
For malformed output or an unexpected result, run `RR abort predicate_unavailable`.
Do not use `finish no_drift` for these results.
Do not use a view or ledger claim as a fallback.

Schema 3 history needs the matching `retro_check` validator.
Refuse the run if validation is unavailable.
Use the caller’s native session ID so the degraded read records identify the caller.
Check that the environment is available before you rely on it.

After the predicate check succeeds, append one line to `<repo-key-dir>/promotion-runs.log`:

```
<ISO8601> predicate=<met|unmet> retros=<n> lifecycle=<0|1> decay=<0|1>
```

If the predicate is unmet, the run is dormant.
The log line is its artifact.
Do not make a branch or PR, or run the gates.
Run `RR finish no_drift` so it records `run_ok` for the artifact gate.
Then stop.

If the predicate is met, continue to §2.
The `run_incomplete` row from `begin` applies during mining, drafting, and publication.
If execution ends before a terminal result, the last marker stays `abort=incomplete-run` and the gate rejects the run.
If the child exits without a terminal row, the runner also appends `run_abort` with `runner_exit_no_terminal`.

## 2. Mining

If the predicate is met, read `<repo-key-dir>/*/retro.json` and the `candidates` list from `lessons.py ... predicate` in §1.
The candidates are typed standing-order records.
The `standing-orders.md` file is a view of the records.

Keep each candidate’s `memory` metadata: revision, body, `supports`, and expiry.
A conditional or condition-expiring Note gives `learning_conditional_use_unsupported`.
Do not promote that Note.
Do not turn a free-text condition you cannot resolve into unconditional guidance.

Candidates include current Muninn lesson text with owner citations and validation.
Only retros with complete owned sources count for graduation.
Use the typed recurrence fields for recurrence counts.

Select only problems that recurred two or more times across two or more different `session_id` values.
Select only repo-agnostic lessons that apply across repos that use agentic-loop.
Keep lessons for one repo in the standing-order records as `scope: repo`.
Keep them in the repo scope if they also satisfy the recurrence threshold.
The `lessons.py predicate` command checks recurrence, different sessions, and `scope: agnostic`.
Check the repo-agnostic judgment here too.

## 3. Drafting

Append one entry for each selected lesson to `learned-failure-modes.md` in `## Promoted lessons`.
Use these field labels:

- **`Failure mode`** — the problem.
- **`Lesson`** — an instruction.
- **`Evidence`** — the contributing session IDs and recurrence count.
- **`Promotion date`** — ISO8601.

## 4. Delivery — full gate chain, manifest-locked

Run the steps in this sequence.
The `RR stage NAME` and `RR run-gate STAGE -- ARGV` commands abort with `stage_out_of_order` if the sequence is incorrect.

1. `fetch_branch`: Fetch `origin/main`. Make a branch from the commit you fetched. Run `RR stage fetch_branch` to record the branch for cleanup.
2. `evals_frozen`: Run `/coderails:task-evals` at scope `pr` and freeze the evals before editing. Run `RR stage evals_frozen`.
3. `edit_made`: Append the entry from §3. Run `git add skills/agentic-loop/learned-failure-modes.md` and commit it. Then run `RR stage edit_made`. The manifest compares two commits and cannot see uncommitted edits. Without the commit, the empty range makes the one-path check fail and abort the run. Add only the named path. Do not run `git add -A` because it can include unrelated files.
4. `manifest_check`: Run `RR stage manifest_check`. It runs `diff_manifest.py --policy policy/retro-promotion.policy.json` on `origin/main...HEAD` with rename detection. The policy permits only a modification (`M`) to `skills/agentic-loop/learned-failure-modes.md`. A second path gives `too_many_paths`. A rename, copy, deletion, or added file gives `status_not_allowed` or `out_of_manifest`. Abort and clean up with `run_abort` and the reported code.

   Use the three-dot diff because a sibling PR merge can move the base of a two-dot diff. Rename detection shows that `git mv scripts/gate.sh skills/agentic-loop/learned-failure-modes.md` is not a modification of the permitted file.

   The manifest checks paths and statuses only. The manifest can accept a modification to the permitted path that contains unrelated content. Use the mining rules in §2 and the reviewer and eval checks in steps 6–8 to check content.
5. `push`: Run `RR run-gate push -- python3 "${CLAUDE_PLUGIN_ROOT}/scripts/push.py"`.
6. `review`: Run `/pr-review-toolkit:review-pr <PR#>`, then `RR stage review`.
7. `post_review`: Run `RR run-gate post_review -- python3 "${CLAUDE_PLUGIN_ROOT}/scripts/post_review.py" post <PR#> --summary <file>`.
8. `post_evals`: Run `RR run-gate post_evals -- python3 "${CLAUDE_PLUGIN_ROOT}/scripts/post_evals.py" post <PR#> <evals.json>`.
9. `merge`: Run `RR run-gate merge -- python3 "${CLAUDE_PLUGIN_ROOT}/scripts/merge.py" <PR#>`. Then run `RR finish ok`. This is the only command that records `run_ok` for a publication run. It runs after the `merge` row. The last terminal marker for a complete publication is `run=ok`.

If a gate fails and the PR is open, `run-gate` exits nonzero.
It records `run_refused` for the gate and cleans up without recording `run_ok`.
After the merge command, the runner checks the same PR and head.
A merge the runner confirms can continue despite a CLI error.
An unknown result keeps the run unsuccessful and blocks cleanup.
Do not close a merged PR or log it as an abort.

Do not wait, poll, or retry for a gate.
Do not invent a marker.
The `RR abort CODE` and `RR refuse GATE` commands accept only the spec’s codes.
Cleanup runs one time in code with `git` and `gh` only.
It closes the PR and removes the local branch only if the current branch is the branch recorded in `fetch_branch`.
It keeps the remote branch.

## 5. Prohibitions

This pipeline writes only `skills/agentic-loop/learned-failure-modes.md` in the repo.
Do not edit SKILL.md, hook scripts, gate code, this skill, the schedule config, or the graduation predicate.
Do not relax, reorder, or skip a gate.

Use only `merge.py` (/coderails:merge) to merge.
Do not use raw `gh pr merge`.
PreToolUse hooks do not run in headless mode.
The script’s artifact gates apply during merge.
