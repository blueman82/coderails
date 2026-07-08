"use client";

import { useEffect, useReducer } from "react";
import type { SessionInfo, LoopInfo } from "@/lib/collect/sessions";
import type { PrGate, PrGateError } from "@/lib/collect/prGates";
import type { TrailEntry } from "@/lib/collect/memoryTrail";
import type { HealthTile } from "@/lib/collect/health";
import type { QueueEntry } from "@/lib/collect/queue";
import type { BuildEntry } from "@/lib/collect/builds";
import type { RunRecord } from "@/lib/runlog";
import type { RunOutputEvent } from "@/lib/runOutputBus";

// Mirrors the Snapshot shape from src/lib/collect/index.ts (type-only import
// there would be safe too, but the fields are re-declared here so this file
// has one single source for "what the client believes the wire shape is" —
// see the module-level comment below for why we don't import the real
// Snapshot/Aggregator types directly).
export interface DashboardSnapshot {
  sessions: SessionInfo[];
  loops: LoopInfo[];
  gates: (PrGate | PrGateError)[];
  trail: TrailEntry[];
  health: HealthTile[];
  runs: RunRecord[];
  queue: QueueEntry[];
  builds: BuildEntry[];
}

export type ActivitySlice = Pick<
  DashboardSnapshot,
  "sessions" | "loops" | "trail" | "health" | "queue" | "builds"
>;

export type DashboardEvent =
  | { event: "snapshot"; data: DashboardSnapshot }
  | { event: "activity"; data: ActivitySlice }
  | { event: "gates"; data: (PrGate | PrGateError)[] }
  | { event: "runs"; data: RunRecord[] }
  | { event: "run-output"; data: RunOutputEvent };

export type ConnectionStatus = "connecting" | "online" | "reconnecting";

// runOutput accumulates live chunks per runId, keyed by the same runId the "runs" slice's
// RunRecord carries — the output viewer panel appends to this map as "run-output" SSE frames
// arrive rather than re-fetching, matching the incremental-publish design in runOutputBus.ts.
// Defaults to {} (see initialDashboardState below); never reset on a later "snapshot"/"activity"
// frame, since those don't carry output and a reset would drop output for still-active runs.
export interface DashboardState {
  snapshot: DashboardSnapshot;
  status: ConnectionStatus;
  lastUpdate: number | null;
  runOutput: Record<string, string>;
}

const EMPTY_SNAPSHOT: DashboardSnapshot = {
  sessions: [],
  loops: [],
  gates: [],
  trail: [],
  health: [],
  runs: [],
  queue: [],
  builds: [],
};

export const initialDashboardState: DashboardState = {
  snapshot: EMPTY_SNAPSHOT,
  status: "connecting",
  lastUpdate: null,
  runOutput: {},
};

// Pure reducer: folds one incoming SSE frame into the running snapshot.
// `now` is threaded in (rather than read via Date.now() here) so the merge
// logic itself stays a pure function of its inputs for unit testing.
export function mergeDashboardEvent(
  state: DashboardState,
  incoming: DashboardEvent,
  now: number
): DashboardState {
  switch (incoming.event) {
    case "snapshot":
      return { ...state, snapshot: incoming.data, status: "online", lastUpdate: now };
    case "activity":
      return {
        ...state,
        snapshot: { ...state.snapshot, ...incoming.data },
        status: "online",
        lastUpdate: now,
      };
    case "gates":
      return {
        ...state,
        snapshot: { ...state.snapshot, gates: incoming.data },
        status: "online",
        lastUpdate: now,
      };
    case "runs": {
      // Prune runOutput entries for runs no longer in the server's run-history window (runsLimit
      // in lib/collect/index.ts, default 20) — otherwise this map only ever grows across a
      // dashboard session's lifetime, one entry per run that ever streamed output. The incoming
      // "runs" snapshot is the authoritative set worth keeping; anything absent from it has
      // rolled off the cap and its buffered output is no longer reachable via any run-history
      // row anyway.
      const keepRunIds = new Set(incoming.data.map((r) => r.runId));
      const prunedRunOutput = Object.fromEntries(
        Object.entries(state.runOutput).filter(([runId]) => keepRunIds.has(runId))
      );
      return {
        ...state,
        snapshot: { ...state.snapshot, runs: incoming.data },
        runOutput: prunedRunOutput,
        status: "online",
        lastUpdate: now,
      };
    }
    case "run-output":
      return {
        ...state,
        runOutput: {
          ...state.runOutput,
          [incoming.data.runId]: (state.runOutput[incoming.data.runId] ?? "") + incoming.data.chunk,
        },
        status: "online",
        lastUpdate: now,
      };
  }
}

