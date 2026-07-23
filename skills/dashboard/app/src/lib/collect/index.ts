import { watch, type FSWatcher } from "node:fs";
import type { DashboardConfig } from "../config";
import { readRuns, reconcileOrphanRunsInLedger, type RunRecord } from "../runlog";
import { runOutputBus as defaultRunOutputBus, type RunOutputBus, type RunOutputEvent } from "../runOutputBus";
import { collectBuilds, type BuildEntry } from "./builds";
import { collectHealth, type HealthTile } from "./health";
import { collectPrGates, type PrGate, type PrGateError } from "./prGates";
import { collectQueue, type QueueEntry } from "./queue";
import { collectSessions, collectLoops, type SessionInfo, type LoopInfo } from "./sessions";
import { collectContextTrend, type ContextTrendSummary } from "./contextTrend";

export interface Snapshot {
  sessions: SessionInfo[];
  loops: LoopInfo[];
  gates: (PrGate | PrGateError)[];
  health: HealthTile[];
  runs: RunRecord[];
  queue: QueueEntry[];
  builds: BuildEntry[];
  // null = source unreadable (no ~/.claude/projects), same degrade stance as
  // the usage tiles — distinct from a real summary with zero sessions.
  contextTrend: ContextTrendSummary | null;
}

export interface AggregatorDeps {
  cfg: DashboardConfig;
  projectsDir: string;
  loopsDir: string;
  runsDir?: string;
  queueDir?: string;
  buildsDir?: string;
  runsLimit?: number;
  queueLimit?: number;
  gatesPollMs?: number;
  activityDebounceMs?: number;
  onError?: (source: string, err: unknown) => void;
  // Test-only seam: inject a fake bus instead of the process-wide singleton
  // in ../runOutputBus.
  runOutputBus?: RunOutputBus;
  // Optional cache for contextTrend. Passing an explicit cache ensures it
  // persists across SSE connections and serves transcripts with stat-only
  // re-validation rather than re-parsing. Critical for production where
  // module-scope caches may be less reliable due to bundling.
  contextTrendCache?: import("./contextTrend").ContextTrendFileCache;
}

export type AggregatorEventName = "runs" | "gates" | "activity" | "run-output";

// Maps each event name to the real payload type emitted alongside it, so a
// call site that emits/handles the wrong shape for a given name is a compile
// error rather than something only caught (or missed) at runtime — "data" was
// previously typed as bare `unknown` here.
export interface AggregatorEventPayloadMap {
  runs: RunRecord[];
  gates: (PrGate | PrGateError)[];
  activity: Pick<Snapshot, "sessions" | "loops" | "health" | "queue" | "builds" | "contextTrend">;
  "run-output": RunOutputEvent;
}

// A single listener handles every event name (the SSE route registers one
// listener and forwards {event, data} straight into an SSE frame), so the
// listener signature is a function overloaded per event name — that keeps
// "gates" paired only with its own payload type (not a union of every
// payload type, which `(event: AggregatorEventName, data: X | Y | Z) => void`
// would silently allow) a compile error at both emit() and subscribe() call
// sites for a mismatched pairing.
export interface AggregatorEventListener {
  (event: "runs", data: AggregatorEventPayloadMap["runs"]): void;
  (event: "gates", data: AggregatorEventPayloadMap["gates"]): void;
  (event: "activity", data: AggregatorEventPayloadMap["activity"]): void;
  (event: "run-output", data: AggregatorEventPayloadMap["run-output"]): void;
}

export interface Aggregator {
  getSnapshot(): Snapshot;
  subscribe(listener: AggregatorEventListener): () => void;
  start(): void;
  stop(): void;
}

