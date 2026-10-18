# Verified routines

A **routine** is a scheduled skill run whose artifact must exist, be fresh and
satisfy a predicate before the runner calls it complete. Exit 0 alone is insufficient.
Five examples ship: nightly `wiki-lint` and `sync-docs-nightly`; weekly
`memory-consolidation-weekly`, `loop-retro-promotion-weekly` and `workflow-audit-weekly`.

This is the operator guide. The exact `Intent`, queue lifecycle and `RoutineDef`
contract is in [the dashboard library README](../skills/dashboard/lib/README.md).
**Read the security warning before enabling routines that write or execute commands.**

## Prerequisites for a cold clone

Install both packages' dependencies from the repository root:

```bash
(cd skills/dashboard/lib && npm install)
(cd skills/dashboard/runner && npm install)
```

Both `node_modules` directories are gitignored; cloning does not populate them.
Launchd imports `src/*.ts` using Node 24's built-in type stripping, without a build
step. Missing dependencies surface as `MODULE_NOT_FOUND` when a routine runs.

The Claude dashboard data directory is `~/.claude/coderails-dashboard/`, derived
from `$HOME` by `runner/src/main.ts` and `seedMain.ts`. No flag/config relocates it.
Redirecting `HOME` is the documented test/sandbox lever for that dashboard state
(for example, `HOME=/tmp/fake-home node src/main.ts`).

The Claude binary is resolved from `KNOWN_CLAUDE_PATHS` in
`skills/dashboard/runner/src/exec.ts`, rather than `$PATH`. Launchd supplies no
`PATH`; its scripts/plists use absolute paths. On another machine, update that
candidate list to include its Claude installation. The configuration is deliberately
machine-specific. The independent Codex scripts, routine specs, runner and skills
live under `packages/codex/`; docs-sync's Codex log default is under `~/.codex/`.

## Architecture: intent producers, one runner

Every button press or scheduled run starts as a JSON intent in
`~/.claude/coderails-dashboard/queue/`. Producers write intents; the runner executes.
The Obsidian plugin's interim direct-exec path is a documented exception in the
library README, and new producers must follow the queue contract.

- Obsidian/web/CLI write `{button, input?, requestedAt, source: "obsidian" | "web" | "cli"}`.
- `seedMain.ts` → `seed.ts:seedDueRoutines` writes
  `{button, requestedAt, source: "scheduler"}` for due routines.
- The runner atomically claims `queue/<id>.json` as `processing/<id>.json`, spawns
  through the shared `buildArgv`/profile mapping and records the run. When the
  button resolves to a `RoutineDef`, it checks the artifact and escalates failures.
  Other buttons gate on exit code. Cadence belongs to the seeder.

## Defining a routine

Put routines in `~/.claude/coderails-dashboard.json` beside `buttons`. Validation
is in `skills/dashboard/lib/src/config.ts`. This configuration is per-machine and
untracked. [examples/dashboard-config.json](../examples/dashboard-config.json) is a
reference copy maintained by hand; the runner does not read it. To enable an example,
copy its button/routine into the machine's config and replace every absolute
`cwd`/`artifactPath` with the correct local path.

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

- `name` identifies the routine. Seeder and runner resolve the button using
  `buttonRef ?? name`; specify `buttonRef` when the names differ.
- Choose exactly one of `skillCommand` and `buttonRef`. The latter reuses a
  button's command, cwd and profile; all five examples use it.
- Optional `foreignSkillPath` is an absolute external skill path. The runner
  checks existence before spawning and escalates `skill-missing` if absent.
  None of the five current examples need it.
- Seeder cadence is only `nightly` (due after 20 hours) or `weekly` (6.5 days).
  The shorter thresholds let late runs catch the next calendar tick. Unknown
  cadence escalates `runner-error` for that routine while other routines continue.
