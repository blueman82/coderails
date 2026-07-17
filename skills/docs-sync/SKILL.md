---
name: docs-sync
description: Scheduled nightly pipeline that audits this repo's git-tracked documentation for drift against the actual codebase, and — only if drift is found — edits, pushes, reviews, and self-merges a fix with no human in the loop. Runs on a schedule, NOT for interactive use — for an interactive drift check, use /sync-docs directly instead.
---

# Docs Sync

Machine-run pipeline. Every night it audits this repo's git-tracked
documentation for drift against the actual codebase. If nothing is
wrong, it logs that and stops — no branch, no PR. If something is wrong,
it fixes it through the full gate chain and merges the fix itself.

This replaces the former `sync-docs-weekly` routine, which was
**read-only** (it only ever wrote a drift report) and had been silently
broken for 9 days: its `foreignSkillPath` pointed at
`/Users/harrison/.claude/skills/sync-docs/SKILL.md`, a path that never
existed — the real skill lives in this repo at `skills/sync-docs/SKILL.md`.
`docs-sync` needs no `foreignSkillPath` at all, because its own skill
(this file) lives in the plugin, same as `loop-retro-promotion`.

## 1. Audit

Invoke `/coderails:sync-docs`'s audit (Phases 1–3 of that skill: discover
project structure, traditional audit, generate a drift report) to detect
drift between this repo's documentation and its actual code.

**Scope of docs this routine may fix: git-tracked `.md` files only** —
`README.md`, `AGENTS.md`, `CLAUDE.md`, and tracked files under `docs/`
— **except the self-governance deny-list in step 4 below**
(`skills/**/SKILL.md`, `AGENTS.md`, `CLAUDE.md`, `docs/routines.md`,
anything under `.claude/`, `examples/dashboard-config.json`). Yes, this
means `AGENTS.md` and `CLAUDE.md` are named in both the general scope
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

1. Append a timestamped `no-drift` line to the run log (step 4) — this
   IS the routine's `expectedArtifact` (an `exists` predicate against
   that same run-log path). Writing this line satisfies the artifact
   gate; there is no separate report file to write on a no-drift night.
2. Exit 0.

Do **NOT** create a branch. Do **NOT** open a pull request. A no-drift
night is a successful, quiet run, not a reason to open an empty or
no-op PR. This short-circuit exists specifically to prevent nightly PR
spam on nights when nothing needs fixing, which will be most nights.

Only proceed to step 3 (Delivery) if the audit found at least one
concrete, git-tracked `.md` drift item this routine is confident about
fixing.

## 3. Delivery — full gate chain, manifest-locked

1. Fetch `origin/main`; branch off the freshly-fetched tip.
2. Run `/coderails:task-evals` (scope: `pr`) and FREEZE it — BEFORE
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
   - `CLAUDE.md`
   - `docs/routines.md`
   - anything under `.claude/`
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
5. `/coderails:push`
6. `/pr-review-toolkit:review-pr <PR#>`
7. `/coderails:post-review <PR#>`
8. `/coderails:post-evals <PR#>`
9. `/coderails:merge`

Any of steps 5–9 can REFUSE (a failing eval, a review that blocks, a
merge gate that rejects) rather than the routine choosing to abort.
Treat a refusal the same as an abort: close the PR if one is open,
delete the branch locally and on the remote, and append a
`refused=<gate>` line to the run log (e.g. `refused=post-evals` or
`refused=merge`) naming which step refused. Never retry past a refusal
in the same run and never relax the gate that refused.

Append a timestamped per-stage line to the run log after each gate step
above (fetch/branch, evals frozen, edit made, manifest check, push,
review, post-review, post-evals, merge) — same convention as
`loop-retro-promotion`'s `promotion-runs.log`.

## 4. Run log and failure visibility

One append-only log at the config's `expectedArtifact.artifactPath`
(`run-{date}.log`), one line per stage per run, timestamped ISO8601. The
no-drift short-circuit (step 2) and every delivery stage (step 3) write
to this same file — it is both this routine's durable record of what
happened on a given night AND the artifact its `exists` gate checks,
mirroring `loop-retro-promotion`'s `promotion-runs.log` convention.

This routine keeps both of its config's shipped escalation channels
(`escalation: ["notification", "vault-note"]`) — nothing here replaces
or reduces them; this section only makes the failure path legible on
top of them. Every abort (step 4) or refusal (steps 5–9) does BOTH of
the following, not just one:

1. Writes its reason into the run-note (the `vault-note` escalation
   channel — same file the routine's normal green/red history already
   goes to).
2. Appends a durable, greppable marker line to this run log —
   `abort=<reason>` for a manifest-scope abort, `refused=<gate>` for a
   downstream gate refusal — so a later audit can `grep` every failed
   night across the whole log in one pass instead of re-reading each
   run-note individually.

Where a human should actually look, in order: the macOS notification
first (transient — easy to miss if you're away), then the vault-note
run history (one entry per run, human-readable), then this run log's
`abort=`/`refused=` lines (the fast, grep-able summary across many
nights). There is no dashboard alert and no PR comment for a failed
run — notification + vault-note are the entire failure-visibility
surface for this routine, same as every other routine in this file.

## 5. Prohibitions

This pipeline writes ONLY git-tracked documentation `.md` files. It
NEVER edits: hook scripts, gate logic, anything under `scripts/`,
`install.sh`, its own `SKILL.md`, the routine config
(`~/.claude/coderails-dashboard.json` or
`examples/dashboard-config.json`), `.claude/settings.json`, or any code.

**This is mechanically enforced, not merely stated.** The
self-governance deny-list in step 4 is checked by the same manifest
assertion that rejects a non-`.md` path — an edit to `skills/**/SKILL.md`
(including this file), `AGENTS.md`, `CLAUDE.md`, `docs/routines.md`, or
anything under `.claude/` aborts the run exactly like a code change
would, before push. It is not left to this prose alone to be honoured.
That said, be honest about the limit: this enforcement lives in the
skill's own prompt and runs inside `claude -p`, where `PreToolUse` hooks
do not fire — it reduces the risk of self-governance drift, it does not
eliminate it the way a hook-level or server-side check would. See the
security warning in `docs/routines.md` for the same caveat stated for
the reader operating this routine.

It never relaxes, reorders, or skips a gate. It merges ONLY via
`/coderails:merge` — never raw `gh pr merge`: `PreToolUse` hooks do not
fire in this headless execution mode (`claude -p`), so
`test_gate`/`enforce_pr_workflow` do not protect this routine's runs
either — `scripts/merge.sh`'s own script-internal artifact gates are the
merge rail.

It must NEVER edit `INSTALLATION.md`'s workflow-tools/claude-guardrails
migration section — those names document live installer behaviour
(`install.sh:232` hard-exits on them) and are not documentation drift for
this routine to "fix."

It never "fixes" a doc to match code it has not read — no guessing. If
the audit is uncertain, it reports rather than edits.
