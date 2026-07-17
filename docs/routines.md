# Verified routines

A **routine** is a scheduled skill run that isn't considered done just
because `claude` exited 0. It's done when a specific artifact exists,
is fresh enough, and satisfies a predicate — the **artifact gate**. Five
routines ship today: `wiki-lint` (nightly), `docs-sync-nightly` (nightly),
`memory-consolidation-weekly` (weekly), `loop-retro-promotion-weekly`
(weekly), `workflow-audit-weekly` (weekly).

This doc is the operator-facing guide: how the queue/runner architecture
works, how to define a routine, how to install/uninstall the scheduler,
and where to look when a routine fails silently instead of loudly. The
schema-level contract (the `Intent` type, the queue lifecycle, the
`RoutineDef`/config shape) lives in
[`skills/dashboard/lib/README.md`](../skills/dashboard/lib/README.md) —
read that first if you need the exact field-by-field contract; this doc
assumes it and focuses on operating the system.

**Read the security warning before enabling anything beyond the shipped
read-only routines.**

## Prerequisites for a cold clone

A fresh `git clone` is not runnable as-is — both TypeScript packages need
their dependencies installed before anything under `skills/dashboard/`
will import:

```bash
cd skills/dashboard/lib && npm install
cd skills/dashboard/runner && npm install
```

`node_modules` is gitignored in both packages and nothing in this repo
builds it for you; the launchd jobs described below import through it
directly (Node 24's built-in TypeScript type-stripping runs `src/*.ts`
with no build step), so a missing `npm install` in either package
surfaces as a `MODULE_NOT_FOUND` the first time a routine fires, not at
clone time.

The dashboard's data directory (`~/.claude/coderails-dashboard/` in every
path in this doc) is derived from `$HOME` at runtime (see `BASE_DIR` in
`skills/dashboard/runner/src/main.ts` and `seedMain.ts`) — there is no
flag or config option to relocate it. Redirecting `HOME` (e.g. `HOME=
/tmp/fake-home node src/main.ts`) is the supported lever for a sandboxed
or test run that shouldn't touch a real machine's dashboard state.

The `claude` binary itself is resolved from a short, hard-coded candidate
list (`KNOWN_CLAUDE_PATHS` in `skills/dashboard/runner/src/exec.ts`), not
`$PATH` — `launchd` invokes these jobs with no `PATH` set at all
(verified via `launchctl print gui/$UID`), so a bare `"claude"` command
string would fail to spawn under the scheduler even though it works fine
in an interactive shell. The candidate list is machine-specific by
design (documented as YAGNI in that file's own comments — no
multi-machine deployment exists yet to justify making it configurable):
on a different machine, edit `KNOWN_CLAUDE_PATHS` in
`skills/dashboard/runner/src/exec.ts` to add that machine's `claude`
install path.

## Architecture: intent producers, one runner

Every run — a dashboard button press, an Obsidian command, or a scheduled
routine — starts as an **intent**: a small JSON file dropped into
`~/.claude/coderails-dashboard/queue/`. Producers only ever write intent
files; they never execute `claude` directly as part of this contract (the
Obsidian plugin's current interim direct-exec behaviour is a known,
temporary exception documented in the lib README, not something new
producers should copy).

- **Obsidian / web / cli** — a button press writes `{ button, input?,
  requestedAt, source: "obsidian" | "web" | "cli" }`.