- `expectedArtifact.artifactPath` supports `{date}` (`YYYY-MM-DD`), `{runId}`
  and `{vault}` (first `wikiPaths` entry). Paths are trusted configuration:
  **never template them from untrusted routine/intent content**.
- `maxAgeSeconds` must comfortably exceed cadence: the nightly example uses
  129600 (36 hours); weekly examples use 691200 (8 days).
- `escalation` selects `notification` and/or `vault-note`. Both are enabled in
  all five examples. An empty array leaves failure visible only in run records;
  there is no separate escalation-off switch or deduplication.

Artifact predicates all require a present, fresh artifact:

| Predicate | Additional requirement |
|---|---|
| `{kind: "exists"}` | None. |
| `{kind: "contains", marker}` | Contains the marker after date/runId/vault substitution. |
| `{kind: "last-marker", success, failures}` | The last terminal marker contains success; a failure marker or no terminal marker fails. |
| `{kind: "json-field", path, value}` | Parses as JSON and the dotted path equals value. |

Use `last-marker` for append-only run logs: whole-file `contains` could pass on
an earlier success surviving a later failure. A routine completes only when
`checkArtifact()` passes, even if its child exited 0.

## `workflow-audit-weekly`: transcript mining with queue-mode proposals

The routine mines seven days of transcripts, groups repeated tool-use patterns
and writes `propose` verdicts to the dashboard approval queue. **Queue mode is
mandatory**: no in-session skill creation; every proposal waits for the owner's
Approve click.

Its note, `~/.claude/coderails-dashboard/routines/workflow-audit/run-{date}.md`,
records `proposals_written: <N>`. The gate checks
`## [{date}] workflow-audit complete`, emitted only after clean completion with
`proposals_written == proposals_attempted`. A crash or failed queue write omits
the marker and fails. Zero attempted/written proposals is a green completed run;
it is expected in a healthy workflow, not a reason to lower the proposal threshold.
The 691200-second freshness window gives late weekly runs eight-day catch-up grace.

## `sync-docs-nightly`: self-merging documentation drift fixer

`skills/docs-sync/SKILL.md` invokes the `/coderails:sync-docs` audit against
tracked documentation and actual source. No drift means `no-drift`, no branch
and no PR before changing Git state. Drift triggers the complete delivery chain:
freeze task evals before editing, check the manifest, push, review, post review,
post evals and merge. The routine's intended flow merges its own PR without a
human step; configured publication/authority/integrity checks can still refuse it.

The manifest uses `git diff origin/main...HEAD --name-status`: three dots avoid
treating a sibling PR's intervening merge as this branch's changes. Changes must
be git-tracked `.md` files. Any other path (hooks, scripts, settings or code)
aborts by closing any opened PR and cleaning up the current local branch; the
remote branch stays intact.

The self-governance deny-list also rejects `skills/**/SKILL.md` (including this
routine), `AGENTS.md`, `CLAUDE.md`, `docs/routines.md` and `.claude/**`.
Report drift there; **do not fix it through this routine**. The list is data in
`policy/docs-sync.policy.json`, enforced by `routine_run.py`'s manifest check.
The Codex policy is a byte mirror and also names `.claude/**`, not `.codex/**`.
These same-user editable controls reduce self-authored governance risk without
providing an independent security boundary.

Both notification and vault-note escalation remain enabled. Look at the transient
macOS notification, `dashboard-runs/sync-docs.md` history, then the routine log's
`abort=`/`refused=` lines. Aborts/refusals retain their reason in the note and
log; there is no separate dashboard alert or failed-run PR comment.

This replaces `sync-docs-weekly`, whose nonexistent external skill path still
passed config validation (absolute/nonempty is checked there; existence is checked
by the runner). The July 2026 rollout recorded a red `skill-missing` vault note
after an earlier green run, then nine days before repair. That historical incident
explains the visibility rules; it is not evidence of current installed behavior.
The current skill ships in-repo and needs no `foreignSkillPath`.

## `loop-retro-promotion-weekly`: a dormant-by-default routine

