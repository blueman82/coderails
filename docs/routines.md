# Verified routines

A **scheduled skill run** uses a `RoutineDef` entry. For success, the runner checks that the artifact is available, recent, and satisfies a predicate. It also checks for exit 0.
There are five examples. The nightly examples are `wiki-lint` and `sync-docs-nightly`.
The weekly examples are `memory-consolidation-weekly`, `loop-retro-promotion-weekly`, and `workflow-audit-weekly`.

For the `Intent`, queue lifecycle, and `RoutineDef` contract, see the [dashboard library README](../skills/dashboard/lib/README.md).
Read the [warning on permissions](#security-warning-bypass-profile-routines-run-outside-the-hook-safety-net) before you configure a scheduled run that writes files or runs commands.

## Prerequisites for a cold clone

Install dependencies from the repository root:

```bash
(cd skills/dashboard/lib && npm install)
(cd skills/dashboard/runner && npm install)
```

Git ignores the two `node_modules` directories. A clone does not contain them.
Launchd imports `src/*.ts` with Node 24 type stripping, without a build step.
A run with a missing dependency reports `MODULE_NOT_FOUND`.

The Claude dashboard uses `~/.claude/coderails-dashboard/`. The `runner/src/main.ts` and `seedMain.ts` scripts use `$HOME` to get this path.
For tests, set `HOME` to a temporary directory, as in `HOME=/tmp/fake-home node src/main.ts`. There is no flag or config setting for this path.

The runner looks for Claude in `KNOWN_CLAUDE_PATHS` in `skills/dashboard/runner/src/exec.ts`.
Launchd supplies no `PATH`. The scripts and plists use absolute paths.
For a different machine, add its Claude path to the list. Use the configuration for that machine.

Codex has its own scripts, run specs, runner, and skills in `packages/codex/`. The default Codex docs-sync log is in `~/.codex/`.

## Architecture: intent producers, one runner

Buttons and scheduled runs put JSON intents in `~/.claude/coderails-dashboard/queue/`. Producers write intents and the runner runs them.
The Obsidian plugin runs commands directly. See the library README. New producers must use the queue.

- Obsidian, web, and CLI producers write `{button, input?, requestedAt, source: "obsidian" | "web" | "cli"}`.

- `seedMain.ts` calls `seed.ts:seedDueRoutines` to write `{button, requestedAt, source: "scheduler"}` for each due run.

- The runner claims `queue/<id>.json` by moving it atomically to `processing/<id>.json`. It uses the shared `buildArgv` and button settings to start and record the run.
  For a `RoutineDef` button, it checks the artifact and escalates errors. For other buttons, it checks the exit code. The seeder sets the schedule.

## Defining a routine

Put `routines` at the same level as `buttons` in `~/.claude/coderails-dashboard.json`. The code in `skills/dashboard/lib/src/config.ts` checks the configuration.
Each machine has its own file, external to Git. The runner does not read the hand-maintained [example config](../examples/dashboard-config.json).
To use an example, copy its `buttons` and `routines` entries into the local config. Replace each absolute `cwd` and `artifactPath` with its local value.

```json
{
  "name": "wiki-lint",
  "label": "Wiki Lint (nightly)",
  "buttonRef": "wiki-lint",
  "cadence": "nightly",
  "expectedArtifact": {
    "artifactPath": "{vault}/log.md",
    "maxAgeSeconds": 129600,
    "predicate": { "kind": "contains", "marker": "## [{date}] lint" }
  },
  "escalation": ["notification", "vault-note"]
}
```

- `name` identifies the `RoutineDef` entry. The seeder and runner find the button with `buttonRef ?? name`. Set `buttonRef` if the names differ.

- Set `skillCommand` or `buttonRef`. Do not set the two fields together. All five examples use `buttonRef` to use the button's command, `cwd`, and permission setting.

- `foreignSkillPath` is an optional absolute path to an external skill. If the path has no file, the runner reports `skill-missing` before it starts the child. The five examples omit it.

- The seeder accepts `nightly` (20 hours) or `weekly` (6.5 days). The shorter intervals let a late run use the next calendar run. An unknown value causes `runner-error` for that entry. The other runs continue.

- `expectedArtifact.artifactPath` accepts `{date}` (`YYYY-MM-DD`), `{runId}`, and `{vault}` (first `wikiPaths` entry). Use trusted configuration for paths. Do not use untrusted values from a run or intent.

- Set `maxAgeSeconds` above the run interval. The nightly example uses 129600 (36 hours). Weekly examples use 691200 (8 days).

- `escalation` can contain `notification`, `vault-note`, or the two together. All five examples use the two together. With `[]`, only run records show errors. There is no other off switch and no deduplication.

All predicates check for an artifact with a timestamp in the permitted age range:

| Predicate | Other requirement |
|---|---|
| `{kind: "exists"}` | None. |
| `{kind: "contains", marker}` | The artifact contains the marker after `{date}`, `{runId}`, and `{vault}` substitution. |
| `{kind: "last-marker", success, failures}` | The last terminal marker contains `success`. A `failures` marker or a missing terminal marker gives an error. |
| `{kind: "json-field", path, value}` | The artifact parses as JSON and the dotted path equals `value`. |

Use `last-marker` for append-only logs. With `contains`, a marker from a previous success can hide a subsequent error.
The runner requires exit 0 and a success result from `checkArtifact()`.

## `workflow-audit-weekly`: transcript mining with queue-mode proposals

The scheduled run reads seven days of transcripts. It groups recurring tool-use patterns and writes `propose` verdicts to the dashboard approval queue.
Queue mode is mandatory. The session does not write skills. The owner must select Approve for each proposal.

The `~/.claude/coderails-dashboard/routines/workflow-audit/run-{date}.md` note records `proposals_written: <N>`.
The gate checks for `## [{date}] workflow-audit complete`. The run adds this marker only after a clean run with `proposals_written == proposals_attempted`.

A crash or queue write error prevents the marker. A run with no proposals to write can succeed. Keep the proposal threshold.
The 691200-second freshness window gives a late weekly run eight days to catch up.

## `sync-docs-nightly`: self-merging documentation drift fixer

`skills/docs-sync/SKILL.md` uses `/coderails:sync-docs` to compare Git-indexed docs with source.
If the audit finds no drift, the run logs `no-drift` and stops before it changes the repository, opens a branch, or opens a PR.
For drift, freeze task evals before edits. Then check the manifest, push, do a code inspection, post its result, post evals, and merge.
The run can merge its own PR without a human step. Publication, authority, or integrity checks can refuse it.

The manifest uses `git diff origin/main...HEAD --name-status`. The three dots exclude changes that a sibling PR merged on the base since this branch began.
The changes must be Git-indexed `.md` files. For a path external to that set, abort, close the open PR if there is one, and clean up the current local branch.
The run keeps the remote branch.

The denylist also blocks `skills/**/SKILL.md` (this includes `skills/docs-sync/SKILL.md`), `AGENTS.md`, `CLAUDE.md`, `docs/routines.md`, and `.claude/**`.
Report drift on these paths. Use a different workflow to change them.
The `routine_run.py` manifest check uses `policy/docs-sync.policy.json`. The Codex policy matches it byte for byte and also names `.claude/**` rather than `.codex/**`.

The same user can edit these controls. They decrease the risk that a run changes its own rules. The run and controls have the same user privileges.

Notifications and vault notes are on. Check the macOS notification, the `dashboard-runs/sync-docs.md` history, and the `abort=` or `refused=` lines in the run log.
The note and the log give the cause. There is no dashboard alert or PR comment for the error.

The previous `sync-docs-weekly` configuration accepted an absolute, nonempty `foreignSkillPath` that pointed to a missing file. The runner checks the file before launch.
In July 2026, a red `skill-missing` vault note followed an earlier green run. Repair took nine days.

That incident explains these reporting rules. Check the current install independently. The current skill ships in the repository and does not use `foreignSkillPath`.

## `loop-retro-promotion-weekly`: a dormant-by-default routine

The run finds its repo-key directory and calls `routine_run.py begin` to write a provisional `run_incomplete` row.
Before it reads retros or makes a branch or edits, it runs `scripts/lib/lessons.py predicate` with its native session ID.
The predicate checks for a minimum of ten unique completed retros with owned `progress.json` files and matching source hashes.
It also checks `orders.json` for one entry with a recurrence and one entry with `status: decayed`.

A refused read (exit 2) ends with `RR abort predicate_refused`. A degraded read (exit 3) ends with `predicate_degraded`.
Malformed output or a different unexpected result ends with `predicate_unavailable`.

These results are unknown and cannot give dormant success. Schema 3 history needs the matching `retro_check` validator.
Use the typed predicate to check the condition. File counts and generated Markdown views do not supply the same checks.

If the predicate can check the data but the requirements do not hold, append the predicate line to `promotion-runs.log` and run `RR finish no_drift`.
It writes terminal `run=ok`. The run opens no branch or PR and runs no publication gate. This is the expected result on most runs.

If the predicate can check the data and the requirements hold, `run_incomplete` stays in the log while the run reads, writes, and publishes.
A stopped run stays red until all gates succeed and `RR finish ok` adds the terminal success row.
Promotion can change only `skills/agentic-loop/learned-failure-modes.md`. The manifest, code inspection, and merge gates check this scope.
The predicate checks the source conditions. Check the terminal result for a complete promotion run.

## Routine state machine and event log (`docs-sync`, `loop-retro-promotion`)

The two scheduled runs use `scripts/routine_run.py`. The Codex copy is in `packages/codex/scripts/`. The script runs without hooks.
Each `routines/*.json` spec sets policy, log path, cleanup, the permitted `reason_code` values, and the step sequence.
The sequence is `fetch_branch`, `evals_frozen`, `edit_made`, `manifest_check`, `push`, `review`, `post_review`, `post_evals`, `merge`.
See the provider's skill for its command chain.

Commands are `begin`, `stage NAME`, `run-gate STAGE -- ARGV`, `abort CODE`, `refuse GATE`, and `finish ok|no_drift`.
Docs-sync defaults to `~/.claude/coderails-dashboard/routines/docs-sync/run-{date}.log`. Codex defaults to `~/.codex/coderails-dashboard/routines/docs-sync/run-{date}.log`.
For promotion, use `--log <repo-key-dir>/promotion-runs.log`.
The runner uses `docs-sync` for `sync-docs-nightly` and `loop-retro-promotion` for `loop-retro-promotion-weekly` in JSONL records and checks of the run data.

- `begin` writes the run data and a provisional `run_incomplete` row with `abort=incomplete-run`. This distinguishes a run that stops before its terminal step from one that did not start.
  For `finish ok`, complete each step. For `finish no_drift`, start no steps. Only a finish that meets these conditions writes `run_ok`.

- The run aborts with `stage_out_of_order` for a duplicate step, a skipped step, or a step out of sequence.
  For gate steps, use `run-gate`.

- `stage manifest_check` runs `scripts/diff_manifest.py --policy <spec policy>`. The run aborts if the manifest violates policy.
  With a dirty worktree or files unknown to Git, it reports `dirty_worktree`. `run-gate push` checks the manifest again before it runs the command.

- Gate arguments must name the configured script in the provider's shipped `scripts/` directory. Use the script directly or with the active Python interpreter.
  Use `post` for posting gates. A script of the same name in a different directory, or a help-only or validation-only command, gives `gate_argv_not_allowed`.

- A nonzero gate exit gives `run_refused` for that gate. This includes a command that cannot start (`gate_spawn_failed` on stderr).
  At merge, the script first saves the PR number and head SHA. If a live check gives `MERGED`, use that result in preference to the exit code.

- On `abort`, `refuse`, or a check error, cleanup runs one time. It uses Git and `gh` to close the PR and delete the current local branch.
  Cleanup keeps remote and default branches and does not use `rm`. It runs only on the branch from `fetch_branch`.
  It does not change a different checkout. A cleanup error prints `cleanup_failed: <step>`. Cleanup stays on the current branch with a dirty tree.

- Without `--new`, `begin` refuses an open run across dates. It also refuses an abort or refusal on the same day.
  For explicit replacement, it first closes an open earlier ID and log with `run_abort incomplete-run`. Then it starts today's run in today's log.
  The run data includes the name. A different `RoutineDef` entry gives `routine_mismatch`.
  The log template identifies the run data. `begin` pins the paths, so a run across midnight keeps its log.

- The runner supplies a 16-character ID to the child in `CODERAILS_ROUTINE_RUN_ID`. `begin` checks it. Manual `begin` without it makes a 12-character ID.
  Subsequent step, gate, and terminal commands check the same child ID. For manual commands, keep `CODERAILS_ROUTINE_RUN_ID` unset.
  `begin --new` can replace an earlier run. The runner accepts terminal rows only for its own ID.
  Manual 12-character runs have no child-token ownership check. Access to log and run data paths has the same-user boundary.

- After the merge command, a PR fetch error or different head keeps the run red and blocks cleanup. A confirmed merge blocks abort and cleanup.
  If the run does not finish after a confirmed merge, the row is `run_incomplete merged_incomplete`. The human log says `incomplete=merged`.
  If that log write did not complete, the runner reads its saved record of the merge command. It writes `run_incomplete merge_state_unknown` and `incomplete=merge-unknown`.
  Check the PR and its head before recovery. Only `finish ok` after all steps records success.

- Updates to the run data use atomic replacement. One flock spans the read, handler, child gate, and cleanup. The writer takes the JSONL flock while it holds the first flock.

`routine_log.py emit --log PATH --run-id ID --routine NAME --stage S --outcome O [--reason-code C]` holds its log lock while it writes two records.
It appends the JSONL object `{v,ts,run_id,routine,stage,outcome,reason_code}` and the human marker.
Outcomes are `stage_ok`, `run_ok`, `run_abort`, `run_refused`, and `run_incomplete`. Each `RoutineDef` entry has a set of permitted `reason_code` values.
An unknown outcome or code gives exit 2 and adds no record.

Human markers are `run=ok`, `abort=<code>`, `refused=<gate>`, `abort=incomplete-run`, `incomplete=merged`, `incomplete=merge-unknown`, and `stage=<name>`.
The human log includes `run_id=<id>`. For JSONL success, the runner also checks for a matching human `run=ok`.
For a `merged_incomplete` run, the runner reads JSONL and keeps the run red.

The writer opens the two files before it appends records. A write error gives `log_unwritable`. The run stays at the same step and does not finish.
A write or close error or a crash can prevent one of the records. After a write error, check the two logs and saved run data.

After each child exit, `sweep.ts` and `timeoutMarker.ts` check JSONL for a terminal `run_ok`, `run_abort`, or `run_refused` row.
If there is no terminal row, the runner appends `run_abort runner_exit_no_terminal` and the human `abort=` marker.
This detects an agent that skips the commands in `routine_run.py`. A run that did start also has a provisional row. The runner cannot make the agent run those commands.

The runner saves the JSONL prefix before it starts the child. It accepts appended rows only if those initial bytes match.
A changed prefix, read or write error, missing terminal row, abort, or refusal blocks success. A previous human `run=ok` cannot make this run succeed.
The runner pins the artifact date and context for the invocation. It checks its own run ID, so a different child cannot make this run green.

A reader that uses `last-marker` directly on the human log does not check JSONL or run ID. If a human log append does not complete, that reader can see a previous green marker.

A `merged_incomplete` row stays red without a fallback abort. Fallback appends do not use the Python log lock or clean up branches or PRs.
This limits concurrent producers. Editable run data or logs, an alternative `--log`, and manual `routine_log.py emit` can let the same user forge success.
This is a cooperating-agent safeguard.

There is no off switch for these checks. The runner records `routine/<outcome>/<reason_code>` in telemetry and counters for observation only.
See [workflow gates measurement](workflow-gates-measurement.md) and the [runbook entry](RUNBOOK.md#a-routine-run-ended-incomplete-aborted-or-refused).
The runner is an integrity-review policy path. `GitHub Actions` checks the current head SHA before merge. The required rule must be active on `main`.

## Install / uninstall

`launchd/install_routines.py` installs two Launchd services. You can run it again to apply the same settings.

| Launchd service | Schedule and operation |
|---|---|
| `com.coderails.routine-sweeper.calendar` | At 03:00 each day, `runner/bin/seed_and_sweep.py` adds due intents, then runs the queue sweeper. It runs the sweeper after a seed error. |
| `com.coderails.routine-sweeper.watch` | When a queue file changes, `runner/bin/sweeper.py` runs the queue sweeper without seeding. |

The two scripts are in `skills/dashboard/`. Use these commands:

```bash
launchd/install_routines.py
launchd/uninstall_routines.py
```

Install copies the plists to `~/Library/LaunchAgents/` and bootstraps them in `gui/$UID`. Uninstall boots out the labels and removes the copies.
After a reboot, Launchd starts only the installed copies. A bootstrap of a repo-path plist lasts until logout or reboot. This caused an error in the July 2026 rollout.

The plists contain this machine's checkout and log paths and `/opt/homebrew/bin/node`. Adjust these paths for a different checkout, user, or machine.
Use absolute paths because Launchd supplies no `PATH`. The historical check was `launchctl print gui/$UID`.

## Where to look when something fails

1. **`~/.claude/coderails-dashboard/routines/sweeper.log`** records stdout and stderr from the two services, scheduler errors, Node crashes, and seed errors.

2. **`~/.claude/coderails-dashboard/runs/runs.jsonl`** records button and scheduled run starts and finishes. Fields include `argv`, `cwd`, `startedAt`, `endedAt`, `exitCode`, and `outputPath`.
   The dashboard uses `readRuns()` to read this log. The runner supplies `outputPath` for stdout and stderr capture.
   The button endpoint is `skills/dashboard/app/src/app/api/run/route.ts`. `GET /api/run/output` supplies output to `COMMAND DECK`'s Run Output viewer.
   If there is no output, check sweeper output and vault notes.

3. **Vault notes** at `<first wikiPath>/dashboard-runs/<routine or button>.md` append `## [YYYY-MM-DD] run <id> — green|red` entries with results and causes.
   The runner's `writeRunNote` uses `type: routine-run`. Wiki ingest, lint, and page conventions exclude these notes.
   Runs from Obsidian write `<YYYY-MM-DD>-<button>.md` with `status: running|done|failed` and no type. Wiki procedures exclude those notes too.

4. **macOS notification** uses synchronous `osascript` with title `Routine failed: <routine name>` and body `<failure class>: <reason>`.
   Notifications are temporary. Vault notes and run records keep the history.

## Escalation taxonomy

The notification and note include `failureClass` and `reason` for each escalation.

| Error class | Cause |
|---|---|
| `skill-missing` | The path to the external skill has no file. The child did not start. |
| `claude-spawn-failed` | The runner cannot find the binary or start the child. An incorrect `cwd` can cause this. |
| `exec-error` | The child gives a nonzero exit or runs for more than 30 minutes. `reason` identifies a timeout. |
| `artifact-gate-failed` | The child exits 0 and the artifact does not satisfy its predicate, has an expired timestamp, or has no file. |
| `runner-error` | Runner bookkeeping error, unknown cadence, unresolved button, or recovery of work idle in `processing/` for 60 minutes. |

Escalation does not deduplicate notices. An invalid cadence or missing button gives a notice on each calendar run. These notices can have the same cause.

## Security warning: bypass-profile routines run outside the hook safety net

On July 7, 2026, a Claude `-p` probe saw `SessionStart`, `UserPromptSubmit`, and `Stop`. It saw no `PreToolUse`. A forced test-gate denial did not stop a commit.
That check describes the July run. Check the current install independently. Headless runs operate without `test_gate` and `enforce_pr_workflow` enforcement.

For `bypass`, `buildArgv` in `skills/dashboard/app/src/lib/argv.ts` uses `--dangerously-skip-permissions`. This setting has no tool allowlist.
For `read-only`, it uses `--allowedTools Read Grep Glob`. Use read-only unless the owner explicitly accepts writes and command execution.
Three examples use read-only. Docs-sync and retro-promotion use bypass.

These two scheduled runs use scripts to check the manifest, publication rules, and code inspection artifacts. The same-user limits above apply.
The standing July 15, 2026 decision leaves general branch protection off. Only the configured `integrity-review` ruleset can add a required check.

Check that it is active and use its required workflow. See [integrity gate](INTEGRITY-GATE.md). Check native Codex hook trust and installed behavior independently.

Workflow-audit's read-only run can write its note, count, and marker in `~/.claude/coderails-dashboard/routines/workflow-audit/`.
It can also write queue entries with D2 allowlisted fields in `~/.claude/coderails-dashboard/approvals/`.
The `scan_transcripts.py` script extracts structure only. Proposals do not contain full transcript content. Each proposal needs owner approval.

## See also

- [Dashboard library contract](../skills/dashboard/lib/README.md)
- [Memory-consolidation skill](../skills/memory-consolidation/SKILL.md)
- [Docs-sync skill](../skills/docs-sync/SKILL.md)
- [Loop-retro-promotion skill](../skills/loop-retro-promotion/SKILL.md)
- [All five examples](../examples/dashboard-config.json)
