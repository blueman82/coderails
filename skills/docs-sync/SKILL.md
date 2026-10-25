---
name: docs-sync
description: Scheduled nightly pipeline that audits this repo's git-tracked documentation for drift against the actual codebase, and — only if drift is found — edits, pushes, reviews, and self-merges a fix with no human in the loop. Runs on a schedule, NOT for interactive use — for an interactive drift check, use /sync-docs directly instead.
effort: high
---

# Docs Sync

This scheduled pipeline checks tracked documentation against the code each
night. If it finds no drift, it logs that result and stops. If it finds
drift, it fixes the files, runs the gates, and merges the fix.

This replaces the former `sync-docs-weekly` routine. That routine only
wrote drift reports. Its `foreignSkillPath` pointed to the absent path
`/Users/harrison/.claude/skills/sync-docs/SKILL.md`, so it failed silently
for 9 days. The skill is at `skills/sync-docs/SKILL.md` in this repo.
`docs-sync` needs no `foreignSkillPath` because this file is in the plugin.

## 1. Audit

Invoke `/coderails:sync-docs`'s audit (Phases 1–3 of that skill: discover
project structure, traditional audit, generate a drift report) to detect
drift between this repo's documentation and its actual code.

**Fix scope: git-tracked `.md` files only**, such as `README.md` and files
under `docs/`. The self-governance deny-list in step 4 overrides this
general scope. It includes `AGENTS.md`, `CLAUDE.md`, `docs/routines.md`,
`skills/**/SKILL.md`, and anything under `.claude/`. Report drift in
these files; do not fix it. Before fixing a `docs/*.md` file, confirm
that Git tracks it and does not ignore it:

```bash
git ls-files --error-unmatch <path>          # tracked, or
git check-ignore -q <path> && echo IGNORED   # gitignored — EXCLUDE
```

An ignored document or unread file is outside the fix scope. Read the code
before changing a document to match it. If the audit cannot confirm drift,
report the uncertainty and leave the file alone.

## 2. NO-DRIFT SHORT-CIRCUIT

Run this step immediately after the audit, **BEFORE any branch or PR is created**.

If the audit in step 1 finds nothing to fix:

1. Append a timestamped `no-drift` line to the run log (step 4).
2. Append a terminal `run=ok` line to the run log — the canonical
   success marker the routine's `expectedArtifact` (a `last-marker`
   predicate against that same run-log path) keys on. Writing this line
   satisfies the artifact gate; there is no separate report file to
   write on a no-drift night.
3. Exit 0.

For a no-drift run, do **not** create a branch. Do **not** open a pull request.
The log records a successful run without an empty PR.

Only proceed to step 3 (Delivery) if the audit found at least one
concrete, git-tracked `.md` drift item this routine is confident about
fixing.

## 3. Delivery — full gate chain, manifest-locked

1. Fetch `origin/main`; branch off the freshly-fetched tip.
2. Run `/coderails:task-evals` (scope: `pr`) and FREEZE it — BEFORE
   making the edit.
3. Make the doc edits identified in step 1 (git-tracked `.md` files only).
   Stage only those named paths and commit them before step 4. The diff in
   step 4 compares commits. If the edits are uncommitted, its output is
   empty and the assertion cannot check the changed paths. Do not use
   `git add -A`; it can sweep in unrelated files.