Before doing anything else, `skills/loop-retro-promotion/SKILL.md` checks:

1. At least ten `retro.json` files under the repo-key directory.
2. A `standing-orders.md` entry with `last_recurred` different from `created`.
3. An entry in `standing-orders-decayed.md`.

Until all three hold, append
`<ISO8601> predicate=unmet retros=<n> lifecycle=<0|1> decay=<0|1>` to
`promotion-runs.log`, finish with `run=ok` and stop without a branch, PR or gate
chain. Dormancy is a successful steady state and must not cause weekly escalation.

The met path calls `routine_run.py begin` before mining/drafting/delivery.
Its provisional `run_incomplete`/derived `abort=incomplete-run` makes an early
death red. The append-only log uses `last-marker` with success `run=ok` and
failures `abort=`, `delivery=started`; the latter supports pre-state-machine logs.

Promotion may change exactly `skills/agentic-loop/learned-failure-modes.md`;
otherwise abort with cleanup. Its merge rail is the manifest check,
`/pr-review-toolkit:review-pr` and `scripts/merge.py`'s internal artifact gates.
Like docs-sync, its button uses `bypass`; the security limits below apply.

A July 2026 snapshot contained only a predicate-unmet line
(`2026-07-12T23:32:06Z predicate=unmet retros=14 lifecycle=1 decay=0`), predating
the terminal-marker change. It did not prove a live full promotion chain.
That snapshot must not be treated as current production validation.

## Routine state machine and event log (`docs-sync`, `loop-retro-promotion`)

Both delivery routines use `scripts/routine_run.py` (independent Codex copy:
`packages/codex/scripts/`). The script needs no hooks. Each `routines/*.json`
spec supplies policy, log path, cleanup, closed reason codes and ordered stages:
`fetch_branch`, `evals_frozen`, `edit_made`, `manifest_check`, `push`, `review`,
`post_review`, `post_evals`, `merge`. Use the provider's SKILL for the exact chain.

Commands are `begin`, `stage NAME`, `run-gate STAGE -- ARGV`, `abort CODE`,
`refuse GATE` and `finish ok|no_drift`. Docs-sync's default is
`~/.claude/coderails-dashboard/routines/docs-sync/run-{date}.log` (Codex:
`~/.codex/coderails-dashboard/routines/docs-sync/run-{date}.log`).
Promotion requires `--log <repo-key-dir>/promotion-runs.log`.

- `begin` writes state and a provisional `run_incomplete` row, deriving
  `abort=incomplete-run`. A mid-sequence exit is red and distinguishable from
  never-started. `finish ok` requires every stage; `finish no_drift` requires
  none started. Only a valid finish emits `run_ok`.
- Stage order is strict: a repeated, skipped or out-of-order stage aborts with
  `stage_out_of_order`. Gate stages must use `run-gate`.
- `stage manifest_check` executes `scripts/diff_manifest.py --policy <spec policy>`.
  Violations abort; dirty/untracked work fails with `dirty_worktree`.
  `run-gate push` rechecks the manifest before executing its command.
- Gate argv must resolve to the configured script under the provider's shipped
  `scripts/` directory, directly or through the active Python interpreter.
  Same-basename files elsewhere are refused with `gate_argv_not_allowed`.
- A nonzero gate exit becomes `run_refused` for that gate, including a command
  that cannot spawn (`gate_spawn_failed` on stderr).
- `abort`, `refuse` and failed checks clean up once using Git/gh: close the PR
  and delete the current local branch, never a remote or default branch. No
  `rm`. Cleanup proceeds only while still on the branch recorded at
  `fetch_branch`; a changed checkout is left untouched. Failed cleanup prints
  `cleanup_failed: <step>`; a dirty tree is not force-switched.
