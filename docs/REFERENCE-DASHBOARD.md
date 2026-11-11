# Dashboard output and connection behavior

[Dashboard skill](REFERENCE-SKILLS.md#dashboard).

**Run output viewer.** In COMMAND DECK, select a run history row to show output in `OutputViewerPanel` (`skills/dashboard/app/src/components/OutputViewerPanel.tsx`).
An active run streams through SSE type `run-output` with `runId` and `chunk`.
The aggregator in `skills/dashboard/app/src/lib/collect/index.ts` adds this type.
The `skills/dashboard/app/src/lib/runOutputBus.ts` module publishes through local pub/sub on the same `/api/events` connection.

For a completed run, read full output one time through `GET /api/run/output` (`skills/dashboard/app/src/app/api/run/output/route.ts`).
The query parameters are `runId` and `token`. The result is `{status: "ok", output}`, `{status: "in-progress"}`, or `{status: "error", error}`.
The `in-progress` result uses 409 while the run has no `endedAt`. Continue to use the live SSE buffer.

**Context Trend.** The CONTEXT TREND panel (`skills/dashboard/app/src/components/ContextTrendPanel.tsx`) uses `collectContextTrend`.
The collector in `skills/dashboard/app/src/lib/collect/contextTrend.ts` reads all Coderails orchestrator transcripts in the projects directory.
That read is slower than the `activity` frame. A dedicated SSE type `context-trend` lets the KPI tiles in `SYSTEM VITALS` display when their collector finishes.

To add an SSE type, update two files:

- In `src/lib/collect/index.ts`, update `AggregatorEventName`, `AggregatorEventPayloadMap`, and the overloaded `emit` and listener signatures.
  If a type and payload disagree, compilation fails.

- In `src/hooks/useDashboardState.ts`, update `DashboardEvent`, `mergeDashboardEvent`, and `SSE_EVENT_NAMES`.
  The `for (const name of SSE_EVENT_NAMES)` loop sets up each `addEventListener`.
  With a name missing, the browser gets the frame but has no handler. It reports no error.
  The hook wiring test detects this. The `mergeDashboardEvent` unit test does not run registration.

The `src/app/api/events/route.ts` subscribe callback forwards `{event, data}` through the same `sseFrame` for all types.
No new branch is necessary. The `sharedContextTrendCache` uses stat-only checks across connections.
Without it, frames continue to work without that cache.

The `Snapshot.contextTrend` value has three possible values. For `undefined`, the panel shows "loading…". For `null`, it shows "unavailable" because it could not read the source.
A summary object supplies data. If the panel handles `undefined` like `null`, it flashes "unavailable" on each page load.

PR #265 corrected the same KPI regression. The `healthNotYetLoaded` value in `RailLeft.tsx` distinguishes "the collect has not resolved yet" from "the collector tried and could not populate this tile".

**Connection cleanup.** The `/api/events` endpoint releases the aggregator from the `abort` signal and `ReadableStream.cancel()`.
It also checks `if (request.signal?.aborted)` after setup.
The `cancel()` callback runs only if the response consumer cancels. It does not reliably run if the client disconnects.
A dropped connection used to keep a recursive `fs.watch` handle for each directory and keep the gates interval.

Launchd limits open files with `launchctl limit maxfiles` (256 on stock macOS). The shell soft limit does not apply.
At the limit, the server can accept TCP connections without responding to them.