- **Scheduler (routines)** — the seed step (`seedMain.ts` →
  `seed.ts`'s `seedDueRoutines`) writes `{ button, requestedAt, source:
  "scheduler" }` for every routine that's due, using the same `Intent`
  shape and the same `queue/` directory as any other producer. Scheduled
  routines are intent **producers**, nothing more — the runner has no
  concept of cadence or "this came from a routine" once an intent is
  queued; it just executes buttons.
- **The runner** (`skills/dashboard/runner`) is the sole consumer. It
  claims an intent by atomically renaming it `queue/<id>.json` →
  `processing/<id>.json`, spawns `claude` via the one shared
  `buildArgv`/profile→flag mapping, records the run, and — only if the
  claimed intent's button resolves to a `RoutineDef` — evaluates that
  routine's artifact gate and escalates on failure. A plain button press
  with no matching routine just gates on exit code, same as before
  routines existed.

## Defining a routine

Routines live in the `routines` array of
`~/.claude/coderails-dashboard.json`, alongside the pre-existing
`buttons` array. A routine either names a `skillCommand` directly or
points at an existing button via `buttonRef` — never both — and every
routine needs `cadence`, `expectedArtifact`, and `escalation`. Full
validation rules are in `skills/dashboard/lib/src/config.ts`; this is the
shipped `wiki-lint` example from
[`examples/dashboard-config.json`](../examples/dashboard-config.json):

**`~/.claude/coderails-dashboard.json` is per-machine, `$HOME`-local, and
not checked into this repo** — every `cwd` and `artifactPath` in it is an
absolute path specific to the machine it lives on (same caveat as the
launchd plists and `KNOWN_CLAUDE_PATHS` above). `examples/dashboard-config.json`
is the checked-in reference copy, kept in sync by hand; it is not itself
read by anything. To arm a routine on a given machine, copy its
button+routine block from the example file into that machine's own
`~/.claude/coderails-dashboard.json` and rewrite every absolute path
(`cwd`, `artifactPath`) to match that machine's actual checkout
location — do not copy the example's paths verbatim.

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

Field by field:

- **`name`** — the routine's own identifier. If it differs from the
  button it drives, set `buttonRef` to the button's `name`; if it's the
  same string, `buttonRef` is optional (both the seeder and the runner
  resolve a routine to a button by `buttonRef ?? name`).
- **`skillCommand` / `buttonRef`** — exactly one. `buttonRef` reuses an
  existing button's `command`/`cwd`/`profile` (all five shipped
  routines do this). `foreignSkillPath` (optional) names an absolute
  path to a skill that lives outside this repo — the runner checks the
  path exists before spawning and escalates `skill-missing` if it
  doesn't, rather than spawning `claude` and letting it fail inside the
  sandbox. None of the five shipped example routines use it today: it
  used to be `sync-docs-weekly`'s way of pointing at a personal-plugin
  skill location, and that path had been silently broken for 9 days
  before anyone noticed — `foreignSkillPath` is validated only as a
  non-empty absolute string, never that it actually exists on disk, at
  config-load time. `docs-sync-nightly` (its replacement) moved the
  skill in-repo instead of fixing the stale path, which is why the field
  is unused now; it remains available for any routine whose skill
  genuinely lives outside this repo.
- **`cadence`** — only `"nightly"` or `"weekly"` are understood by the
  seed step today. Nightly is due after **20 hours** since the routine's
  last recorded run; weekly after **6.5 days**. Both thresholds are
  intentionally shorter than the nominal cadence so a routine that's a
  few hours late (e.g. the machine was asleep) still fires on the next
  calendar tick rather than sliding a full extra day. An unrecognised
  cadence string doesn't crash seeding — it escalates a `runner-error`
  for that routine and the rest of the routines still get considered.
- **`expectedArtifact`** — the gate. `artifactPath` may contain
  `{date}` (`YYYY-MM-DD`), `{runId}`, and `{vault}` (the first entry of
  `wikiPaths`) template tokens, substituted at check time. `maxAgeSeconds`
  is how old the artifact is allowed to be — set it comfortably above the
  cadence interval (the `wiki-lint` example above uses 129600s = 36h for
  a nightly routine; the four weekly routines use 691200s = 8 days) so a
  slightly-late run doesn't fail its own gate. `predicate` is one of:
  - `{ kind: "exists" }` — file present and fresh, nothing more.
  - `{ kind: "contains", marker }` — file present, fresh, and contains
    `marker` (itself `{date}`/`{runId}`/`{vault}`-substituted).
  - `{ kind: "json-field", path, value }` — file parses as JSON and the
    dotted `path` resolves to exactly `value`.
- **`escalation`** — an array drawn from `["notification",
  "vault-note"]`. Both shipped channels are enabled on all five
  example routines; there's no "off" option today — a routine either
  escalates through the channels it lists or (if the array is empty)
  fails silently except in the runlog, which is rarely what you want.

A run isn't "done" until the runner sees a passing `checkArtifact()`
result for the routine it resolved — an exit-0 `claude` process that
never wrote the expected artifact is a **failure**, not a success. This
is deliberate: it's the whole reason routines exist instead of a bare
cron job piping into `claude -p`.

## `workflow-audit-weekly`: transcript mining with queue-mode proposals

This routine mines transcripts from the last 7 days, clusters repeated tool-use patterns, judges them as skill candidates, and writes any `propose` verdicts as queue entries in the dashboard approval queue. It runs in **queue-mode mandatory**: in-session skill creation is forbidden, and every proposal appears as a queue entry awaiting the owner's Approve click, never auto-built.

The routine's run note lives at `~/.claude/coderails-dashboard/routines/workflow-audit/run-{date}.md` and records `proposals_written: <N>` (count of queue entries actually written this run). The artifact gate checks for the completion marker `## [{date}] workflow-audit complete`, which the routine emits **only** if it finishes cleanly **and** `proposals_written == proposals_attempted` (no queue write failures). A week with zero proposals (`proposals_written: 0` with no failures) is a **successful run** — the marker is emitted and the gate passes. A crash, or a shortfall where some proposals failed to write, causes the marker to be omitted and the gate to fail.

