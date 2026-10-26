---
name: docs-sync
description: Scheduled nightly pipeline that audits this repo's git-tracked documentation for drift against the actual codebase, and — only if drift is found — edits, pushes, reviews, and self-merges a fix with no human in the loop. Runs on a schedule, NOT for interactive use — for an interactive drift check, use /sync-docs directly instead.
effort: high
---

# Docs Sync

Machine-run pipeline. Every night it audits this repo's git-tracked
documentation for drift against the actual codebase. If nothing is
wrong, it logs that and stops — no branch, no PR. If something is wrong,
it fixes it through the full gate chain and merges the fix itself.

This replaces the former `sync-docs-weekly` routine, which was
**read-only** and had been silently broken for 9 days (its
`foreignSkillPath` pointed at a path that never existed). `docs-sync`
needs no `foreignSkillPath`: this skill lives in the plugin, same as
`loop-retro-promotion`.

**State machine.** Everything after the audit is one script,
`routine_run.py`, shared with `loop-retro-promotion` (spec:
`routines/docs-sync.json`: the ordered stages, the policy file, the log
path and the cleanup). It needs no hooks, so it works headless
(`claude -p`). Write `RR` for
`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/routine_run.py" docs-sync`. Do not
write the run log by hand: `routine_run.py` appends a JSONL event row
(closed outcomes `stage_ok`, `run_ok`, `run_abort`, `run_refused`,
`run_incomplete`; closed reason codes in the spec) and derives the legacy
marker line (`run=ok`, `abort=<code>`, `refused=<gate>`,
`abort=incomplete-run`) that the dashboard's `last-marker` predicate reads.
An outcome or code outside the closed lists is refused (exit 2).
`RR begin` refuses an open run even across midnight. Explicit `RR begin --new`
first aborts the previous open id; never replace a run merely to hide its failure.
`log_unwritable` refuses state advancement; inspect both logs and state for
partial writes. Same-user forgery and runner limits are in `docs/routines.md`.

## 1. Audit

Invoke `/coderails:sync-docs`'s audit (Phases 1–3 of that skill: discover
project structure, traditional audit, generate a drift report) to detect
drift between this repo's documentation and its actual code.

**Scope of docs this routine may fix: git-tracked `.md` files only** —
`README.md`, `AGENTS.md`, `CLAUDE.md`, and tracked files under `docs/` —
**except the self-governance deny-list** in `policy/docs-sync.policy.json`
(`skills/**/SKILL.md`, `AGENTS.md`, `CLAUDE.md`, `docs/routines.md`,
anything under `.claude/`, `examples/dashboard-config.json`). Read the
deny-list as an override: if the audit finds drift in a deny-listed file,
report it, do not fix it. This routine can flag that its own governing
documents look stale; it can never be the one to edit them. Before
treating any `docs/*.md` file as in-scope, confirm it is actually tracked
and not gitignored:

```bash
git ls-files --error-unmatch <path>          # tracked, or
git check-ignore -q <path> && echo IGNORED   # gitignored — EXCLUDE
```

Any doc that is gitignored, or any file this routine has not actually
read, is out of scope. **Never "fix" a doc to match code this routine has
not read** — no guessing. If the audit is uncertain whether a section is
actually stale, it reports the uncertainty rather than editing it.

## 2. NO-DRIFT SHORT-CIRCUIT

**This step runs BEFORE any branch or PR is created — it is the first
thing this routine decides after the audit completes.**

Run `RR begin` (writes the state file and a provisional `run_incomplete`
row), then, if the audit finds nothing to fix, `RR finish no_drift`
(emits `run_ok`; the derived `run=ok` marker is what the routine's
`expectedArtifact` predicate keys on). Exit 0.

Do **NOT** create a branch. Do **NOT** open a pull request. A no-drift
night is a successful, quiet run, not a reason to open an empty or no-op
PR. Only proceed to step 3 if the audit found at least one concrete,
git-tracked `.md` drift item this routine is confident about fixing.

## 3. Delivery — full gate chain, manifest-locked

`RR begin` has already run (step 2), so a session that ends mid-sequence
leaves the standing `run_incomplete` row: the log reads red
(`abort=incomplete-run`), distinguishable from a run that never started.
The runner also appends `run_abort` `runner_exit_no_terminal` when a
routine child exits without a terminal row.

Run the stages in this order. `RR stage NAME` and `RR run-gate STAGE -- ARGV`
enforce it; a call out of order aborts the run (`stage_out_of_order`).

1. `fetch_branch`: fetch `origin/main`, branch off the freshly-fetched tip,
   then `RR stage fetch_branch` (records the branch for cleanup).
2. `evals_frozen`: run `/coderails:task-evals` (scope: `pr`) and FREEZE it
   BEFORE making the edit, then `RR stage evals_frozen`.
3. `edit_made`: make the doc edits identified in step 1 (git-tracked `.md`
   files only), commit them, then `RR stage edit_made`.
4. `manifest_check`: `RR stage manifest_check`. It runs
   `diff_manifest.py --policy policy/docs-sync.policy.json` itself over
   `origin/main...HEAD` (three-dot, with rename detection, so
   `git mv scripts/gate.sh evil.md` shows its source). Any violation
   (`out_of_manifest`, `denied_path`, `docs_sync_deny`, `docs_sync_deletion`,
   `special_file_type`, `status_not_allowed`, `too_many_paths`,
   `manifest_unreadable`) ends the run `run_abort` with cleanup.
   **ABORT, never warn-and-continue.** The policy encodes: every path is a
   git-tracked `.md` file; no path is on the self-governance deny-list (even
   though each is itself `.md`); no rename or copy whose source was not an
   in-scope doc; no deletion of an in-scope doc.
