---
name: docs-sync
description: On-demand pipeline for manually auditing this repo's git-tracked documentation for drift and, only when drift is found, editing, pushing, reviewing, and merging a fix. Use $coderails-codex:sync-docs for a report-only drift check.
---

# Docs Sync

Set `SKILL_DIR` to the absolute directory containing this `SKILL.md` when a
package helper path is needed below.

On-demand pipeline. Native Codex bundles no automatic scheduler; invoke this
skill manually when a full audit-and-delivery run is wanted. It audits this
repo's git-tracked documentation against the actual codebase. If nothing is
wrong, it logs that and stops — no branch, no PR. If something is wrong, it
fixes it through the full gate chain and merges the fix itself.

This skill is package-local and needs no external or user-specific skill path.

## 1. Audit

Invoke `$coderails-codex:sync-docs` and run its audit phases: discover
project structure, traditional audit, generate a drift report) to detect
drift between this repo's documentation and its actual code.

**Scope of docs this routine may fix: git-tracked `.md` files only** —
`README.md`, `AGENTS.md`, `AGENTS.md`, and tracked files under `docs/`
— **except the self-governance deny-list in step 4 below**
(`skills/**/SKILL.md`, `AGENTS.md`, `AGENTS.md`, `docs/routines.md`,
anything under `.codex/`, `examples/dashboard-config.json`). Yes, this
means `AGENTS.md` and `AGENTS.md` are named in both the general scope
above and the deny-list — read the deny-list as an override: if the
audit finds drift in a deny-listed file, report it, do not fix it. This
routine can flag that its own governing documents look stale; it can
never be the one to edit them. Before treating any `docs/*.md` file as
in-scope, confirm it is actually tracked and not gitignored:

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

If the audit in step 1 finds nothing to fix:

1. Append a timestamped `no-drift` line to the run log (step 4).
2. Append a terminal `run=ok` line to the run log — the canonical success
   marker retained by the historical `last-marker` semantics. There is no
   separate report file to write on a no-drift run.
3. Exit 0.

Do **NOT** create a branch. Do **NOT** open a pull request. A no-drift
result is a successful, quiet run, not a reason to open an empty or
no-op PR. This short-circuit prevents PR spam when nothing needs fixing.

Only proceed to step 3 (Delivery) if the audit found at least one
concrete, git-tracked `.md` drift item this routine is confident about
fixing.

## 3. Delivery — full gate chain, manifest-locked

1. Fetch `origin/main`; branch off the freshly-fetched tip.
2. Invoke `$coderails-codex:task-evals` with scope `pr` and FREEZE it — BEFORE
   making the edit.
3. Make the doc edits identified in step 1 (git-tracked `.md` files
   only).
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

   Two-dot compares against whatever `origin/main` happens to be at
   assertion time; if a sibling PR merges into `main` mid-run, that
   comparison base has moved and a two-dot diff can indict an
   otherwise-clean branch for files it never touched. Three-dot compares
   against the merge-base as of when this branch forked, which is the
   only comparison actually scoped to what *this* routine changed.

   `--name-only` prints a rename as its DESTINATION path alone, so
   `git mv scripts/gate.sh evil.md` appears as bare `evil.md` — which is
   `.md`, is on no deny-list, and therefore passes conditions 1 and 2
   while smuggling a shell script into the repo. `--name-status` prints
   `R100  scripts/gate.sh  evil.md`, exposing the source. The same flag
   is what makes condition 4 checkable at all: under `--name-only` a
   deletion and an edit are the identical single line `README.md`, while
   `--name-status` prints `D  README.md`. Conditions 3 and 4 are not
   reachable without `--name-status`; this is why the flag is mandatory
   rather than stylistic.

   **Self-governance deny-list (permanently out of scope, regardless of
   file extension):**
   - any `skills/**/SKILL.md` — including this skill's own file, and
     every other skill in the plugin
   - `AGENTS.md`
   - `AGENTS.md`
   - `docs/routines.md`
   - anything under `.codex/`
   - `examples/dashboard-config.json` (already excluded by the
     non-`.md` rule below, named here explicitly so the deny-list is a
     complete, self-contained list on its own)

   These are this routine's own governing files: documents that define
   what it is allowed to do. A drift finding against any of them
   is **reported** in the run log and the run-note, **never fixed** by
   this routine; it is escalated to a human instead, exactly like any
   other abort. This is not advisory: the assertion in this step MUST
   fail the manifest check the same way a non-`.md` path does, and
   nothing in the prose of this skill can waive it — see Prohibitions
   below for why this is a mechanism, not merely a stated intent.

   If ANY non-`.md` path appears in that diff — anything under `hooks/`,
   `scripts/`, `skills/*/` other than a `.md` file, any `.sh`, `.json`,
   `.ts`, `.yaml` — **or ANY deny-listed path appears, even though it is
   `.md`** — **ABORT WITH CLEANUP**: close the PR if one was opened,
   delete the branch both locally and on the remote, and append an
   `abort=<reason>` line to the run log. Do not leave orphaned branches,
   PRs, or partial state. **ABORT, never warn-and-continue** — a
   non-`.md` path, or a deny-listed `.md` path, in the diff is a hard
   stop, not a warning to log and push anyway.