The 8-day artifact-gate freshness window (`maxAgeSeconds: 691200`) provides catch-up grace for a run that fires late (e.g. the machine was asleep at the scheduled time) — a run inside that window still passes the gate. Read `proposals_written: 0` plainly: no repeated patterns reached the proposal threshold this week, and zero proposals is not a failure or a request to lower the threshold — it's the expected norm in a healthy workflow. Report it as a green, completed run just like any other passing gate.

## `docs-sync-nightly`: self-merging documentation drift fixer

Every night, this routine's skill (`skills/docs-sync/SKILL.md`) audits
the repo's git-tracked documentation (`README.md`, `AGENTS.md`,
`CLAUDE.md`, tracked `docs/*.md`) for drift against the actual codebase,
using `/coderails:sync-docs`'s own audit. If nothing needs fixing, it
logs `no-drift` and stops — no branch, no PR — before any git state is
touched, which keeps a healthy night from ever producing an empty or
no-op PR. If drift is found, it fixes it and drives the fix through the
full gate chain (task-evals frozen before the edit, a
`git diff origin/main...HEAD --name-only` manifest assertion — three-dot,
because a sibling PR merging into `main` mid-run must not make a clean
branch look contaminated — review, post-review, post-evals, merge) and
merges its own PR with no human in the loop.

It replaces the former `sync-docs-weekly` routine, which had been
silently broken for 9 days: its `foreignSkillPath` pointed at a path
under `~/.claude/skills/` that never existed (the real skill lives
in-repo), and `loadConfig()`'s own validator only checks that
`foreignSkillPath` is a non-empty absolute string, never that the path
exists on disk — so the broken config loaded clean and the failure
surfaced only at sweep time, with zero escalations logged the whole
time it was dead. `docs-sync-nightly` needs no `foreignSkillPath` at
all: its skill ships in-repo, same as `loop-retro-promotion`.

Its manifest is hard-scoped to git-tracked `.md` files. If the diff ever
contains anything else — a hook script, `scripts/`, `.claude/settings.json`,
any code — the skill aborts with cleanup (closes the PR if one was
opened, deletes the branch locally and on the remote) rather than
warning and continuing.

