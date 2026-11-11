---
name: docs-sync
description: Scheduled nightly pipeline that audits this repo's git-tracked documentation for drift against the actual codebase, and — only if drift is found — edits, pushes, reviews, and self-merges a fix with no human in the loop. Runs on a schedule, NOT for interactive use — for an interactive drift check, use /sync-docs directly instead.
effort: high
---

# Docs Sync

Each night, this pipeline checks the repo’s tracked documentation against the code.
If it finds no drift, it records that result and stops without a branch or PR.
If it finds drift, it corrects it through the full gate sequence and merges the correction.

This replaces the read-only `sync-docs-weekly` schedule.
That schedule did not work for 9 days and gave no error. Its `foreignSkillPath` pointed to a missing path.
The plugin includes `docs-sync` and `loop-retro-promotion`, so this skill uses no `foreignSkillPath`.

**Run controls.**
After the audit, the `routine_run.py` script controls the run.
The `loop-retro-promotion` skill uses the same script.
The spec `routines/docs-sync.json` gives the step sequence, policy file, log path, and cleanup.
The script works in `claude -p` without hooks.

Here, `RR` means `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/routine_run.py" docs-sync`.
Do not write the run log by hand.
The script appends a JSONL row for `stage_ok`, `run_ok`, `run_abort`, `run_refused`, or `run_incomplete`.
The spec gives the permitted codes.
The script derives the legacy marker that the dashboard’s `last-marker` predicate reads: `run=ok`, `abort=<code>`, `refused=<gate>`, or `abort=incomplete-run`.
It refuses an outcome or code that is not on the lists and exits 2.

The `RR begin` command refuses an open run across date changes too.
An explicit `RR begin --new` first aborts the previous open ID.
Do not replace a run to hide an error.
With `log_unwritable`, the run cannot move to the next step.
Check the log and run data for writes that did not finish.
See `docs/routines.md` for the limits of the runner and same-user forgery.

## 1. Audit

Use Phases 1–3 of `/coderails:sync-docs` to find differences between tracked docs and code.
Identify the project structure, run the traditional audit, and give the drift report.

**Correct only tracked `.md` files that the policy permits.**
Check `README.md`, `AGENTS.md`, `CLAUDE.md`, and tracked docs in `docs/`.
The deny-list in `policy/docs-sync.policy.json` overrides this scope.
It includes `skills/**/SKILL.md`, `AGENTS.md`, `CLAUDE.md`, `docs/routines.md`, paths in `.claude/`, and `examples/dashboard-config.json`.
Report drift in those files and do not correct it.

Before you correct a `docs/*.md` file, check that Git tracks it and does not ignore it.

```bash
git ls-files --error-unmatch <path>          # Git knows this path.
git check-ignore -q <path> && echo IGNORED   # gitignored — EXCLUDE
```

Do not change an ignored document or a document you did not read.
Read the code before you update a document to agree with it.
If you cannot show drift, report the uncertainty and do not edit the file.

## 2. NO-DRIFT SHORT-CIRCUIT

After the audit, do this step before you make a branch or PR.

Run `RR begin` to write the run data and a provisional `run_incomplete` row.
If the audit finds nothing to correct, run `RR finish no_drift`.
This records `run_ok` and the `run=ok` marker that the schedule’s `expectedArtifact` checks.
Exit 0.

Do not make a branch or open a PR for a no-drift run.
Go to step 3 only if you can show drift in a tracked `.md` file the policy permits and you can correct it.

## 3. Delivery — full gate chain, manifest-locked

Step 2 ran `RR begin`.
If the session stops before a terminal result, the provisional `run_incomplete` row stays.
The log’s `abort=incomplete-run` marker shows that the run started and did not finish.
If the child exits without a terminal row, the runner also appends `run_abort` with `runner_exit_no_terminal`.

Run the steps in this sequence.
The `RR stage NAME` and `RR run-gate STAGE -- ARGV` commands abort with `stage_out_of_order` if the sequence is incorrect.

1. `fetch_branch`: Fetch `origin/main`. Make a branch from the commit you fetched. Run `RR stage fetch_branch` to record the branch for cleanup.
2. `evals_frozen`: Run `/coderails:task-evals` at scope `pr` and freeze the evals before editing. Run `RR stage evals_frozen`.
3. `edit_made`: Make the Step 1 edits to the tracked `.md` files. Commit them. Run `RR stage edit_made`.
4. `manifest_check`: Run `RR stage manifest_check`. It runs `diff_manifest.py --policy policy/docs-sync.policy.json` on `origin/main...HEAD`. It uses a three-dot diff with rename detection. For example, `git mv scripts/gate.sh evil.md` shows its source.

   The policy permits only tracked `.md` files. It refuses files on the self-governance deny-list. It refuses renames and copies from a source that is not an in-scope doc, and deletions of in-scope docs.

   A violation gives `out_of_manifest`, `denied_path`, `docs_sync_deny`, `docs_sync_deletion`, `special_file_type`, `status_not_allowed`, `too_many_paths`, or `manifest_unreadable`. The runner ends with `run_abort` and cleans up. Do not continue after a violation.

