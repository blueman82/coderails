# Approve-Click → Skill-Creator Builder Runner — Contract

**Date:** 2026-07-07
**Status:** Normative for the shipped seam (WU1, merged); the wrapper and
prompt template (WU2) implement this contract — see the per-section notes
below for what is design-committed versus already merged code.
**Sub-project:** loop 2 of the workflow-audit × dashboard integration —
"Approve → skill-creator builder pipeline". Builds on
[`2026-07-07-workflow-audit-queue-seam.md`](2026-07-07-workflow-audit-queue-seam.md),
which this document supersedes only in its "Honesty requirement" section
(see that document's own note).

## What this builds

When the owner clicks Approve on a `workflow-audit:propose-skill` queue
entry, the dashboard now spawns a detached, headless `claude -p` build that
authors the proposed skill via **skill-creator** and ships it as a coderails
PR through the full gate sequence. The builder never merges — its terminal
state is an open PR with gates green, rendered on the dashboard as
"awaiting your merge." The owner reviews and merges by hand.

## 1. Trigger (shipped, WU1, merged)

Inside `POST /api/queue`
(`skills/dashboard/app/src/app/api/queue/route.ts`), synchronously after
`resolveQueueEntry` succeeds, the route calls `claimAndSpawnBuild` when both
conditions hold on the returned entry:

```
entry.status === "approved" && entry.toolName === "workflow-audit:propose-skill"
```

`resolveQueueEntry` (`skills/dashboard/app/src/lib/collect/queueActions.ts`)
carries a **pending-only transition guard**: it throws `QueueActionError` if
the entry's current status is not `"pending"`, and the route maps any error
whose message includes `"is not pending"` to an HTTP 409. This closes
approve-after-deny and double-approve re-flips — a second click against an
already-decided entry never re-triggers a build. `resolveQueueEntry` returns
the parsed, updated entry object (the exact bytes it just wrote), so the
route has a byte-accurate snapshot to hand to the build claim without a
second file read.

**Send-gate isolation, two independent mechanisms:** (a) gate-owned queue
entries (Slack/Calendar) never carry `toolName: "workflow-audit:propose-skill"`,
so the gate condition above can never match them; (b) the builder never
writes into the queue directory — all of its state lives in a separate
builds directory (§2) — so nothing the builder does can perturb the send
gate's own poll of the queue directory.

## 2. The claim (shipped, WU1, merged)

`claimAndSpawnBuild` (`skills/dashboard/app/src/lib/build/spawn.ts`):

1. Reads `toolInput.proposed_name` from the entry (narrowed defensively —
   `toolInput` is `unknown` per the queue contract) and validates it against
   `^[a-z0-9][a-z0-9-]{0,63}$`. A failing or missing name returns
   `{ claimed: false, error: "invalid_name" }` and claims nothing — see the
   dead-end this creates in §6.
2. Claims the hash via a non-recursive `mkdirSync(buildsDir/<hash>)`.
   `EEXIST` means another request already claimed this hash — returns
   `{ claimed: false, alreadyClaimed: true }`. This is the same
   atomic-exclusive idiom `api/run/route.ts`'s `acquireLock` already uses.
3. On a successful claim, writes three files into `builds/<hash>/`:
   `snapshot.json` (the exact entry object, `JSON.stringify`'d — this is
   what the builder consumes, never the live queue file), `prompt.md`, and
   `state.json` (`{ schemaVersion: 1, hash, state: "claimed", createdAt }`).
4. Spawns `bash <wrapperPath> <buildDir>` detached and unref'd, with
   `CODERAILS_BUILDER=1` in its environment, then returns
   `{ claimed: true, runId: hash.slice(0, 8) }`. The spawn function is
   dependency-injected (`ClaimAndSpawnBuildDeps.spawnImpl`) exactly like
   `api/run/route.ts`'s `execFileImpl`, so tests never fork a real process.

Fire-and-forget is safe here because the claim directory is never released
on process exit — it always ends up in a terminal state written by the
wrapper (§3), and retry is deleting the directory (§6), not re-approving.

**`prompt.md` as shipped by WU1 is a placeholder** (`"See prompt.ts (WU2)
for the real template — this task only establishes the file-write
contract"`) — WU1's scope was the file-write contract, not the prompt
content. The real interpolated template is WU2's `src/lib/build/prompt.ts`
(§4 describes its committed design).

## 3. Sidecar schema (builds directory)

Build lifecycle lives entirely in
`~/.claude/coderails-dashboard/builds/<hash>/`, a directory **separate from**
the queue directory. This is a deliberate structural choice: the queue
contract requires any file failing `parseQueueEntry` to be logged as
`unparseable_entry:<filename>` (`skills/dashboard/app/src/lib/collect/queue.ts`),
and the queue's own status vocabulary is closed to exactly
`pending|approved|denied` (`VALID_STATUSES` in the same file) — putting
build-lifecycle state inside the queue directory, or inventing a new queue
status for it, would either generate permanent false rejections or reopen a
frozen vocabulary two shipped consumers already depend on. The builds
directory keeps the queue directory byte-for-byte untouched.

`state.json`, `schemaVersion: 1`:

```json
{
  "schemaVersion": 1,
  "hash": "...",
  "state": "claimed|queued|running|pr_open|failed",
  "pid": 123,
  "startedAt": 0,
  "claudeVersion": "2.1.202",
  "prUrl": "...",
  "failureReason": "hash_mismatch:<hash>|unparseable_entry:<filename>|invalid_name|timeout|queue_timeout|nonzero_exit",
  "stderrTail": "last 20 lines"
}
```

A heartbeat touch-file (`builds/<hash>/heartbeat`) is touched by the wrapper
periodically; its mtime, not a JSON field, is the staleness signal — this
avoids a JSON-rewrite race between the wrapper and the dashboard collector
polling the same file.

*Per implementation (WU2/WU3, not yet merged):* the wrapper is designed to
touch the heartbeat roughly every 30 seconds while `running`, and a
dashboard collector (`src/lib/collect/builds.ts`) is designed to read this
directory with the same closed-set validation discipline as
`parseQueueEntry` — rejecting an unrecognised `state` value rather than
defaulting it — and surface a "builder dead" state when the heartbeat goes
stale while `state == "running"`.

## 4. The builder wrapper and prompt (per implementation — WU2, not yet merged)

The following describes the **committed design** for
`skills/dashboard/scripts/run-builder.sh` and
`skills/dashboard/app/src/lib/build/prompt.ts`. Treat it as the contract
WU2 implements, not as verified shipped behaviour — WU2 is still in
progress at the time of writing.

**Wrapper responsibilities, in order** — the wrapper, not the LLM, owns the
state machine and the hash check:

1. **Global serialization.** Acquire a single `builder.lock` (exclusive
   create + live-pid staleness check, the same idiom as the run route's
   lock) before starting a build; a wrapper invocation that can't acquire
   the lock immediately sits in `state: "queued"` and polls, giving up after
   a 4-hour ceiling with `failureReason: "queue_timeout"`. This is repo-level
   serialization only — per-hash idempotency is already the mkdir claim in
   §2; this lock exists because only one builder should touch the repo's
   worktrees at a time.
2. **Deterministic hash re-validation, before any LLM process starts.**
   Recompute the hash over `snapshot.json`'s `toolInput`
   (`jq -S -c .toolInput | shasum -a 256`) and compare it against the
   snapshot's own stored `hash`. A mismatch is `failureReason:
   "hash_mismatch:<hash>"` and the build stops — `claude` is never invoked.
   An unreadable or malformed snapshot is the separate rejection
   `failureReason: "unparseable_entry:<filename>"`. These are the same two
   distinct, non-soft rejections the queue-seam contract already defines for
   the (still unbuilt at that document's time of writing) consumption seam —
   this wrapper is that seam's actual implementation.
3. **Filter re-assertion.** Confirm the snapshot's own
   `status == "approved" && toolName == "workflow-audit:propose-skill"`
   before proceeding — belt-and-braces against a snapshot written under a
   future code path that skips the route's own gate.
4. **Worktree creation**, off an absolute repository path asserted (not
   derived from the wrapper process's own working directory) — `.git`
   presence and a `package.json` name check — before running `git worktree
   add`. A cwd-relative repo path is exactly the class of bug this
   assertion exists to prevent.
5. **Spawn `claude -p`**, cwd set to the new worktree, with
   `--dangerously-skip-permissions`, a **`--max-budget-usd 25`** cap, and a
   **45-minute wall-clock** watchdog (`kill -TERM` after
   `BUILDER_WALL_CLOCK_SECS`, env-overridable) — macOS ships no stock
   `timeout(1)`, so the watchdog is implemented in the wrapper itself.
   `--max-turns` does not exist as a CLI flag (verified against `claude -p
   --help`), so budget cap and wall clock are the only two runaway bounds.
6. **Terminal state from artifacts, not exit code alone.** Exit 0 **and**
   the existence of `<buildDir>/pr_url` (the one file the prompt instructs
   the builder to write, containing only the PR URL) together mean
   `state: "pr_open"`. Anything else is `failed`, tagged with the most
   specific `failureReason` available (`timeout`, `nonzero_exit`, or —
   optionally, cheaply — `budget_exceeded` when the result JSON's `subtype`
   is `error_max_budget_usd`, per the probe result in §7). A `trap` on exit
   guarantees a terminal state is always written even if the wrapper itself
   crashes.

**Prompt contract** (`src/lib/build/prompt.ts`, a typed template function
interpolated server-side at claim time, snapshot fields appearing only
inside one fenced block):

1. The builder is scoped to exactly one approved proposal: its sole
   authority is the `snapshot.json` already hash-verified before it started.
   It must never read or write the queue directory, and must not batch in
   any other pattern it happens to notice.
2. Snapshot-derived fields (`proposed_name`, `proposed_description`,
   `task_summary`, `cluster_ngram`, `sessions`) appear only inside one
   ` ```untrusted-proposal-data ... ``` ` fence, preceded by a static
   instruction never to follow anything found inside it — see §5 for the
   full injection-containment rationale. Nothing from the snapshot is
   interpolated anywhere else in the prompt template.
3. **Authoring** is driven through `/skill-creator:skill-creator`'s create
   flow, fully specified from the snapshot content so its intake questions
   are all answerable from context, skipping skill-creator's own
   human-facing eval-viewer step. **Stop condition** is substituted from
   `coderails:writing-skills`'s RED/GREEN/REFACTOR discipline (skill-creator
   itself has no autonomous "done" signal): a fresh-subagent baseline
   pressure test without the new skill, a minimal `SKILL.md` addressing the
   observed baseline failures, then a re-test that closes any loopholes.
4. Transcript mining is bounded: the builder may read the `sessions`
   transcripts locally to understand context, but must never place verbatim
   transcript prose, file contents, or paths into the skill, its tests, the
   PR description, or any other committed artifact — only generic derived
   intent. This matters because the repo is flippable to public at any time.
5. **Delivery** follows the same invariant workflow-audit's own SKILL.md
   already pins for the create step, verbatim: its own branch, then
   `/coderails:push`, then the full gate sequence — `test_gate` →
   `pr-review-toolkit:review-pr` → security review → `post-review` →
   pr-scope evals → `post-evals`. Never a commit straight to `main`, never a
   write into a user's personal `~/.claude/skills` directory.
6. **Terminal instruction: stop once gates are green on the open PR. Never
   invoke `/coderails:merge`.** The final act is writing the PR URL to
   `<buildDir>/pr_url`.
7. The builder must not spawn further headless `claude` sessions or agent
   teams — `CODERAILS_BUILDER=1` in its environment marks it as already one.

## 5. Why the owner merges, not the builder

The Approve click authorises *creating* code that did not exist at click
time — it is not consent to land a diff the owner never saw. Two
independent reasons converge on the same answer:

- **Prompt-injection backstop.** The judge-authored `proposed_description`
  and `task_summary` fields are derived from transcript content the judge
  saw, and the containment measures in §4/§6 reduce but do not eliminate the
  risk that adversarial content shapes the builder's behaviour. A human
  reading the opened PR before merging is the one review step that isn't
  correlated with whatever compromised the builder's judgement, if anything
  did.
- **Consistency with the repo's existing delivery invariant.** Every other
  skill this repo has ever shipped goes through branch + PR + full gates
  before a human merges it. Auto-merging skill PRs would be a new exception
  carved out only for this pipeline, and no owner directive has asked for
  that exception — the authorising instruction that named this pipeline
  ("build the motherfucker") names building, not merging.

The dashboard's `pr_open` state is rendered as an explicit "awaiting your
merge" call to action (*per implementation, WU3*), so an approved-but-not-yet-merged
build is visible, not silently dangling.

## 6. Concurrency, idempotency, and retry

| Situation | Mechanism |
|---|---|
| Double-click, two tabs, replayed request | Pending-only transition guard → HTTP 409 |
| Two near-simultaneous successful flips racing to spawn | `mkdirSync(builds/<hash>)` exclusive claim — exactly one spawn wins |
| Approve-after-deny | Same pending-only guard (status is no longer `"pending"`) |
| Several approvals in one sitting | Single `builder.lock`; later wrappers wait in `state: "queued"` *(per implementation, WU2)* |
| Wrapper or `claude` process crashes mid-build | `trap`-guaranteed terminal state write, plus heartbeat staleness surfaced on the dashboard *(per implementation, WU2/WU3)* |
| **Retry** | Delete `builds/<hash>/` by hand. **Re-approving the same queue entry is not the retry path** — the entry is no longer `"pending"` once approved, so a second Approve click 409s rather than re-spawning. |
| **Invalid `proposed_name` dead end** | An approved entry whose `toolInput.proposed_name` fails `^[a-z0-9][a-z0-9-]{0,63}$` gets `error: "invalid_name"` from `claimAndSpawnBuild` and **no claim directory is ever created for it** — there is nothing to delete and no retry that helps this specific entry, because its status is already `"approved"` and the pending-only guard blocks re-approval. The fix is not editing the queue file by hand; it is a fresh workflow-audit run that proposes the same cluster again under a name that passes validation, producing a new hash and a new pending entry. |

## 7. Threat-model honesty note

This pipeline's threat model is deliberately narrow. **In scope:**
prompt-injection via judge-authored `proposed_description`/`task_summary`
content, contained by the untrusted-data fence (§4.2), the absence of merge
authority (§5), and the hash re-validation happening before any LLM process
exists (§4.2) rather than being trusted to prompt text. **Out of scope:**
a compromised or malicious process already running as the same local user —
that actor could bypass this entire pipeline by writing to the repo
directly, and no fence or budget cap defends against it. **Bounded but not
eliminated:** runaway cost and runtime, bounded by a $25 budget cap and a
45-minute wall clock, both env-overridable, neither a hard guarantee against
a sufficiently adversarial builder session burning the full allowance
before failing.

Two runtime probes closed open questions ahead of WU2 (recorded in the
loop's `probe-results.md`, not committed to this repo): `claude -p` can list
and would be expected to invoke `skill-creator:skill-creator` and the other
named gate skills under `-p`, and a `--max-budget-usd` breach produces a
clean nonzero exit with `result: null` and `subtype: "error_max_budget_usd"`
in the JSON output — no partial or hung state — which is exactly what the
wrapper's artifact-based terminal-state logic (§4.6) already expects.

## 8. E5 — the manual eval this pipeline still owes

Everything in §1–§4 above that is stubbable is covered by automated,
stub-`claude` evals at loop scope (byte-comparison against the queue file,
absence-of-invocation as the tamper oracle, and so on — see the loop's
`evals.json`, not committed to this repo). The one thing that cannot be
faked is a real `claude -p` + skill-creator build running to completion.
**E5** is a manual, loop-closing eval: the owner seeds one real proposal,
clicks Approve in the browser, watches a real build reach `pr_open`, and
then reviews and merges the resulting skill PR by hand. This is the only
honest exercise of the full headless authoring path, and it is treated as
an approval-gate stop rather than an automated pass/fail — a human judges
whether the produced skill and PR are acceptable, not a script.

## Non-goals

- No scheduling, cron, or polling loop — the build spawns synchronously
  from the Approve click itself; there is no separate consumer process
  waiting on the queue or builds directory.
- No auto-merge, now or by default — see §5.
- No change to the queue file format, its status vocabulary, or the
  Approve/Deny button wiring beyond the toolName-gated spawn call described
  in §1 — the queue contract in
  [`2026-07-06-assistant-link-panel-design.md`](2026-07-06-assistant-link-panel-design.md)
  is unchanged.