**Security note.** See the security warning below —
`docs-sync-nightly` is the **second** routine in this repo (after
`loop-retro-promotion-weekly`) to use a non-`read-only` button profile
(`bypass`). Its mitigation is the same shape as that routine's: no hook
protects a `claude -p` run, so the entire merge rail is the manifest
lock (docs-only, three-dot-scoped) plus `scripts/merge.sh`'s own
script-internal artifact gates and `/pr-review-toolkit:review-pr` — not
any hook or server-side check.

## `loop-retro-promotion-weekly`: a dormant-by-default routine

Unlike the other three read-only routines, `loop-retro-promotion-weekly`'s own
skill (`skills/loop-retro-promotion/SKILL.md`) evaluates a 3-part
graduation predicate every time it runs, before doing anything else: (1)
at least 10 `retro.json` files exist under the repo-key dir, (2)
`standing-orders.md` has at least one entry whose `last_recurred` differs
from its `created` date (one lesson has recurred at least once), and (3)
`standing-orders-decayed.md` has at least one entry (one lesson has
completed a full create → recur → decay lifecycle). Until all three
hold, the routine is dormant.

A dormant run still appends one line to `promotion-runs.log`
(`<ISO8601> predicate=unmet retros=<n> lifecycle=<0|1> decay=<0|1>`) and
stops there — no branch, no PR, no gate chain. That log line is
deliberately this routine's `expectedArtifact` (an `exists` predicate),
precisely so a dormant run still passes its artifact gate: dormancy is
the expected steady state for a long while after this routine ships, not
a failure, and the routine shouldn't escalate every week just because the
graduation bar hasn't been met yet.

**Security note.** This is the first routine in this repo to use a
non-`read-only` button profile (`bypass`, i.e.
`--dangerously-skip-permissions` — see the security warning below). Once
the predicate graduates, the routine opens and merges its own PR with no
human in the loop, and — as that warning documents — `PreToolUse` hooks
do not fire under `claude -p`, so `test_gate`/`enforce_pr_workflow` do
not protect this run either. Its merge rail is entirely
`scripts/merge.sh`'s own script-internal artifact gates, plus
`/pr-review-toolkit:review-pr` and the manifest assertion the skill
itself runs before pushing (abort-with-cleanup if the diff isn't exactly
`skills/agentic-loop/learned-failure-modes.md`) — no hook and no
server-side check backs any of this up. This repo deliberately does not
enable GitHub branch protection (2026-07-15) — that's a standing
decision, not a TODO — so this routine's merge rail rests entirely, by
design, on the script-internal gates named above.

## Install / uninstall

Two launchd jobs drive the runner, both installed by
`launchd/install-routines.sh` (idempotent — safe to re-run):

- **`com.coderails.routine-sweeper.calendar`** — fires daily at 03:00,
  runs `skills/dashboard/runner/bin/seed-and-sweep.sh`, which seeds any
  due routines into `queue/` and then sweeps. The seed step's own exit
  code never blocks the sweep that follows it — a seeding failure still
  lets any already-queued (e.g. button-pressed) intents get processed.
- **`com.coderails.routine-sweeper.watch`** — fires on any write under
  `~/.claude/coderails-dashboard/queue`, runs
  `skills/dashboard/runner/bin/sweeper.sh` (sweep only, no seed step —
  a button press already wrote its own intent, nothing to seed).

```bash
launchd/install-routines.sh     # copy both plists into ~/Library/LaunchAgents and bootstrap into gui/$UID
launchd/uninstall-routines.sh   # bootout both plists and remove the LaunchAgents copies
```