5. `push`: `RR run-gate push -- python3 "${CLAUDE_PLUGIN_ROOT}/scripts/push.py"`.
6. `review`: `/pr-review-toolkit:review-pr <PR#>`, then `RR stage review`.
7. `post_review`: `RR run-gate post_review -- python3 "${CLAUDE_PLUGIN_ROOT}/scripts/post_review.py" post <PR#> --summary <file>`.
8. `post_evals`: `RR run-gate post_evals -- python3 "${CLAUDE_PLUGIN_ROOT}/scripts/post_evals.py" post <PR#> <evals.json>`.
9. `merge`: `RR run-gate merge -- python3 "${CLAUDE_PLUGIN_ROOT}/scripts/merge.py" <PR#>`.
   Then run `RR finish ok` to record `run_ok` as the last terminal row.

**Use the exit code to identify gate refusal.**
If a gate fails and the PR is open, `run-gate` exits nonzero.
It records `run_refused` for the gate (`refused=<gate>`), then cleans up without recording `run_ok`.
The rule uses the exit code. It also applies when the command reports no named cause.
The `merge.py` script has more than 30 nonzero exits, plus errors that bypass its error function.

For example, `integrity-review` can be `pending`.
The `/coderails:merge` command exits nonzero if the GitHub workflow has not posted the mandatory status.
If GitHub shows that the same PR and head merged despite a CLI error, `run-gate merge` moves to the next step.
If GitHub cannot show the merge status, the run remains unsuccessful and cleanup stops.

Do not wait, poll, or retry for a gate to succeed.
After a refusal, do not retry in the same run or relax a gate.
Do not invent a marker.
The `RR abort CODE` and `RR refuse GATE` commands accept only codes from the spec.
The historical marker `merge-blocked reason=integrity-review-pending` gives exit 2.
For an audit that cannot continue, use `RR abort audit_failed`.

After an abort, refusal, manifest violation, or gate refusal, cleanup runs one time in code with `git` and `gh`.
It closes the open PR if one was made.
It removes the local branch only if the current branch is the one recorded in `fetch_branch`.
It keeps the remote branch and uses no `rm`.
Do not close a merged PR or log it as an abort.

## 4. Run log and failure visibility

Use the spec’s `log` path, `~/.claude/coderails-dashboard/routines/docs-sync/run-{date}.log`.
The `{date}` is the local calendar date, as from `localDateIso()`.
Use `--log PATH` only if `~/.claude/coderails-dashboard.json` specifies a different `expectedArtifact.artifactPath`.
The JSONL log and run data use the same path with `.jsonl` and `.state.json` suffixes.
Do not use a repo-relative log or reuse a log at a different location.
The gate reads only its configured path.

The `last-marker` predicate reads the last terminal marker in the date’s log.
It succeeds only if that marker is `run=ok`.
An abort after an earlier `run=ok` on the same date makes the gate refuse the run.
The `abort=incomplete-run` marker means the run began but did not record a terminal result.

Keep the two escalation channels `escalation: ["notification", "vault-note"]`.
Each abort or refusal writes its cause to the run note through `vault-note`.
It also writes an `abort=<code>` or `refused=<gate>` line in the run log through `routine_run.py`.
Check the macOS notification first, then the vault-note run history, then the run log.
The run does not give a dashboard alert or PR comment for an error.

## 5. Prohibitions

Write only tracked documentation `.md` files that the policy permits.
Do not edit hook scripts, gate code, paths in `scripts/`, `install.py`, this `SKILL.md`, or code.
Do not edit the schedule config (`~/.claude/coderails-dashboard.json` or `examples/dashboard-config.json`) or `.claude/settings.json`.

The self-governance deny-list is in `policy/docs-sync.policy.json`.
The `stage manifest_check` command checks this list and refuses non-`.md` paths.
Changes to `skills/**/SKILL.md`, `AGENTS.md`, `CLAUDE.md`, `docs/routines.md`, or paths in `.claude/` abort before push.
The agent can skip the command because `PreToolUse` hooks do not run in `claude -p`.
This rule reduces the risk of self-governance changes.
The command supplies no hook-level or server-level check.

The default-on `diff_manifest` publication gate in `merge.py` checks the same diff again at merge.
See the alert about these risks in `docs/routines.md`.

Do not relax, reorder, or skip a gate.
Use only `merge.py` (`/coderails:merge`) to merge.
Do not use raw `gh pr merge`.
In headless mode, `PreToolUse` hooks do not run.
The script’s artifact gates apply during merge without the `test_gate` and `enforce_pr_workflow` hooks.

Do not edit the workflow-tools/claude-guardrails migration section of `INSTALLATION.md`.
Those names document current installer behavior.
The installer exits on them at `install.py:232`.

Read the code before you correct a document to agree with it.
If the audit is uncertain, report it and do not edit.