5. `push`: `RR run-gate push -- python3 "${CLAUDE_PLUGIN_ROOT}/scripts/push.py"`.
6. `review`: `/pr-review-toolkit:review-pr <PR#>`, then `RR stage review`.
7. `post_review`: `RR run-gate post_review -- python3 "${CLAUDE_PLUGIN_ROOT}/scripts/post_review.py" post <PR#> --summary <file>`.
8. `post_evals`: `RR run-gate post_evals -- python3 "${CLAUDE_PLUGIN_ROOT}/scripts/post_evals.py" post <PR#> <evals.json>`.
9. `merge`: `RR run-gate merge -- python3 "${CLAUDE_PLUGIN_ROOT}/scripts/merge.py" <PR#>`.
   Then `RR finish ok` (emits `run_ok`, the last terminal row).

**The trigger is the mechanism, not the reason: `run-gate` exits non-zero
when a gate fails and the PR is still open.** It records
`run_refused` for that gate (`refused=<gate>`), cleans up, and never emits
`run_ok`. This is keyed on the exit code, not on a list of rejecting
reasons: `merge.py` has more than thirty distinct non-zero exits plus
failures that bypass its own error function, so any list is incomplete. A
non-zero exit that is neither a pass nor a rejection is still a refusal; the
worked example is a `pending` `integrity-review` status, where
`/coderails:merge` exits non-zero because GitHub Actions has not yet posted
the required status. If GitHub confirms the exact PR and head merged despite
a CLI error, `run-gate merge` advances the stage. If GitHub cannot confirm
the state, the run stays red and cleanup stops.
**Never wait, poll, or retry for a gate to resolve**, never retry past a
refusal in the same run, never relax the gate that refused, and
**never invent a new marker**: `RR abort CODE` and `RR refuse GATE` accept only the
spec's closed reason codes (the historical invented marker
`merge-blocked reason=integrity-review-pending` is refused with exit 2).
Use `RR abort audit_failed` for an audit that cannot continue.

Cleanup (on `abort`, `refuse`, a manifest violation or a refused gate) runs
once, in code, with `git` and `gh` only: close the PR if one was opened,
delete the current local branch only while still on the branch recorded at
`fetch_branch`. The remote branch is left intact. No file is removed with
`rm`. A confirmed merged PR is never closed or logged as an abort.

## 4. Run log and failure visibility

The log path is the spec's `log`
(`~/.claude/coderails-dashboard/routines/docs-sync/run-{date}.log`, `{date}`
the run's LOCAL calendar date, matching the runner's `localDateIso()`); pass
`--log PATH` only when `~/.claude/coderails-dashboard.json` names a
different `expectedArtifact.artifactPath`. The JSONL log and the state file
sit beside it with `.jsonl` and `.state.json` suffixes. Never write the run
log to a repo-relative path, and never adopt a pre-existing log at a
different location: a log at any other path is invisible to the gate.

The `last-marker` predicate takes the LAST terminal marker in the per-date
log and passes only if it is `run=ok`, so a same-date run that aborts after
an earlier `run=ok` still reads red. A log whose last marker is
`abort=incomplete-run` means the run began and never reached a terminal
outcome, not that it was never attempted.

This routine keeps both of its config's escalation channels
(`escalation: ["notification", "vault-note"]`). Every abort or refusal does
BOTH: writes its reason into the run-note (the `vault-note` channel), and
leaves its greppable `abort=<code>` / `refused=<gate>` line in the run log
(written by `routine_run.py`). Where a human should look, in order: the macOS
notification, the vault-note run history, then the run log. There is no
dashboard alert and no PR comment for a failed run.

## 5. Prohibitions

This pipeline writes ONLY git-tracked documentation `.md` files. It
NEVER edits: hook scripts, gate logic, anything under `scripts/`,
`install.py`, its own `SKILL.md`, the routine config
(`~/.claude/coderails-dashboard.json` or `examples/dashboard-config.json`),
`.claude/settings.json`, or any code.

**This is mechanically enforced, not merely stated.** The self-governance
deny-list is data in `policy/docs-sync.policy.json`, checked by the same
`stage manifest_check` that rejects a non-`.md` path: an edit to
`skills/**/SKILL.md` (including this file), `AGENTS.md`, `CLAUDE.md`,
`docs/routines.md`, or anything under `.claude/` aborts the run before push.
The limit: it runs under `claude -p`, where `PreToolUse` hooks do not fire,
and the agent could skip calling it; it reduces the risk of
self-governance drift, it does not eliminate it the way a hook-level or
server-side check would. The default-on publication gate in `merge.py`
(`diff_manifest`) checks the same diff again at merge. See the security
warning in `docs/routines.md`.

It never relaxes, reorders, or skips a gate. It merges ONLY via
`merge.py` (`/coderails:merge`) — never raw `gh pr merge`: `PreToolUse`
hooks do not fire in this headless execution mode, so `test_gate` and
`enforce_pr_workflow` do not protect this routine's runs either;
`scripts/merge.py`'s own script-internal artifact gates are the merge rail.

It must NEVER edit `INSTALLATION.md`'s workflow-tools/claude-guardrails
migration section — those names document live installer behaviour
(`install.py:232` hard-exits on them) and are not documentation drift for
this routine to "fix."

It never "fixes" a doc to match code it has not read — no guessing. If
the audit is uncertain, it reports rather than edits.