Install **copies** each plist into `~/Library/LaunchAgents/` and bootstraps
from that copy, not from the repo path. This is what makes the jobs survive a
reboot: a `launchctl bootstrap` from an arbitrary path lasts only until
logout/reboot, and launchd only auto-loads plists that live in
`~/Library/LaunchAgents/`. Bootstrapping straight from the repo directory
silently unloads the entire routines system on the next reboot — observed live
on 2026-07-08, when the 03:00 run succeeded, the machine rebooted at 07:34, and
afterwards no `com.coderails` jobs were loaded and no copies existed in
`~/Library/LaunchAgents/`. Uninstall boots out both labels and removes those
copies.

Both plists hard-code this machine's absolute paths (checkout location,
log path, `/opt/homebrew/bin/node`) at authoring time — they are **not
portable** to a different checkout location or a different user's
machine without hand-editing the plist files first. `launchd`'s
environment carries no `PATH` (confirmed via `launchctl print
gui/$UID`), which is why both bin scripts and the plists use absolute
paths throughout rather than relying on a shell's PATH resolution.

## Where to look when something fails

Four places, roughest signal to most precise:

1. **`~/.claude/coderails-dashboard/routines/sweeper.log`** — both
   plists' stdout/stderr. First stop for "did the job even run" —
   launchd scheduling failures, node crashes before a `SweepResult`
   exists, and the seed step's own stderr (seed failures print to
   stderr but don't block the sweep) all land here.
2. **`~/.claude/coderails-dashboard/runs/runs.jsonl`** — one JSONL
   record per run (start line, then a finish line with `exitCode` and
   `endedAt` folded in), across every button and routine. This is the
   ground truth for "did this run, when, with what argv, what exit
   code" — read via `readRuns()`, the same reader the merged dashboard
   app itself uses. Every record carries an `outputPath` field, but only
   a dashboard-triggered button run (via `POST /run` in
   `skills/dashboard/app/src/app/api/run/route.ts`) actually writes its
   captured stdout/stderr there as it streams, and exposes it via `GET
   /api/run/output` and the COMMAND DECK's Run Output viewer. A
   **routine** run (the scheduler's `sweep.ts`) still only computes and
   stores the path — it captures stdout/stderr in memory via
   `runClaudeImpl` but never writes them to `outputPath`, so reading a
   routine's `outputPath` gets you a path to a file that doesn't exist.
   For a routine's captured output, this runlog is not yet the place to
   look — see the `sweeper.log` and vault-note entries above and below
   instead.
3. **Vault run notes** — `<first wikiPath>/dashboard-runs/<routine or
   button name>.md`, one file per routine/button, append-only, one `##
   [YYYY-MM-DD] run <id> — green|red` section per run with a reason on
   red. This is the human-readable failure history and is written for
   both routine successes (green) and failures (red) — it is not just
   an error log. **This is a distinct vault note type from the wiki
   schema in `AGENTS.md`** (`type: routine-run`, not one of
   `command|hook|skill|design|investigation|source`) — it is not
   ingested by `/wiki-ingest` and does not follow the wiki page-format
   contract; treat it as operational output, not a wiki page. Note the
   `dashboard-runs/` folder holds two note conventions side by side: the
   runner's `writeRunNote` (described above) writes one rolling
   `<routine>.md` per routine with `type: routine-run` frontmatter, while
   the Obsidian plugin's direct-exec path (pressing a button in the
   vault) writes a separate `<YYYY-MM-DD>-<button>.md` per run, with
   `status: running|done|failed` frontmatter and no `type` field at all.
4. **macOS notification** — fired synchronously on every escalation via
   `osascript`, titled `Routine failed: <routine name>`, body
   `<failure class>: <reason>`. Transient — if you miss it, the vault
   note and runlog are the durable record.

## Escalation taxonomy

Every escalation carries a `failureClass`, always paired with a `reason`
string, in both the notification body and the vault note:

| Failure class | Fires when |
|---|---|
| `skill-missing` | The routine's `foreignSkillPath` doesn't exist on disk — checked before spawning `claude` at all. |
| `claude-spawn-failed` | `resolveClaudePath()` found no `claude` binary, or `execFile` itself failed to spawn the process (e.g. bad `cwd`). The process never started. |
| `exec-error` | `claude` spawned and exited non-zero, or the process was killed for exceeding the 30-minute timeout (the reason text says "timeout" explicitly in that case). |
| `artifact-gate-failed` | `claude` exited 0 but `checkArtifact()` failed — missing, stale, or predicate mismatch. The routine "succeeded" by exit code and still failed. |
| `runner-error` | A failure in the runner's own bookkeeping around a claimed intent (or a seed-time misconfiguration — unrecognised cadence, unresolvable `buttonRef` — see below), not the routine's execution itself. Also used for orphan recovery (a `processing/` file abandoned by a crashed sweep, reclaimed after 60 minutes). |

**No deduplication.** Escalation has no "already told you about this"
memory. A permanently misconfigured routine (bad cadence, dangling
`buttonRef`) re-escalates in full on every calendar fire, forever. This
is deliberate — a silently-swallowed misconfiguration is worse than
repeated noise, and dedup adds state (what counts as "the same"
failure, when to expire it) not worth building until the noise itself
becomes the problem in practice.

## Security warning: bypass-profile routines run outside the hook safety net

**Empirically verified in this repo (2026-07-07):** under `claude -p`
(the non-interactive mode the runner always uses), `SessionStart`,
`UserPromptSubmit`, and `Stop` hooks fire normally, but **`PreToolUse`
hooks do not fire**. This was confirmed directly: with a `test_gate`
trigger file configured to force a deny, a `-p` invocation ran `git
commit` and it succeeded — the gate never engaged.

Concretely, `test_gate` and `enforce_pr_workflow` — the hooks that
block untested commits and direct pushes to `main` in an interactive
session — **do not protect a routine run**. A routine configured with
`"profile": "bypass"` on its button (via `--dangerously-skip-permissions`,
see `buildArgv` in `skills/dashboard/app/src/lib/argv.ts`) runs headless
with neither the CLI's own tool allowlist (a `read-only`-profile
routine gets `--allowedTools Read Grep Glob`; `bypass` gets no
allowlist at all) nor the hook-based safety net an interactive terminal
session gets.

**Ship read-only routines unless you have explicitly accepted this.**
Four of the five shipped example routines use `"profile": "read-only"`
for exactly this reason. `loop-retro-promotion-weekly` is
the deliberate, documented exception — see the section above for what
backs up its merge instead of a hook. If a routine's skill needs to
write files or run commands, understand that its actions are gated only
by the artifact check after the fact, not by any hook before the fact.

**Write surfaces for unattended routines.** `workflow-audit-weekly` runs
headless in `read-only` profile; its write surface is restricted to two
directories: `~/.claude/coderails-dashboard/routines/workflow-audit/`
(its own run note, containing `proposals_written: N` and optionally the
completion marker) and `~/.claude/coderails-dashboard/approvals/`
(queue entries for each proposed skill, carrying only the judge's D2-whitelisted
fields, never full transcript content). The scan's privacy boundary — structural
extraction only, no full-text content — is enforced at the `scan_transcripts.sh`
level and is unchanged by this routine.

## See also

- [`skills/dashboard/lib/README.md`](../skills/dashboard/lib/README.md)
  — the `Intent`/`RoutineDef` schema contract and queue lifecycle in
  full.
- [`skills/memory-consolidation/SKILL.md`](../skills/memory-consolidation/SKILL.md)
  — one of the five shipped routines; a good template for a routine
  whose own skill writes its artifact-gate report natively.
- [`skills/loop-retro-promotion/SKILL.md`](../skills/loop-retro-promotion/SKILL.md)
  — the fourth shipped routine; dormant by default, see the
  dedicated section above for its graduation predicate and security
  posture.
- [`examples/dashboard-config.json`](../examples/dashboard-config.json)
  — the full five-routine config this doc's examples are drawn from.