5. Invoke `$coderails-codex:push`.
6. Spawn the installed `spec-reviewer` custom agent to review the current PR
   head against this run's scope and manifest. Add `deploy-safety-reviewer`
   only when the change has a production surface. Wait for and close each.
7. Invoke `$coderails-codex:post-review <PR#>`.
8. Invoke `$coderails-codex:post-evals <PR#>`.
9. Invoke `$coderails-codex:merge`. Once the merge succeeds, append a terminal
   `run=ok` line to the run log as the last line — the canonical
   success marker under the historical `last-marker` semantics.

**Claim the terminal-marker slot BEFORE step 5, not only after step 9.**
Immediately before starting step 5, append `abort=incomplete-run` to the
run log. Then, on reaching a terminal outcome, append the real marker
(`run=ok`, `abort=<reason>`, or `refused=<gate>`) — the LAST terminal marker
defines the run's outcome, so the real outcome supersedes the provisional one.

This ordering exists because steps 5–9 are prose instructions executed by
an agent session, and a session can end mid-sequence — a turn budget
exhausted, a context limit, a killed process — without executing any
further instruction. A marker written only after step 9 is therefore not
guaranteed to be written at all. When that happens the run log ends with
no terminal marker, historically reported as "Artifact has no terminal marker"
— a state that is indistinguishable from a run that never started, and
unrecoverable from the artifact afterwards. Claiming the slot up front
converts that silent gap into an honest `abort=incomplete-run`, which
correctly records failure.

No scheduler or wrapper backfills this marker for an interrupted run. If the
invoking session ends before writing a real terminal marker, the provisional
`abort=incomplete-run` line remains the honest final outcome.

