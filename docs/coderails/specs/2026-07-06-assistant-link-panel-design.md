# ASSISTANT.LINK Panel + Approval-Queue Contract — Design

**Date:** 2026-07-06 (queue contract + button confirmed built 2026-07-06, see [Post-freeze reconciliation](#post-freeze-reconciliation-2026-07-06))
**Status:** Contract confirmed implemented on both sides (assistant-agent#4, coderails#31); panel spec approved by owner (D6); items 1/2/4 remain unbuilt as designed
**Sub-project:** 4 of 5 in the agentic-OS evolution sequence (secretary/coderails-kernel integration)

## Context

Sub-project 4 puts the secretary (`~/Github/assistant-agent`) on the coderails
kernel: a deterministic Tier-2 send-approval gate in front of Slack/Calendar/
Gmail send tools, with three approval surfaces (terminal, Telegram, and a
dashboard queue). This spec defines the two pieces that are dashboard-facing
rather than secretary-internal:

1. The **on-disk contract** for the approval-queue files the secretary's gate
   writes and the dashboard (`skills/dashboard/`, landed via PR #25) will
   eventually read and act on.
2. The **ASSISTANT.LINK panel** — a dashboard panel surfacing secretary state
   (tasks, email, sends/approvals, routine runs) alongside the existing
   session/loop/PR-gate panels.

This was originally a design/contract document only, with no dashboard code
added or modified. That has since changed: both sides of the contract, and
the panel's queue-slice UI, are now built and merged — see
[Post-freeze reconciliation](#post-freeze-reconciliation-2026-07-06) for what
shipped and where. The rest of this document is kept as originally written
(the design record), except where reconciliation notes are inserted inline.

## Normativity note (historical — see reconciliation)

At the time of writing, `~/Github/assistant-agent`'s send-gate (WU2) had not
yet implemented `gate/surfaces/queue.ts` — there was no `QueueFileEntry` shape
in code to copy verbatim. Per the loop plan's fallback instruction, **this
document was the normative side of the contract**: WU2's `queue.ts` was
required to conform to the shape defined here, not the reverse. The exact
shape was sent to worker `wu2-gate` directly (SendMessage) so their
implementation could consume it without re-deriving it.

**Outcome (confirmed 2026-07-06):** WU2 shipped `gate/surfaces/queue.ts`
(assistant-agent PR #4, merged `e492f745`) with a `QueueFileEntry` byte-
identical to the shape below — field names, types, and the "no expired/
timeout status in the file" design point all match exactly, confirmed by
wu2-gate directly and independently by reading the merged file. No
divergence occurred; no re-resolution was needed.

## Queue contract

### On-disk layout

```
~/.claude/coderails-dashboard/queue/<hash>.json
```

One file per pending (or resolved) approval, named by the hex SHA-256 hash of
the canonicalised tool input (see WU2's `gate/sendGate.ts` `hashInput`). The
directory is created idempotently (`mkdir -p` semantics) by whichever process
writes first — the secretary's gate is the only writer of `pending` entries;
a future dashboard Approve/Deny button is the only writer of the
`approved`/`denied` transition.

### `QueueFileEntry` shape (normative)

```typescript
export interface QueueFileEntry {
  hash: string;           // sha256(canonicalise(toolInput)), hex — also the filename stem
  toolName: string;       // e.g. "mcp__claude_ai_Slack__slack_send_message"
  toolInput: unknown;     // the raw (canonicalised) tool_input the approval covers
  createdAt: number;      // epoch ms, when the pending entry was first written
  status: "pending" | "approved" | "denied";
}
```

Field-by-field rationale:

- `hash` is duplicated as both the filename and a field so a consumer that
  globs the directory doesn't need to parse filenames to get the key, and a
  consumer that already has the file open doesn't need the path.
- `toolInput` is `unknown` deliberately — the queue is generic across all
  gated tools (Slack/Calendar/Gmail); the panel and any future button render
  it opaquely (e.g. `JSON.stringify` in a `<pre>`), never destructure it by
  assumed shape.
- `status` is the entire state machine: `pending` → `approved` | `denied`.
  There is no `expired`/`timeout` status in the file — a timeout is a gate-
  side decision (recorded in the audit log, per D2), not a queue-file state;
  the gate simply stops waiting on the file and the file is left `pending`
  as a stale artifact. A future cleanup routine (unbuilt, out of scope here)
  may prune stale `pending` files past some age.

### Consumption semantics

- **Writer (secretary gate, WU2):** on a gated tool call, writes a `pending`
  `QueueFileEntry` to `<queue-dir>/<hash>.json`, then polls (or watches) that
  same file for `status` to change away from `"pending"`. This is the write
  half of the "dashboard queue" approval surface from D3 item 3.
- **Reader (dashboard collector, unbuilt):** a `collectQueue` function
  shaped like the existing collectors in
  `skills/dashboard/app/src/lib/collect/` (see
  [Collector shape](#proposed-collector-shape) below) lists the queue dir,
  parses each `<hash>.json`, and surfaces `pending` entries for operator
  action and recent `approved`/`denied` entries for the audit view.
- **Writer (dashboard Approve/Deny button, unbuilt, deferred):** flips
  `status` from `pending` to `approved` or `denied` in place. This is the
  only piece of the round-trip not yet built — see
  [Deferred work](#deferred-work-approvedeny-button).

### Proposed collector shape

Modeled directly on `collectMemoryTrail` (`skills/dashboard/app/src/lib/collect/memoryTrail.ts`),
which is the existing collector closest in shape (list a directory, parse
each file, degrade to `[]` on any read error, never throw, sort newest-first,
truncate to a caller-supplied `limit`):

```typescript
// skills/dashboard/app/src/lib/collect/queue.ts (proposed, NOT built by this spec)
export interface QueueEntry {
  hash: string;
  toolName: string;
  toolInput: unknown;
  createdAt: number;
  status: "pending" | "approved" | "denied";
}

// Lists `<queueDir>/*.json`, parses each as a QueueFileEntry. A missing dir,
// an unreadable file, or a file that fails JSON.parse contributes nothing —
// consistent with collectMemoryTrail's per-file try/catch and
// collectPrGates's per-source safeCall wrapper in index.ts. Never throws.
export function collectQueue(queueDir: string): QueueEntry[];
```

Wiring into the aggregator (`skills/dashboard/app/src/lib/collect/index.ts`)
follows the existing pattern exactly: add `queue: QueueEntry[]` to the
`Snapshot` interface, call `collectQueue` inside `collectActivitySlice()`
wrapped in the same `safeCall("queue", () => collectQueue(dir), [])` idiom
used for `trail` and `health`, and add a `queueDir` (or reuse
`DashboardConfig`'s existing path conventions — confirm against
`~/.claude/coderails-dashboard.json`'s schema at build time) to
`AggregatorDeps`. This spec proposes the signature and wiring point; it does
not implement them.

### Negative-control note (for WU4-1's frozen eval)

A fixture `QueueFileEntry` that renames or drops a field (e.g. `tool_name`
snake_case, or a missing `status`) must fail a diff against this shape — that
mismatch is exactly what the WU4-1 eval's negative control checks for. Since
this document is normative (no `queue.ts` exists yet to diff against), the
"diff" for now is: wu2-gate's eventual `queue.ts` must match this file's
`QueueFileEntry` verbatim, field names and types included.

## ASSISTANT.LINK panel spec (D6)

A new dashboard panel, `ASSISTANT.LINK`, surfacing secretary
(`~/Github/assistant-agent`) state. Follows the existing panel/tile idiom in
`skills/dashboard/app/src/components/` (e.g. `HudCallout.tsx`,
`RailRight.tsx`) — this spec defines content and data sources; visual
placement and component implementation are left to the dashboard's own
build-time design pass, not fixed here.

Owner selected all four items (D6, spec.md); no fifth item is added
speculatively.

### 1. Tasks due/overdue

- **Source:** `~/Github/assistant-agent/tasks/*.md`.
- **Status at time of writing:** the `tasks/` directory in `assistant-agent`
  is currently empty (confirmed by listing it during this spec's research —
  zero `.md` files exist to infer a due-date convention from). This spec
  cannot freeze a parse format that has no example to derive it from. The
  panel's task-parsing logic must be resolved when WU1 or a future task
  actually populates `tasks/*.md` with a real file — at that point, whichever
  task-file convention emerges (front-matter due-date field vs. inline date
  in the body) becomes the parse target. Until then, this slot's data source
  is named but its parser is unbuilt; the panel should render an explicit
  "no tasks tracked yet" empty state rather than fabricate a schema.

### 2. Email last checked

- **Source:** a secretary-side state file (unbuilt) recording the sweep
  timestamp and unread count each time `secretary.ts` polls Outlook/Gmail.
- **Status:** this is a secretary-side dependency, not yet built by any WU in
  this plan. Noting it as a dependency here, not implying it exists: WU2's
  gate work does not produce this file, and no other WU in plan.md commits to
  building it. A future task must add a small JSON state write
  (`{ lastCheckedAt: number, unreadCount: number }` is the minimal shape) on
  each mail-sweep in `secretary.ts` before this panel slot has real data to
  show. Until then, the panel's empty state for this slot is "never checked".

### 3. Sends + approvals log

- **Source:** WU2's `gate/auditLog.ts` JSONL, directly reused — no new file
  format. Per plan.md Task 4's frozen format:
  `{ ts, event: "attempt" | "decision", toolName, hash, surface, decision? }`
  one JSON object per line, append-only.
- **Rendering:** most-recent-first, capped (mirrors `collectMemoryTrail`'s
  `limit` parameter convention) tail of the log — an `attempt` row paired
  with its subsequent `decision` row by matching `hash`. A `decision` row's
  `decision` field (`"approved"` | `"denied"` | presumably a timeout variant
  — confirm exact enum against WU2's actual `auditLog.ts` once built) drives
  the row's visual state.
- **Collector shape:** same idiom as the queue collector above — tail the
  JSONL file, parse each line independently (a single malformed line is
  skipped, not fatal to the whole read), degrade to `[]` on missing file.

### 4. Routine-runs slot

- **Source:** sub-project 2 (routines / intent-queue + runner contract),
  explicitly not yet landed.
- **Status:** placeholder shape only, per spec.md's own language ("populated
  when sub-project 2 lands"). This spec does not invent a routine-run data
  shape ahead of that sub-project's own contract — doing so risks exactly the
  kind of un-derived-from-reality placeholder the loop's plan explicitly
  avoids elsewhere (plan.md's "Placeholder scan" self-review gate). The panel
  reserves a labelled empty slot ("Routines — not yet configured") with no
  data source wired, to be filled in in sub-project 2's own spec/plan cycle.

## Deferred work: Approve/Deny button (historical — now built, see reconciliation)

The dashboard-side button that flips a `QueueFileEntry.status` from
`pending` to `approved`/`denied` was originally deferred until coderails PR
#25 (the dashboard's initial observability build) merged — confirmed merged
as of this writing (`378004e`, "Merge pull request #25 from
blueman82/observability/spec", an ancestor of `origin/main`'s then-current
head `d8fbdec`). **This deferral has since been resolved**: coderails PR #31
built the button, the collector, and the panel component — see
[Post-freeze reconciliation](#post-freeze-reconciliation-2026-07-06).

## Non-goals (as originally scoped by this PR — see reconciliation for what a later PR added)

- No dashboard code, component, or collector was implemented by *this* PR
  (#28). A later PR (#31) implemented all three — this section is retained
  to record the original scope boundary, not as a current statement of what
  exists in the repo.
- No change to `skills/dashboard/` was made by this PR.
- No retroactive change to WU2's gate implementation was needed — WU2's
  shipped shape matched this document exactly (see the normativity note's
  outcome above).

## Post-freeze reconciliation (2026-07-06)

This document was written and merged (PR #28) before either side of the
contract existed in code. Both sides landed shortly after, on the same day:

- **Queue-writer side** (`~/Github/assistant-agent`): `gate/surfaces/queue.ts`,
  merged via assistant-agent PR #4 (`e492f745`). `QueueFileEntry` matches this
  document's shape exactly — confirmed by wu2-gate directly and by reading
  the merged file.
- **Queue-reader + button side** (`~/Github/coderails`, `skills/dashboard/`):
  merged via coderails PR #31 (`feat/wu5-approve-button`, head `6fa5e34`).
  Files added: `skills/dashboard/app/src/lib/collect/queue.ts` (the
  `collectQueue` collector — matches the [Proposed collector shape](#proposed-collector-shape)
  above closely, with one addition this doc didn't specify: `parseQueueEntry`
  validates each field's type and rejects/skips entries with a renamed field
  or an out-of-vocabulary `status` rather than accepting anything
  JSON-shaped — a stricter, and better, reading of this doc's "never throws"
  requirement than the doc itself spelled out), `collect/queueActions.ts`,
  `components/AssistantLinkPanel.tsx` (the button + queue-slice UI, citing
  this document directly in its own code comments), and an `/api/queue`
  route handling the approve/deny POST. `AssistantLinkPanel.tsx` explicitly
  scopes itself to panel item 3 (sends + approvals log / the pending-queue
  slice) only — items 1, 2, and 4 (tasks, email-last-checked, routine-runs)
  remain unbuilt, exactly as this document specified they should stay until
  their own dependencies land.

**What this means for a future reader:** the "normative," "proposed,"
"unbuilt," and "deferred" language throughout the sections above described
reality accurately at merge time (2026-07-06, PR #28) but does not describe
the repo as it stands after this reconciliation. Where this reconciliation
section and an earlier section conflict on current build status, this
section wins. The earlier sections are kept unedited (beyond inline
pointers to this one) because their design rationale — why the shape looks
the way it does, why certain fields were left unspecified, why certain panel
items were deliberately not schema'd ahead of their real data source — is
still the accurate record of *why*, even where *whether it's built yet* has
moved on.
