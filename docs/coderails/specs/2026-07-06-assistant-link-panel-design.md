# ASSISTANT.LINK Panel + Approval-Queue Contract — Design

**Date:** 2026-07-06
**Status:** Contract normative (implementation-pending); panel spec approved by owner (D6)
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

This is a design/contract document only. No dashboard code is added or
modified by this spec — `skills/dashboard/` is untouched. The dashboard-side
Approve/Deny button is explicitly **deferred**: see [Deferred work](#deferred-work-approve-deny-button).

## Normativity note (read this first)

At the time of writing, `~/Github/assistant-agent`'s send-gate (WU2) has not
yet implemented `gate/surfaces/queue.ts` — there is no `QueueFileEntry` shape
in code to copy verbatim. Per the loop plan's fallback instruction, **this
document is the normative side of the contract**: WU2's `queue.ts` must
conform to the shape defined here, not the reverse. The exact shape was sent
to worker `wu2-gate` directly (SendMessage, sent alongside this PR) so their
implementation can consume it without re-deriving it. If WU2 ships a
divergent shape, that is a bug in WU2, not a stale doc here — this file should
be updated only if the owner explicitly re-resolves the contract, not
silently patched to match an implementation that drifted.

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
  [Deferred work](#deferred-work-approve-deny-button).

### Proposed collector shape

Modeled directly on `collectMemoryTrail` (`skills/dashboard/app/src/lib/collect/memoryTrail.ts`),
which is the existing collector closest in shape (list a directory, parse
each file, degrade to `[]` on any read error, never throw):

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

## Deferred work: Approve/Deny button

The dashboard-side button that flips a `QueueFileEntry.status` from
`pending` to `approved`/`denied` is explicitly deferred until coderails PR #25
(the dashboard's initial observability build) merges — confirmed merged as
of this writing (`378004e`, "Merge pull request #25 from
blueman82/observability/spec", an ancestor of `origin/main`'s current head
`d8fbdec`). Deferred here means: not built by this PR. A
follow-up PR, scoped separately, adds the button component, wires it to
`collectQueue`'s output, and performs the in-place JSON rewrite of the
target `<hash>.json` file's `status` field. That follow-up is out of scope
for sub-project 4 and is not tracked as an open task in this spec — it
should be picked up as its own dashboard-side work item when the dashboard's
own roadmap reaches it.

## Non-goals

- No dashboard code, component, or collector is implemented by this PR.
- No change to `skills/dashboard/` of any kind.
- No retroactive change to WU2's gate implementation — this document adapts
  to WU2's shipped shape only if the owner re-resolves a mismatch; it does
  not get silently rewritten to match drift.