- `begin` refuses an open run even across midnight, or a same-day abort/refusal,
  unless `--new`. Explicit replacement first closes an open previous id/log
  with `run_abort incomplete-run`, then starts today's run in today's log.
  State includes the routine name; another routine is refused with
  `routine_mismatch`. State is keyed by the log template, with paths pinned
  at begin so a run crossing midnight keeps its log.
- State uses atomic replacement. A state flock covers load/handler/child gate/
  cleanup; the separate JSONL flock is acquired inside it, never in reverse.

`routine_log.py emit --log PATH --run-id ID --routine NAME --stage S --outcome O
[--reason-code C]` appends JSONL
`{v,ts,run_id,routine,stage,outcome,reason_code}` and a derived human-log marker
under its log lock. Outcomes are `stage_ok`, `run_ok`, `run_abort`,
`run_refused`, `run_incomplete`; reason codes are closed per routine. Unknown
outcomes/codes exit 2 and append nothing. The human marker is `run=ok`,
`abort=<code>`, `refused=<gate>`, `abort=incomplete-run` or `stage=<name>`,
so the existing last-marker predicate is unchanged. Both files open before either
append. A failed write returns `log_unwritable` without advancing/ending state.
The files are **not a transaction**: write/close errors or a crash can leave
partial output. Inspect both logs and persisted state after a write error.

After a child exit, including exit 0, `sweep.ts`/`timeoutMarker.ts` check JSONL
for a terminal `run_ok`, `run_abort` or `run_refused` row. Without one they
append `run_abort runner_exit_no_terminal` and its human `abort=` marker.
An agent that never calls the state machine is caught by the runner check;
a begun run also has its provisional row. Invocation itself is not forced.

The runner captures the existing JSONL bytes before child launch and accepts
only appended rows with that prefix intact. A changed prefix, read/write error,
missing terminal, abort or refusal returns failed evidence and cannot pass via
an old human `run=ok`. It pins the artifact date/context for that invocation.
Among new rows it chooses the latest run id, falling back to its own id; it does
not hand an id to the child. Fallback appends do not take the Python log lock or
perform branch/PR cleanup. Concurrent producers remain an integration limit.
An editable state/log, redirected `--log`, or manual `routine_log.py emit` can
forge success under the same user. This is a cooperating-agent safeguard.

There is no separate routine-state off switch. Events emit non-authoritative
`routine/<outcome>/<reason_code>` trace/counter rows; see
[workflow-gates-measurement.md](workflow-gates-measurement.md) and the RUNBOOK
entry “A routine run ended incomplete, aborted or refused.” The runner is an
integrity-daemon policy path; daemon-attested runner changes need a human merge.

## Install / uninstall

Two jobs are managed by the idempotent `launchd/install_routines.py`:

| Job | Trigger and action |
|---|---|
| `com.coderails.routine-sweeper.calendar` | Daily 03:00; `runner/bin/seed_and_sweep.py` seeds due intents then sweeps. Seed failure never prevents sweeping queued work. |
| `com.coderails.routine-sweeper.watch` | Queue-directory writes; `runner/bin/sweeper.py` sweeps without seeding. |

Both bin paths are under `skills/dashboard/`. Operator commands:

```bash
launchd/install_routines.py
launchd/uninstall_routines.py
```

Install copies plists to `~/Library/LaunchAgents/` and bootstraps those copies
in `gui/$UID`; uninstall boots out the labels and removes the copies. Launchd
auto-loads only those installed copies after reboot. Bootstrapping a repo-path
plist lasts only until logout/reboot; the July 2026 rollout exposed this failure.

Plists embed this machine's checkout/log paths and `/opt/homebrew/bin/node`.
Edit them for another checkout/user/machine. Launchd has no `PATH` (the historical
check was `launchctl print gui/$UID`), so the absolute paths are required.

## Where to look when something fails

1. **`~/.claude/coderails-dashboard/routines/sweeper.log`**: both plists'
   stdout/stderr, scheduler failures, Node crashes and seed failures.
