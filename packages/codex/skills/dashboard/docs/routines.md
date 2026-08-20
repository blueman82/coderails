# Native Codex routines

Native Codex routine execution is on-demand only. This package does not bundle
a native scheduler, background service, or installer for scheduled jobs.

## Run a declared routine

Routine buttons use the same declarations as the dashboard command deck. Copy
`../examples/dashboard-config.json` to
`~/.codex/coderails-dashboard.json`, replace its placeholder paths, launch the
dashboard with `$coderails-codex:dashboard`, and press the declared button.

`read-only` runs use Codex's read-only sandbox. `auto` runs use the
`workspace-write` sandbox so Codex can edit files only in the selected working
directory, with network access forced off. Network delivery is not part of an
unattended dashboard run.

## Run workflow-audit manually

The example config keeps `workflow-audit-weekly` as a manual button. It mines
the last seven days and writes proposals to the dashboard queue for human
approval. Despite the historical name, nothing runs it weekly automatically.

You can also invoke it directly in Codex:

```text
Use $coderails-codex:workflow-audit in QUEUE-MODE over the last 7 days (--days 7).
Write proposal verdicts to the dashboard queue only; do not create skills in this run.
```

After reviewing a queued proposal in ASSISTANT.LINK, Approve starts the bundled
local builder. The builder edits and tests inside a `workspace-write` worktree,
then stops at `ready_for_review`. A person reviews those local changes and
handles commit, push, and pull-request delivery separately.

## Routine results

The dashboard records run output under
`~/.codex/coderails-dashboard/runs/`. Declared artifact checks and failure
notices run when an on-demand queue sweep processes the intent. They do not
imply that a background scheduler exists.
