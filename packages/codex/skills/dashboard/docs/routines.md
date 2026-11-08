# Native Codex routines

Native Codex routine execution is on-demand only. This package does not bundle
a native scheduler, background service, or installer for scheduled jobs.

## Run a declared routine

Routine buttons use the dashboard command deck declarations.

1. Copy `../examples/dashboard-config.json` to
   `~/.codex/coderails-dashboard.json`.
2. Replace the placeholder paths.
3. Launch the dashboard with `$coderails-codex:dashboard`.
4. Press the declared button.

`read-only` runs use Codex's read-only sandbox. `auto` runs use the
`workspace-write` sandbox. Codex can edit files only in the selected working
directory. Network access is off. An unattended dashboard run does not
deliver results over the network.

## Run workflow-audit manually

The example config keeps `workflow-audit-weekly` as a manual button. It mines
the last seven days. It writes proposals to the dashboard queue for human
approval. The name does not make it run each week.

You can also invoke it directly in Codex:

```text
Use $coderails-codex:workflow-audit in QUEUE-MODE over the last 7 days (--days 7).
Write proposal verdicts to the dashboard queue only; do not create skills in this run.
```

After you review a queued proposal in ASSISTANT.LINK, Approve starts the
local builder. The builder edits and tests in a `workspace-write` worktree.
It stops at `ready_for_review`. A person reviews the local changes. That
person handles the commit, push, and pull request.

## Routine results

The dashboard records run output under
`~/.codex/coderails-dashboard/runs/`. Declared artifact checks and failure
notices run when an on-demand queue sweep processes the intent. They do not
imply that a background scheduler exists.