4. **Assert `git diff origin/main...HEAD --name-status` (THREE-dot, not
   two; `--name-status`, never `--name-only`) satisfies ALL FOUR of the
   conditions below. Any violation is an ABORT WITH CLEANUP.**

   1. Every path is a git-tracked `.md` file.
   2. No path is in the self-governance deny-list below — even though
      every one of them is itself `.md`.
   3. No line has status `R` or `C` (rename/copy) unless its SOURCE path
      was already an in-scope `.md` doc.
   4. No line has status `D` (deletion) for an in-scope doc. This
      routine fixes drift in a doc; it never deletes one.

   Use three-dot to compare with the branch's merge base. A two-dot diff
   uses the current `origin/main`. If another PR merges during this run,
   that base moves. The two-dot diff can then show files this branch did
   not change.

   Use `--name-status` to inspect both paths in a rename. With
   `--name-only`, `git mv scripts/gate.sh evil.md` appears only as
   `evil.md`. It could pass the `.md` and deny-list checks. With
   `--name-status`, it appears as `R100 scripts/gate.sh evil.md`.
   The flag also distinguishes deletion from editing. For `README.md`,
   `--name-only` prints the same path for either action. `--name-status`
   prints `D README.md` for deletion. Conditions 3 and 4 require it.

   **Self-governance deny-list (permanently out of scope, regardless of
   file extension):**
   - any `skills/**/SKILL.md` — including this skill's own file, and
     every other skill in the plugin
   - `AGENTS.md`
   - `CLAUDE.md`
   - `docs/routines.md`
   - anything under `.claude/`
   - `examples/dashboard-config.json` (already excluded by the
     non-`.md` rule below, named here explicitly so the deny-list is a
     complete, self-contained list on its own)

   These are documents that define what this routine can do. Report drift in the run log and
   run-note, then escalate it to a human. Do not edit them. The manifest
   assertion must reject these paths just as it rejects a non-`.md` path.
   See Prohibitions below for the enforcement limit.

   If the diff contains a non-`.md` path or a deny-listed path, **abort
   with cleanup**. Close any open PR. Delete the branch locally and on
   the remote. Append `abort=<reason>` to the run log. Do not continue
   after this manifest failure. **ABORT, never warn-and-continue.**
5. `/coderails:push`
6. `/pr-review-toolkit:review-pr <PR#>`
7. `/coderails:post-review <PR#>`
8. Run the frozen checks and negative controls, grade their results, then
   invoke `/coderails:post-evals <PR#>`.
9. `/coderails:merge`. Once the merge succeeds, append a terminal
   `run=ok` line to the run log as the last line — the canonical
   success marker the `last-marker` gate keys on.

**Claim the terminal-marker slot BEFORE step 5, not only after step 9.**
Immediately before starting step 5, append `abort=incomplete-run` to the
run log. Then, on reaching a terminal outcome, append the real marker
(`run=ok`, `abort=<reason>`, or `refused=<gate>`) — the gate reads the
LAST terminal marker, so the real outcome supersedes the provisional one.

Steps 5–9 run as agent instructions. The session can end between them due
to a turn limit, context limit, or stopped process. If the routine writes
its first terminal marker after step 9, an interrupted run has none. The
gate then reports "Artifact has no terminal marker" and cannot distinguish
that run from one that never started. The provisional
`abort=incomplete-run` records an interrupted run as a failure.

Write this marker in the routine. The runner writes one only when it kills
the routine after a SIGKILL timeout. If a session ends and its process exits
0, the runner cannot tell whether the routine finished or failed silently.
It writes no marker in that case.

Any step from 5–9 can refuse the run. **Treat every non-zero exit as a
refusal.** Check exit status, not known error text. Stop even for a new
failure mode in `scripts/merge.py` or `gh pr merge`.

Treat a refusal the same as an abort: close the PR if one is open,
delete the branch locally and on the remote, and append a
`refused=<gate>` line to the run log (e.g. `refused=post-evals` or
`refused=merge`) naming which step refused. Never retry past a refusal
in the same run and never relax the gate that refused. **Never append
`run=ok` on this path** — an abort (step 4) or a refusal (steps 5–9)
writes `abort=`/`refused=` only; the success marker is written on
successful completion of a no-drift or merged night and on no other
path.

**A pending gate that exits non-zero is a refusal.** The worked example is a `pending` `integrity-review` status.
`/coderails:merge` exits non-zero before
GitHub Actions posts its attestation. Write `refused=merge` and clean up.
Never wait, poll, or retry. Never invent a new marker. On
2026-07-26 and 2026-07-27, the routine wrote
`merge-blocked reason=integrity-review-pending`. The `last-marker` gate
could not see that string in its configured failure list. The session
then ended while it waited. Use only `run=ok`, `abort=<reason>`, or
`refused=<gate>` for a final outcome.