Any of steps 5–9 can REFUSE rather than the routine choosing to abort.
**The trigger is the mechanism, not the reason: if the step's command
exits non-zero, that is a refusal.** This is deliberately keyed on the
exit code rather than on a list of rejecting reasons, because a list
only covers the outcomes someone thought to enumerate. `$SKILL_DIR/../../scripts/merge.sh`
alone has more than thirty distinct non-zero exits through one shared
`err` function, PLUS failures that bypass `err` entirely — it runs under
`set -euo pipefail`, so an unguarded command aborts the script directly
(the `gh pr merge` call is exactly this: its own comment says "its
failure must abort"). Counting the `err` calls therefore does not
enumerate the exits either, which is the point. A run must terminate on
every one of them, including the ones added after this sentence was
written.

Treat a refusal the same as an abort: close the PR if one is open,
delete the branch locally and on the remote, and append a
`refused=<gate>` line to the run log (e.g. `refused=post-evals` or
`refused=merge`) naming which step refused. Never retry past a refusal
in the same run and never relax the gate that refused. **Never append
`run=ok` on this path** — an abort (step 4) or a refusal (steps 5–9)
writes `abort=`/`refused=` only; the success marker is written on
successful completion of a no-drift or merged run and on no other
path.

**A non-zero exit that is neither a pass nor a rejection is still a
refusal.** The worked example is a `pending` `integrity-review` status:
`$coderails-codex:merge` exits non-zero because the integrity daemon has not
yet posted its attestation — the gate has not rejected the PR, it has not
yet attested it. Write `refused=merge` and clean up, exactly as for a
rejection. **Never wait, poll, or retry for a gate to resolve**, and
**never invent a new marker** to describe an outcome the terminal set
does not name. Both were tried on 2026-07-26 and 2026-07-27: the run
logged `merge-blocked reason=integrity-review-pending`, a string that appears
in no historical `failures` list and which the `last-marker` semantics
therefore could not interpret, then waited for the status to resolve until
the session ended. The three terminal markers (`run=ok`, `abort=<reason>`,
`refused=<gate>`) are the complete set — an outcome that is not one of
them is not a new marker, it is a refusal that has not been written yet.

Append a timestamped per-stage line to the run log after each gate step
above (fetch/branch, evals frozen, edit made, manifest check, push,
review, post-review, post-evals, merge) — same convention as
`loop-retro-promotion`'s `promotion-runs.log`.

## 4. Run log and failure visibility

Preserve the historical append-only run ledger at
`~/.codex/coderails-dashboard/routines/docs-sync/run-{date}.log`, where
`{date}` is the manually invoked run's local calendar date (`YYYY-MM-DD`). This
path and its last-marker semantics preserve continuity with existing run
history; they do not imply automatic execution. Write to that path and no
other. Never write the run log to a repo-relative path such
as `.codex/docs-sync-runs/`, and never adopt a pre-existing log file
found at a different location just because it is there — a log at any
other path breaks continuity with the historical ledger. If that file appears
absent at write time, create it; do not relocate the write. One line per stage
per run, timestamped ISO8601. The no-drift
short-circuit (step 2) and every delivery stage (step 3) write to this
same file — it is both this routine's durable record of what happened in
an invocation AND the historical artifact checked by its last-marker
semantics, mirroring
`loop-retro-promotion`'s `promotion-runs.log` convention.

`run=ok` is the canonical terminal success marker. Preserve the historical
`last-marker` rule keyed on this exact string, with `abort=` and `refused=` as
failure markers. Write it as the final terminal marker on both success paths — the no-drift
short-circuit (step 2) and a completed merge (step 3, after step 9) — and
NEVER on an abort or a refusal. The LAST terminal marker defines the outcome,
which is successful only when that marker is `run=ok`: this per-date log is
append-only across many runs, so a same-date run that aborts after an
earlier run wrote `run=ok` must still read red — the most recent run's
outcome wins, not merely whether `run=ok` appears anywhere. A run log
merely *existing* does not mean the run succeeded (an aborted or
refused run still writes a log describing its own failure); only a
trailing `run=ok` does.

`abort=incomplete-run` is a fourth terminal marker, written provisionally
before step 5 and superseded by whichever real marker the run reaches (see
step 9). Because the historical rule uses the LAST terminal marker, a run that
completes overwrites its own provisional line in effect, while a run whose
session ends mid-sequence leaves it standing and correctly records failure. A
log whose last marker is `abort=incomplete-run` therefore means the run
started the push/merge sequence and never reached a terminal outcome —
not that it was never attempted.

When the invoking environment provides the historical escalation channels
(`notification` and `vault-note`), keep both; the run ledger does not replace
them. Every abort (step 4) or refusal (steps 5–9) records both of the following:

1. Writes its reason into the run-note (the `vault-note` escalation
   channel — same file the routine's normal green/red history already
   goes to).
2. Appends a durable, greppable marker line to this run log —
   `abort=<reason>` for a manifest-scope abort, `refused=<gate>` for a
   downstream gate refusal — so a later audit can `grep` every failed
   run across the whole log in one pass instead of re-reading each
   run-note individually.

Where a human should actually look, in order: the macOS notification
first (transient — easy to miss if you're away), then the vault-note
run history (one entry per run, human-readable), then this run log's
`abort=`/`refused=` lines (the fast, grep-able summary across many
runs). There is no dashboard alert and no PR comment for a failed
run — notification + vault-note are the entire failure-visibility
surface for this routine, same as every other routine in this file.

## 5. Prohibitions

This pipeline writes ONLY git-tracked documentation `.md` files. It
NEVER edits: hook scripts, gate logic, anything under `scripts/`,
`install.sh`, its own `SKILL.md`, the routine config
(`~/.codex/coderails-dashboard.json` or
`examples/dashboard-config.json`), `.codex/settings.json`, or any code.

**This is mechanically enforced, not merely stated.** The
self-governance deny-list in step 4 is checked by the same manifest
assertion that rejects a non-`.md` path — an edit to `skills/**/SKILL.md`
(including this file), `AGENTS.md`, `AGENTS.md`, `docs/routines.md`, or
anything under `.codex/` aborts the run exactly like a code change
would, before push. It is not left to this prose alone to be honoured.
That said, be honest about the limit: this enforcement lives in the
skill's own instructions — it reduces the risk of self-governance drift,
but does not eliminate it the way a hook-level or server-side check would. See the
security warning in `docs/routines.md` for the same caveat stated for
the reader operating this routine.

It never relaxes, reorders, or skips a gate. It merges only via
`$coderails-codex:merge`, never raw `gh pr merge`, so the package-local merge
script's artifact checks remain in force.

It must NEVER edit `INSTALLATION.md`'s workflow-tools/codex-guardrails
migration section — those names document live installer behaviour
(`install.sh:232` hard-exits on them) and are not documentation drift for
this routine to "fix."

It never "fixes" a doc to match code it has not read — no guessing. If
the audit is uncertain, it reports rather than edits.