2. **`~/.claude/coderails-dashboard/runs/runs.jsonl`**: start/finish records across
   buttons and routines with argv, cwd, `startedAt`, `endedAt`, `exitCode` and
   `outputPath`; consumed by `readRuns()` and the dashboard. The runner passes
   `outputPath` to execution for stdout/stderr capture. The dashboard button
   endpoint is `skills/dashboard/app/src/app/api/run/route.ts`, and
   `GET /api/run/output` serves output to COMMAND DECK's Run Output viewer.
   Missing/failed capture still requires checking sweeper output and vault notes.
3. **Vault notes**: `<first wikiPath>/dashboard-runs/<routine or button>.md`,
   append-only `## [YYYY-MM-DD] run <id> — green|red` entries, including success
   and failure reasons. The runner's `writeRunNote` uses `type: routine-run`;
   these are operational output, excluded from wiki ingest/lint/page conventions.
   Obsidian direct execution instead writes `<YYYY-MM-DD>-<button>.md` with
   `status: running|done|failed` and no type. Treat both forms as non-wiki.
4. **macOS notification**: synchronous `osascript`, title
   `Routine failed: <routine name>`, body `<failure class>: <reason>`.
   Notifications are transient; notes/run records provide durable history.

## Escalation taxonomy

Every escalation carries `failureClass` and `reason` in notification and note.

| Failure class | Trigger |
|---|---|
| `skill-missing` | Referenced external skill is absent; child has not spawned. |
| `claude-spawn-failed` | No binary or failed spawn, including bad cwd. |
| `exec-error` | Spawned child exits nonzero or exceeds the 30-minute timeout; timeout is explicit in reason. |
| `artifact-gate-failed` | Child exits 0 but artifact is missing, stale or fails its predicate. |
| `runner-error` | Runner bookkeeping, unknown cadence, unresolved button, or recovery of processing work abandoned for 60 minutes. |

Escalation has no deduplication. Bad cadence/dangling buttons are reported on every
calendar fire; do not mistake repeated notices for distinct root causes.

## Security warning: bypass-profile routines run outside the hook safety net

The July 7, 2026 Claude `-p` probe observed `SessionStart`,
`UserPromptSubmit` and `Stop`, but no `PreToolUse`: a forced test-gate denial
did not stop a commit. This is historical evidence, not a fresh activation check.
Consequently the headless contract does not rely on `test_gate` or
`enforce_pr_workflow` to protect routine actions.

`bypass` selects `--dangerously-skip-permissions` through `buildArgv` in
`skills/dashboard/app/src/lib/argv.ts`. It has no tool allowlist; `read-only`
uses `--allowedTools Read Grep Glob`. **Ship read-only routines unless writing
and execution have been explicitly accepted.** Three examples are read-only;
docs-sync and retro-promotion are the two deliberate bypass exceptions.

Their merge rail is the scripted manifest/publication checks and review artifacts,
subject to the same-user limits above. General branch protection remains disabled
by the standing July 15, 2026 decision. The separate configured `integrity-review`
mechanism/ruleset is the sole opt-in exception; do not assume it is installed or
replace it with another route. See [INTEGRITY-GATE.md](INTEGRITY-GATE.md).
Native Codex hook trust and installed enforcement need their own verification.

Workflow-audit's read-only write surfaces are restricted to
`~/.claude/coderails-dashboard/routines/workflow-audit/` (note/count/marker) and
`~/.claude/coderails-dashboard/approvals/` (queue entries with D2-whitelisted fields).
`scan_transcripts.py` enforces structural extraction only: no full transcript
content in proposals. Each proposal still requires owner approval.

## See also

- [Dashboard library contract](../skills/dashboard/lib/README.md)
- [Memory-consolidation skill](../skills/memory-consolidation/SKILL.md)
- [Docs-sync skill](../skills/docs-sync/SKILL.md)
- [Loop-retro-promotion skill](../skills/loop-retro-promotion/SKILL.md)
- [All five example routines](../examples/dashboard-config.json)
