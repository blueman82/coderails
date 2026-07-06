import { watch, type FSWatcher } from "node:fs";
import type { DashboardConfig } from "../config";
import { readRuns, type RunRecord } from "../runlog";
import { collectHealth, type HealthTile } from "./health";
import { collectMemoryTrail, type TrailEntry } from "./memoryTrail";
import { collectPrGates, type PrGate, type PrGateError } from "./prGates";
import { collectQueue, type QueueEntry } from "./queue";
import { collectSessions, collectLoops, type SessionInfo, type LoopInfo } from "./sessions";

export interface Snapshot {
  sessions: SessionInfo[];
  loops: LoopInfo[];
  gates: (PrGate | PrGateError)[];
  trail: TrailEntry[];
  health: HealthTile[];
  runs: RunRecord[];
  queue: QueueEntry[];
}

export interface AggregatorDeps {
  cfg: DashboardConfig;
  projectsDir: string;
  loopsDir: string;
  runsDir?: string;
  queueDir?: string;
  memoryTrailLimit?: number;
  runsLimit?: number;
  queueLimit?: number;
  gatesPollMs?: number;
  activityDebounceMs?: number;
  onError?: (source: string, err: unknown) => void;
}

export type AggregatorEventName = "runs" | "gates" | "activity";

export interface Aggregator {
  getSnapshot(): Snapshot;
  subscribe(listener: (event: AggregatorEventName, data: unknown) => void): () => void;
  start(): void;
  stop(): void;
}

const DEFAULT_TRAIL_LIMIT = 20;
const DEFAULT_RUNS_LIMIT = 20;
const DEFAULT_GATES_POLL_MS = 120_000;
const DEFAULT_ACTIVITY_DEBOUNCE_MS = 2_000;

function sortSessions(sessions: SessionInfo[]): SessionInfo[] {
  return [...sessions].sort((a, b) => b.lastActivity - a.lastActivity);
}

function sortLoops(loops: LoopInfo[]): LoopInfo[] {
  return [...loops].sort((a, b) => a.slug.localeCompare(b.slug));
}

function isGateError(gate: PrGate | PrGateError): gate is PrGateError {
  return "error" in gate;
}

// Sorted by repo, then PR number (error entries carry no number — they sort
// first within their repo, since a missing/unreachable repo has no number to
// compare).
function sortGates(gates: (PrGate | PrGateError)[]): (PrGate | PrGateError)[] {
  return [...gates].sort((a, b) => {
    const repoCmp = a.repo.localeCompare(b.repo);
    if (repoCmp !== 0) return repoCmp;
    const aNum = isGateError(a) ? -1 : a.number;
    const bNum = isGateError(b) ? -1 : b.number;
    return aNum - bNum;
  });
}

// Builds the aggregator: an in-memory snapshot kept current by fs.watch on
// the sessions/loops/memory-trail dirs (debounced) plus a runs-log tap, and a
// setInterval gh poll for gates. Every collector call is wrapped so a throw
// degrades that slice of the snapshot rather than killing the aggregator —
// callers (the SSE route) never see an aggregator-level exception, and
// `onError` is invoked (log once) instead.
export function createAggregator(deps: AggregatorDeps): Aggregator {
  const trailLimit = deps.memoryTrailLimit ?? DEFAULT_TRAIL_LIMIT;
  const runsLimit = deps.runsLimit ?? DEFAULT_RUNS_LIMIT;
  const gatesPollMs = deps.gatesPollMs ?? DEFAULT_GATES_POLL_MS;
  const activityDebounceMs = deps.activityDebounceMs ?? DEFAULT_ACTIVITY_DEBOUNCE_MS;
  const onError = deps.onError ?? (() => {});

  const listeners = new Set<(event: AggregatorEventName, data: unknown) => void>();
  const watchers: FSWatcher[] = [];
  let gatesTimer: ReturnType<typeof setInterval> | undefined;
  let activityDebounceTimer: ReturnType<typeof setTimeout> | undefined;

  let snapshot: Snapshot = {
    sessions: [],
    loops: [],
    gates: [],
    trail: [],
    health: [],
    runs: [],
  };

  function emit(event: AggregatorEventName, data: unknown): void {
    for (const listener of listeners) listener(event, data);
  }

  function safeCall<T>(source: string, fn: () => T, fallback: T): T {
    try {
      return fn();
    } catch (err) {
      onError(source, err);
      return fallback;
    }
  }

  function collectActivitySlice(): Pick<Snapshot, "sessions" | "loops" | "trail" | "health"> {
    const sessions = sortSessions(safeCall("sessions", () => collectSessions(deps.projectsDir, Date.now()), []));
    const loops = sortLoops(safeCall("loops", () => collectLoops(deps.loopsDir), []));
    const trail = safeCall("trail", () => collectMemoryTrail(deps.cfg.memoryPaths, trailLimit), []);
    // health has no dedicated fs signal to watch (usage tiles are always
    // unavailable; hooksFired/lintFindings are cheap to recompute) — it
    // rides along with the activity slice rather than getting its own timer.
    const health = safeCall("health", () => collectHealth(), []);
    return { sessions, loops, trail, health };
  }

  function refreshActivity(): void {
    const { health, ...activity } = collectActivitySlice();
    snapshot = { ...snapshot, ...activity, health };
    emit("activity", activity);
  }

  async function refreshGates(): Promise<void> {
    let gates: (PrGate | PrGateError)[];
    try {
      gates = sortGates(await collectPrGates(deps.cfg));
    } catch (err) {
      onError("gates", err);
      return;
    }
    snapshot = { ...snapshot, gates };
    emit("gates", gates);
  }

  function refreshRuns(): void {
    const runs = safeCall("runs", () => readRuns(runsLimit, { runsDir: deps.runsDir }), []);
    snapshot = { ...snapshot, runs };
    emit("runs", runs);
  }

  function scheduleActivityRefresh(): void {
    if (activityDebounceTimer) clearTimeout(activityDebounceTimer);
    activityDebounceTimer = setTimeout(refreshActivity, activityDebounceMs);
  }

  function watchDir(dir: string, onChange: () => void): void {
    try {
      const watcher = watch(dir, { recursive: true }, onChange);
      watcher.on("error", (err) => onError("watch", err));
      watchers.push(watcher);
    } catch (err) {
      // Missing/unwatchable dir degrades to "no activity signal from this
      // source" rather than throwing — the initial collect above already
      // handles a missing dir by returning an empty slice.
      onError("watch", err);
    }
  }

  return {
    getSnapshot(): Snapshot {
      return snapshot;
    },

    subscribe(listener) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },

    start(): void {
      const activity = collectActivitySlice();
      const runs = safeCall("runs", () => readRuns(runsLimit, { runsDir: deps.runsDir }), []);
      snapshot = { ...snapshot, ...activity, runs };

      watchDir(deps.projectsDir, scheduleActivityRefresh);
      watchDir(deps.loopsDir, scheduleActivityRefresh);
      for (const dir of deps.cfg.memoryPaths) watchDir(dir, scheduleActivityRefresh);
      if (deps.runsDir) watchDir(deps.runsDir, refreshRuns);

      void refreshGates();
      gatesTimer = setInterval(() => void refreshGates(), gatesPollMs);
    },

    stop(): void {
      for (const watcher of watchers) watcher.close();
      watchers.length = 0;
      if (gatesTimer) clearInterval(gatesTimer);
      if (activityDebounceTimer) clearTimeout(activityDebounceTimer);
      listeners.clear();
    },
  };
}