export function markReconnecting(state: DashboardState): DashboardState {
  if (state.status === "reconnecting") return state;
  return { ...state, status: "reconnecting" };
}

function isGateError(gate: PrGate | PrGateError): gate is PrGateError {
  return "error" in gate;
}

export { isGateError };

// Picks the loop DIRECTIVES/hero should show. `loops[0]` alone isn't
// reliable: collectLoops (src/lib/collect/sessions.ts) treats every
// subdirectory under the loops base as a session, including non-loop dirs
// like a stray `.git`, and sortLoops only orders by slug — so index 0 can
// land on a 0-unit noise entry ahead of the loop that's actually running.
// Prefers an in-progress loop; falls back to any loop that has units at
// all; falls back to loops[0] (or undefined) so an all-noise list still
// resolves to *something* rather than throwing.
export function selectActiveLoop(loops: LoopInfo[]): LoopInfo | undefined {
  return (
    loops.find((l) => l.status === "in-progress") ?? loops.find((l) => l.workUnitsTotal > 0) ?? loops[0]
  );
}

// --- Formatters -------------------------------------------------------

// "HH:MM:SS" in the local zone, zero-padded.
export function formatClockTime(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

// Coarse "just now / Nm / Nh / Nd" relative age from an mtime (ms since
// epoch) to `now` (ms since epoch). Negative/zero deltas floor to "just now"
// rather than showing a negative number.
export function formatRelativeAge(mtimeMs: number, nowMs: number): string {
  const deltaMs = Math.max(0, nowMs - mtimeMs);
  const minutes = Math.floor(deltaMs / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return `${days}d`;
}

// "42S" / "3M10S" style duration from a start/end pair (ms since epoch),
// matching the mockup's compact run-history format.
export function formatDuration(startedAtMs: number, endedAtMs: number): string {
  const totalSeconds = Math.max(0, Math.round((endedAtMs - startedAtMs) / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0 ? `${minutes}M${seconds}S` : `${seconds}S`;
}

// Derives PASS/FAIL/RUNNING from a RunRecord's exit code: 0 = PASS, any other
// number = FAIL, undefined (still running / crashed before recording) = RUNNING.
export function runResultLabel(run: RunRecord): "PASS" | "FAIL" | "RUNNING" {
  if (run.exitCode === undefined) return "RUNNING";
  return run.exitCode === 0 ? "PASS" : "FAIL";
}

// "HH:MM" in the local zone from an epoch-ms timestamp, for run-history rows.
export function formatHHMM(epochMs: number): string {
  const date = new Date(epochMs);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

// --- Hook ---------------------------------------------------------------

export interface UseDashboardStateOptions {
  // Test-only seam: inject a fake EventSource-like object instead of the
  // real browser EventSource.
  createSource?: (url: string) => EventSourceLike;
  url?: string;
}

export interface EventSourceLike {
  addEventListener(type: string, listener: (ev: MessageEvent) => void): void;
  close(): void;
  onerror?: ((ev: Event) => void) | null;
}

const SSE_EVENT_NAMES: DashboardEvent["event"][] = ["snapshot", "activity", "gates", "runs", "run-output"];

export function useDashboardState(options: UseDashboardStateOptions = {}): DashboardState {
  const { createSource, url = "/api/events" } = options;
  const [state, dispatch] = useReducer(
    (s: DashboardState, action: DashboardEvent | { event: "reconnecting" }) =>
      action.event === "reconnecting" ? markReconnecting(s) : mergeDashboardEvent(s, action, Date.now()),
    initialDashboardState
  );

  // Connects exactly once per mount, intentionally ignoring later changes to
  // createSource/url (a caller swapping the SSE endpoint mid-life is not a
  // supported scenario — this hook always points at the one dashboard
  // stream for the component's lifetime).
  useEffect(() => {
    const makeSource = createSource ?? ((u: string) => new EventSource(u) as unknown as EventSourceLike);
    const source = makeSource(url);

    for (const name of SSE_EVENT_NAMES) {
      source.addEventListener(name, (ev: MessageEvent) => {
        try {
          const data = JSON.parse(ev.data);
          dispatch({ event: name, data } as DashboardEvent);
        } catch {
          // malformed frame — drop it, keep last-good state.
        }
      });
    }
    source.onerror = () => {
      dispatch({ event: "reconnecting" });
    };

    return () => source.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return state;
}
