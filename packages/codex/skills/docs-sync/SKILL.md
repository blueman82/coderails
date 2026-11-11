---
name: docs-sync
description: On-demand pipeline for manually auditing this repo's git-tracked documentation for drift and, only when drift is found, editing, pushing, reviewing, and merging a fix. Use $coderails-codex:sync-docs for a report-only drift check.
---

# Docs Sync

Set `SKILL_DIR` to the absolute directory containing this `SKILL.md` for the helper paths below.

Invoke this skill on demand for a full audit and publication run. Native Codex has no automatic scheduler.
The skill checks this repository's Git-tracked documentation against the code.
If it finds nothing incorrect, it logs that result and stops without a branch or PR.
If it finds incorrect documentation, it makes corrections through the full gate sequence and merges them.

This skill is package-local and needs no external or user-specific skill path.

**Run controller.** `routine_run.py` controls the steps after the audit. This skill shares it with `loop-retro-promotion`.
The spec `routines/docs-sync.json` gives the step sequence, policy file, log path, and cleanup. The script needs no hooks.
Write `RR` for `python3 "$SKILL_DIR/../../scripts/routine_run.py" docs-sync`.

Do not write the run log by hand. `routine_run.py` appends a JSONL row and derives the legacy marker.
The accepted results are `stage_ok`, `run_ok`, `run_abort`, `run_refused`, and `run_incomplete`. The spec lists the accepted codes.
The legacy markers are `run=ok`, `abort=<code>`, `refused=<gate>`, and `abort=incomplete-run`.
An unlisted result or code gives exit 2.

`RR begin` refuses an open run across midnight too. Explicit `RR begin --new` first aborts the previous open ID.
Do not replace a run to hide an error. If `log_unwritable` prevents an update, examine the two logs and the run file for unfinished writes.
See `docs/routines.md` for same-user forgery and runner limits.

## 1. Audit

Invoke `$coderails-codex:sync-docs`. Find the project structure, run its traditional audit, and write a drift report.
Use the report to identify differences between the documentation and the code.

**The scope includes only Git-tracked `.md` files.** Check `README.md`, `AGENTS.md`, and tracked files in `docs/`.
Apply the self-governance deny-list in `policy/docs-sync.policy.json` before editing.
The list includes `skills/**/SKILL.md`, `AGENTS.md`, `CLAUDE.md`, `docs/routines.md`, all of `.claude/`, and `examples/dashboard-config.json`.

Report drift in deny-listed files, such as the instructions for this skill. Do not edit them.
Before you include a `docs/*.md` file in scope, check that Git tracks it and does not ignore it:

```bash
git ls-files --error-unmatch <path>          # Git knows this path, or
git check-ignore -q <path> && echo IGNORED   # gitignored — EXCLUDE
```

Do not edit files that Git ignores or files you have not read.
**Do not "fix" a doc to agree with code you have not read.** Do not guess.
If the audit cannot show a section is stale, report the uncertainty. Do not edit it.

## 2. NO-DRIFT SHORT-CIRCUIT

**Do this first after the audit, before you make a branch or PR.**
Run `RR begin` to write the run file and provisional `run_incomplete` row.
If the audit finds nothing to correct, run `RR finish no_drift`.
It writes `run_ok`. The historical `last-marker` rule keeps the derived `run=ok` marker.

Exit 0. Do not make a branch or open a PR.

Continue to step 3 only if you found a concrete difference in a Git-tracked `.md` file and can correct it with confidence.

## 3. Delivery — full gate chain, manifest-locked

`RR begin` ran in step 2. If a session ends during this sequence, its `run_incomplete` row stays in the log.
The `abort=incomplete-run` marker distinguishes it from a run that did not start.
No scheduler or wrapper writes a terminal row after an interrupted manual run.

Use the sequence below. `RR stage NAME` and `RR run-gate STAGE -- ARGV` check it.
A step out of sequence aborts the run with `stage_out_of_order`.

1. `fetch_branch`: Fetch `origin/main`. Make the branch from that fetched head.
   Run `RR stage fetch_branch` to record the branch for cleanup.
2. `evals_frozen`: invoke `$coderails-codex:task-evals` with scope `pr` and
   FREEZE it BEFORE making the edit, then `RR stage evals_frozen`.
3. `edit_made`: make the doc edits identified in step 1 (git-tracked `.md`
   files only), commit them, then `RR stage edit_made`.
4. `manifest_check`: Run `RR stage manifest_check`.
   It runs `diff_manifest.py --policy policy/docs-sync.policy.json` against `origin/main...HEAD`.
   The three-dot diff finds renames, so it shows the source of `git mv scripts/gate.sh evil.md`.

   A violation ends the run with `run_abort` and cleanup. **Abort without continuing.**
   Codes are `out_of_manifest`, `denied_path`, `docs_sync_deny`, `docs_sync_deletion`, `special_file_type`, `status_not_allowed`, `too_many_paths`, and `manifest_unreadable`.

   The policy accepts only Git-tracked `.md` paths. It rejects paths on the self-governance deny-list.
   It rejects renames or copies from a source out of scope and removal of documentation in scope.

