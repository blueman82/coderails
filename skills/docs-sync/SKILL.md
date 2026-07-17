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
`README.md`, `AGENTS.md`, `CLAUDE.md`, and tracked files under `docs/`.
Before treating any `docs/*.md` file as in-scope, confirm it is actually
tracked and not gitignored:

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
4. **Assert `git diff origin/main...HEAD --name-only` (THREE-dot, not
   two) contains ONLY git-tracked `.md` files.** Two-dot compares against
   whatever `origin/main` happens to be at assertion time; if a sibling
   PR merges into `main` mid-run, that comparison base has moved and a
   two-dot diff can indict an otherwise-clean branch for files it never
   touched. Three-dot compares against the merge-base as of when this
   branch forked, which is the only comparison actually scoped to what
   *this* routine changed. If ANY non-`.md` path appears in that diff —
   anything under `hooks/`, `scripts/`, `skills/*/` other than a `.md`
   file, any `.sh`, `.json`, `.ts`, `.yaml` — **ABORT WITH CLEANUP**:
   close the PR if one was opened, delete the branch both locally and on
   the remote, and append an `abort=<reason>` line to the run log. Do not
   leave orphaned branches, PRs, or partial state. **ABORT, never
   warn-and-continue** — a non-`.md` path in the diff is a hard stop,
   not a warning to log and push anyway.
5. `/coderails:push`
6. `/pr-review-toolkit:review-pr <PR#>`
7. `/coderails:post-review <PR#>`
8. `/coderails:post-evals <PR#>`
9. `/coderails:merge`

Append a timestamped per-stage line to the run log after each gate step
above (fetch/branch, evals frozen, edit made, manifest check, push,
review, post-review, post-evals, merge) — same convention as
`loop-retro-promotion`'s `promotion-runs.log`.

## 4. Run log

One append-only log, one line per stage per run, timestamped ISO8601.
The no-drift short-circuit (step 2) and every delivery stage (step 3)
write to this same log — it is this routine's durable record of what
happened on a given night, mirroring `loop-retro-promotion`'s
`promotion-runs.log` convention.

## 5. Prohibitions

This pipeline writes ONLY git-tracked documentation `.md` files. It
NEVER edits: hook scripts, gate logic, anything under `scripts/`,
`install.sh`, its own `SKILL.md`, the routine config
(`~/.claude/coderails-dashboard.json` or
`examples/dashboard-config.json`), `.claude/settings.json`, or any code.

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