Append a timestamped per-stage line to the run log after each gate step
above (fetch/branch, evals frozen, edit made, manifest check, push,
review, post-review, post-evals, merge) — same convention as
`loop-retro-promotion`'s `promotion-runs.log`.

## 4. Run log and failure visibility

Use one append-only log at the config's `expectedArtifact.artifactPath`.
The current path is
`~/.claude/coderails-dashboard/routines/docs-sync/run-{date}.log`.
Check `~/.claude/coderails-dashboard.json` if it may have changed.
`{date}` is the run's local date in `YYYY-MM-DD` format.
`localDateIso()` in `skills/dashboard/runner/src/sweep.ts` supplies it.

Write only to that path. A log elsewhere is invisible to the gate.
Create the file there if it is absent. Append one ISO8601 timestamped
line per stage. Both the no-drift path and the delivery path use it.
It records the run and serves as the gate artifact, like
`loop-retro-promotion`'s `promotion-runs.log`.

`run=ok` is the terminal success marker. The config's
`expectedArtifact.predicate` checks the **last** terminal marker.
Write `run=ok` after a no-drift run or a completed merge, and never after
an abort or refusal. The log can hold several runs on one date. A later
`abort=` or `refused=` makes that date fail even if an earlier run passed.
The log's existence alone does not prove success.

Write `abort=incomplete-run` provisionally before step 5. A later final
marker supersedes it because the gate reads the last marker. If it stays
last, the run started the push and merge sequence but did not finish.

Keep both configured escalation channels:
`escalation: ["notification", "vault-note"]`. For each abort or refusal,
do both of these actions:

1. Writes its reason into the run-note (the `vault-note` escalation
   channel — same file the routine's normal green/red history already
   goes to).
2. Appends a durable, greppable marker line to this run log —
   `abort=<reason>` for a manifest-scope abort, `refused=<gate>` for a
   downstream gate refusal — so a later audit can `grep` every failed
   night across the whole log in one pass instead of re-reading each
   run-note individually.

For a failed run, check the macOS notification first. Then read the
vault-note history and the log's `abort=` or `refused=` lines. The
notification can be missed. The vault-note has one readable entry per run.
The log supports searches across nights. There is no dashboard alert and no PR comment for a failed run.

## 5. Prohibitions

This pipeline writes ONLY git-tracked documentation `.md` files. It
NEVER edits: hook scripts, gate logic, anything under `scripts/`,
`install.py`, its own `SKILL.md`, the routine config
(`~/.claude/coderails-dashboard.json` or
`examples/dashboard-config.json`), `.claude/settings.json`, or any code.

The step 4 manifest assertion checks the deny-list before push. An edit
to `skills/**/SKILL.md`, `AGENTS.md`, `CLAUDE.md`, `docs/routines.md`, or
anything under `.claude/` aborts the run like a code change. This check
is inside the skill prompt. It runs under `claude -p`, where `PreToolUse`
hooks do not fire; it reduces the risk of self-governance drift.
It is not a hook or server check. See `docs/routines.md` for the same limit.

It never relaxes, reorders, or skips a gate. It merges ONLY via
`/coderails:merge` — never raw `gh pr merge`: `PreToolUse` hooks do not
fire in this headless execution mode (`claude -p`), so
`test_gate`/`enforce_pr_workflow` do not protect this routine's runs
either — `scripts/merge.py`'s own script-internal artifact gates are the
merge rail.

It must NEVER edit `INSTALLATION.md`'s workflow-tools/claude-guardrails
migration section — those names document live installer behaviour
(`scripts/installer/claude.py:29-40` refuses those installed plugins) and are not documentation drift for
this routine to "fix."

It never "fixes" a doc to match code it has not read — no guessing. If
the audit is uncertain, it reports rather than edits.