5. `push`: `RR run-gate push -- python3 "$SKILL_DIR/../../scripts/push.py"`.
6. `review`: Start the installed `spec-reviewer` custom agent. It examines the current PR head against this run's scope and manifest.
   Add `deploy-safety-reviewer` only if the change has a production surface.
   Wait for and close each agent. Then run `RR stage review`.
7. `post_review`: `RR run-gate post_review -- python3 "$SKILL_DIR/../../scripts/post_review.py" post <PR#> --summary <file>`.
8. `post_evals`: `RR run-gate post_evals -- python3 "$SKILL_DIR/../../scripts/post_evals.py" post <PR#> <evals.json>`.
9. `merge`: `RR run-gate merge -- python3 "$SKILL_DIR/../../scripts/merge.py" <PR#>`.
   Then `RR finish ok` (emits `run_ok`, the last terminal row).

**`run-gate` exits non-zero if a gate does not succeed and the PR stays open.**
It writes `run_refused` for that gate (`refused=<gate>`) and runs cleanup. It does not write `run_ok`.
The decision uses the exit code. `merge.py` has more than thirty different non-zero exits and errors that bypass its error function.

A non-zero exit counts as a refusal. For example, `$coderails-codex:merge` exits non-zero for a `pending` `integrity-review` status.
In that condition, GitHub has not posted the mandatory status.
If GitHub confirms that the named PR and head merged despite a CLI error, `run-gate merge` goes to the next step.
If GitHub cannot confirm the result, the run stays red and cleanup stops.

**Do not wait, poll, or try again for a gate to resolve.** Do not try again after refusal in the same run.
Do not relax the gate or invent a marker.
`RR abort CODE` and `RR refuse GATE` accept only codes listed in the spec.
The historical invented marker `merge-blocked reason=integrity-review-pending` gives exit 2.
Use `RR abort audit_failed` if the audit cannot continue.

On `abort`, `refuse`, a manifest violation, or a gate refusal, the code runs cleanup one time with only `git` and `gh`.
It closes an open PR. It removes the current local branch only if it is the branch recorded at `fetch_branch`.
It keeps the remote branch and does not remove files with `rm`.
It does not close a confirmed merged PR or log it as an abort.

## 4. Run log and failure visibility

The spec's `log` path is `~/.codex/coderails-dashboard/routines/docs-sync/run-{date}.log`.
`{date}` is the run's local calendar date. Use `--log PATH` only to agree with an existing ledger at a different path.
The JSONL log and run file use `.jsonl` and `.state.json` suffixes in the same directory.

Do not write the run log to a repository-relative path or select a different existing log.
The path and last-marker rule keep continuity with run history. They do not schedule automatic runs.

The historical `last-marker` rule uses the last terminal marker in that day's log.
It reports success only for `run=ok`. An abort after an earlier `run=ok` on the same date reads red.
A last marker of `abort=incomplete-run` means the run started but did not have a terminal result.

If the calling environment gives `notification` and `vault-note`, keep the two historical escalation channels.
The run ledger does not replace them.
For each abort or refusal, the run note gives its cause. `routine_run.py` writes `abort=<code>` or `refused=<gate>` in the run log.
An unsuccessful run has no dashboard alert or PR comment.

## 5. Prohibitions

This pipeline writes only Git-tracked documentation `.md` files.
Do not edit hook scripts, gate logic, files in `scripts/`, `install.py`, this `SKILL.md`, `.codex/settings.json`, or code.
Do not edit its config at `~/.codex/coderails-dashboard.json` or `examples/dashboard-config.json`.

`stage manifest_check` rejects paths that are not `.md` and checks the self-governance deny-list in `policy/docs-sync.policy.json`.
An edit to `skills/**/SKILL.md` (this file too), `AGENTS.md`, `CLAUDE.md`, `docs/routines.md`, or files in `.claude/` aborts the run before push.

The agent can skip this check because this skill tells the agent to invoke it.
The check decreases the risk of self-governance drift. It does not have the enforcement of a hook or server check.
The policy lists `.claude/**`. It does not list `.codex/**`.

The publication gate (`pr_publication_gate`, `merge.py`) is on by default and checks the diff again at merge.
See the warning in `docs/routines.md`.

Do not relax, change the sequence of, or skip gates.
Merge only through `$coderails-codex:merge` so the package-local script checks the artifacts. Do not use raw `gh pr merge`.

Do not edit the migration section in `INSTALLATION.md` about workflow-tools and claude-guardrails.
The root installer (`scripts/installer/claude.py`, `preflight`) refuses those superseded Claude plugins.
The native Codex installation uses a different path. Those historical plugin names identify current migration checks.
Do not "fix" them as drift.

Read the code before you correct a doc to agree with it. Do not guess.
If the audit is uncertain, report the uncertainty. Do not edit the doc.