const DEFAULT_RUNS_LIMIT = 20;
const DEFAULT_QUEUE_LIMIT = 50;
const DEFAULT_GATES_POLL_MS = 30_000;
const DEFAULT_ACTIVITY_DEBOUNCE_MS = 2_000;
const GATES_RUNS_DEBOUNCE_MS = 3_000;

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
// the sessions/loops dirs (debounced) plus a runs-log tap, and a
// setInterval gh poll for gates. Every collector call is wrapped so a throw
// degrades that slice of the snapshot rather than killing the aggregator —
// callers (the SSE route) never see an aggregator-level exception, and
// `onError` is invoked (log once) instead.
export function createAggregator(deps: AggregatorDeps): Aggregator {
  const runsLimit = deps.runsLimit ?? DEFAULT_RUNS_LIMIT;
  const queueLimit = deps.queueLimit ?? DEFAULT_QUEUE_LIMIT;
  const gatesPollMs = deps.gatesPollMs ?? DEFAULT_GATES_POLL_MS;
  const activityDebounceMs = deps.activityDebounceMs ?? DEFAULT_ACTIVITY_DEBOUNCE_MS;
  const onError = deps.onError ?? (() => {});
  const runOutputBus = deps.runOutputBus ?? defaultRunOutputBus;

  const listeners = new Set<AggregatorEventListener>();
  const watchers: FSWatcher[] = [];
  let gatesTimer: ReturnType<typeof setInterval> | undefined;
  let gatesDebounceTimer: ReturnType<typeof setTimeout> | undefined;
  let activityDebounceTimer: ReturnType<typeof setTimeout> | undefined;
  let unsubscribeRunOutput: (() => void) | undefined;

  let snapshot: Snapshot = {
    sessions: [],
    loops: [],
    gates: [],
    health: [],
    runs: [],
    queue: [],
    builds: [],
    contextTrend: null,
  };

  // Overloaded the same way as AggregatorEventListener so each call site
  // below is checked against that event name's real payload type, not a
  // catch-all `unknown`.
  function emit(event: "runs", data: AggregatorEventPayloadMap["runs"]): void;
  function emit(event: "gates", data: AggregatorEventPayloadMap["gates"]): void;
  function emit(event: "activity", data: AggregatorEventPayloadMap["activity"]): void;
  function emit(event: "run-output", data: AggregatorEventPayloadMap["run-output"]): void;
  function emit(event: AggregatorEventName, data: AggregatorEventPayloadMap[AggregatorEventName]): void {
    for (const listener of listeners) listener(event as never, data as never);
  }

  function onRunOutput(event: RunOutputEvent): void {
    emit("run-output", event);
  }

  function safeCall<T>(source: string, fn: () => T, fallback: T): T {
    try {
      return fn();
    } catch (err) {
      onError(source, err);
      return fallback;
    }
  }

  async function safeCallAsync<T>(source: string, fn: () => Promise<T>, fallback: T): Promise<T> {
    try {
      return await fn();
    } catch (err) {
      onError(source, err);
      return fallback;
    }
  }

  async function collectActivitySlice(): Promise<
    Pick<Snapshot, "sessions" | "loops" | "health" | "queue" | "builds" | "contextTrend">
  > {
    const sessions = sortSessions(safeCall("sessions", () => collectSessions(deps.projectsDir, Date.now()), []));
    const loops = sortLoops(safeCall("loops", () => collectLoops(deps.loopsDir), []));
    // health reads usage transcripts (I/O-bound, hence async) and has no
    // dedicated fs signal of its own to watch beyond the projects dir already
    // watched for sessions — it rides along with the activity slice rather
    // than getting its own timer. loopsDir is passed through so the cost
    // tiles (costWeek/costMonth) read sibling retro.json files from the same
    // tree collectLoops walks.
    const health = await safeCallAsync(
      "health",
      () => collectHealth({ projectsDir: deps.projectsDir, loopsDir: deps.loopsDir }),
      []
    );
    const queue = deps.queueDir ? safeCall("queue", () => collectQueue(deps.queueDir!, queueLimit), []) : [];
    const builds = deps.buildsDir ? safeCall("builds", () => collectBuilds(deps.buildsDir!), []) : [];
    return { sessions, loops, health, queue, builds };
  }

  async function refreshActivity(): Promise<void> {
    const activity = await collectActivitySlice();
    snapshot = { ...snapshot, ...activity };
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
    activityDebounceTimer = setTimeout(() => void refreshActivity(), activityDebounceMs);
  }

  function scheduleGatesRefresh(): void {
    if (gatesDebounceTimer) clearTimeout(gatesDebounceTimer);
    gatesDebounceTimer = setTimeout(() => void refreshGates(), GATES_RUNS_DEBOUNCE_MS);
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
      // Settle any runs orphaned by a server process that died mid-flight
      // (crashloop, launchctl restart, kill) before its in-process
      // child.on("exit") handler could write the finish line — must run
      // BEFORE the readRuns below, and unguarded (no "ran once" flag):
      // start() runs once per SSE connection, building a fresh aggregator
      // each time, so a module-scope "ran once" guard would silently stop
      // the reconciler from running on the second and all later
      // connections — any orphan created after the first connection would
      // then never be settled. Idempotency (a second pass sees the
      // synthetic finish line already appended and no-ops) is what makes
      // running it unguarded on every call both safe and correct.
      safeCall("runs", () => { reconcileOrphanRunsInLedger({ runsDir: deps.runsDir }); return undefined; }, undefined);
      const runs = safeCall("runs", () => readRuns(runsLimit, { runsDir: deps.runsDir }), []);
      snapshot = { ...snapshot, runs };
      // Initial activity collect (sessions/loops/health) is async (health
      // now reads usage transcripts) — fire it without blocking start(), same
      // pattern as refreshGates below; the snapshot fills in once it resolves
      // and "activity" listeners are notified same as any later refresh.
      void refreshActivity();

      watchDir(deps.projectsDir, scheduleActivityRefresh);
      watchDir(deps.loopsDir, scheduleActivityRefresh);
      if (deps.runsDir) watchDir(deps.runsDir, () => { refreshRuns(); scheduleGatesRefresh(); });
      if (deps.queueDir) watchDir(deps.queueDir, scheduleActivityRefresh);
      if (deps.buildsDir) watchDir(deps.buildsDir, scheduleActivityRefresh);

      void refreshGates();
      gatesTimer = setInterval(() => void refreshGates(), gatesPollMs);

      unsubscribeRunOutput = runOutputBus.subscribe(onRunOutput);
    },

    stop(): void {
      for (const watcher of watchers) watcher.close();
      watchers.length = 0;
      if (gatesTimer) clearInterval(gatesTimer);
      if (gatesDebounceTimer) clearTimeout(gatesDebounceTimer);
      if (activityDebounceTimer) clearTimeout(activityDebounceTimer);
      unsubscribeRunOutput?.();
      unsubscribeRunOutput = undefined;
      listeners.clear();
    },
  };
}
