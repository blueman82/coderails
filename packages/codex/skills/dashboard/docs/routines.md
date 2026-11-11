# Native Codex routines

Native Codex starts each run on demand. This package does not include
a native scheduler, background service, or installer for scheduled work.

## Run a declared routine

The dashboard command deck declarations define the buttons.

1. Copy `../examples/dashboard-config.json` to
   `~/.codex/coderails-dashboard.json`.
2. Replace the placeholder paths.
3. Launch the dashboard with `$coderails-codex:dashboard`.
4. Push the declared button.

`read-only` runs use Codex's read-only sandbox. `auto` runs use the `workspace-write` sandbox.

Codex can edit files only in the selected working
directory. Network access is off. An unattended dashboard run does not
send results through the network.

## Run workflow-audit manually

The example config keeps `workflow-audit-weekly` as a manual button. It mines
the last seven days. It writes proposals to the dashboard queue for human
approval. The name does not make it run each week.

You can also invoke it directly in Codex:

```text
Use $coderails-codex:workflow-audit in QUEUE-MODE over the last 7 days (--days 7).
Write proposal verdicts to the dashboard queue only; do not create skills in this run.
```

After you examine a queued proposal in ASSISTANT.LINK, Approve starts the local builder. The builder edits and tests in a `workspace-write` worktree.
It stops at `ready_for_review`. A person examines the local changes. That
person commits, pushes, and opens the PR.

## Routine results

The dashboard records run output in
`~/.codex/coderails-dashboard/runs/`. An on-demand queue sweep handles the intent, runs declared artifact checks,
and gives notices if checks fail. This package has no background scheduler.
