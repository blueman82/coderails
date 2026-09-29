import { watch, type FSWatcher } from "node:fs";
import { readRuns, reconcileOrphanRunsInLedger } from "../runlog";
import { runOutputBus as defaultRunOutputBus, type RunOutputEvent } from "../runOutputBus";
import { collectBuilds } from "./builds";
import { collectHealth } from "./health";
import { collectPrGates, type PrGate, type PrGateError } from "./prGates";
import { collectQueue } from "./queue";
import { collectSessions, collectLoops } from "./sessions";
import { collectContextTrend } from "./contextTrend";
import { ageSessions, sortGates, sortLoops, sortSessions, sourceFingerprint, type LocalSource } from "./aggregatorHelpers";
import type { Snapshot, AggregatorDeps, AggregatorEventName, AggregatorEventPayloadMap, AggregatorEventListener, Aggregator } from "./aggregatorTypes";

export { NATIVE_SESSION_ID, MAX_TRACE_PAGE, nativeRouteDefaults, validSourceRef, sourceInsideRoot } from "./nativeRoute";
export type { NativeRouteDeps } from "./nativeRoute";
export type { Snapshot, AggregatorDeps, AggregatorEventName, AggregatorEventPayloadMap, AggregatorEventListener, Aggregator } from "./aggregatorTypes";

const DEFAULT_RUNS_LIMIT = 20;
const DEFAULT_QUEUE_LIMIT = 50;
const DEFAULT_GATES_POLL_MS = 30_000;
const ACTIVITY_RECONCILE_MS = 5_000;
const DEFAULT_ACTIVITY_DEBOUNCE_MS = 2_000;
const GATES_RUNS_DEBOUNCE_MS = 3_000;
// Rolling usage/cost windows and the daily hook tile need a clock even when
// source metadata is unchanged. This cadence does not re-read other slices.
const HEALTH_CLOCK_REFRESH_MS = 60_000;

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
  const activityReconcileMs = deps.activityReconcileMs ?? ACTIVITY_RECONCILE_MS;
  const activityDebounceMs = deps.activityDebounceMs ?? DEFAULT_ACTIVITY_DEBOUNCE_MS;
  const onError = deps.onError ?? (() => {});
  const runOutputBus = deps.runOutputBus ?? defaultRunOutputBus;

  const listeners = new Set<AggregatorEventListener>();
  const watchers: FSWatcher[] = [];
  let gatesTimer: ReturnType<typeof setInterval> | undefined;
  let activityTimer: ReturnType<typeof setInterval> | undefined;
  let gatesDebounceTimer: ReturnType<typeof setTimeout> | undefined;
  let activityDebounceTimer: ReturnType<typeof setTimeout> | undefined;
  let contextTrendDebounceTimer: ReturnType<typeof setTimeout> | undefined;
  let unsubscribeRunOutput: (() => void) | undefined;
  let closed = false;
  let gateAbort: AbortController | undefined;
  const fingerprints = new Map<LocalSource, string>();
  let lastHealthClockRefresh = Date.now();
  let healthRevision = 0;

  function singleFlight(work: () => Promise<void>): () => void {
    let active = false;
    let dirty = false;
    const run = (): void => {
      if (closed) return;
      if (active) { dirty = true; return; }
      active = true;
      void work().finally(() => {
        active = false;
        if (dirty && !closed) { dirty = false; run(); }
      });
    };
    return run;
  }

  let snapshot: Snapshot = {
    sessions: [],
    loops: [],
    gates: [],
    health: [],
    runs: [],
    queue: [],
    builds: [],
    // undefined = the contextTrend collect (its own frame) hasn't resolved yet.
    // The panel renders "loading" for undefined, "unavailable" only for null.
    contextTrend: undefined,
  };

  // Overloaded the same way as AggregatorEventListener so each call site
  // below is checked against that event name's real payload type, not a
  // catch-all `unknown`.
  function emit(event: "runs", data: AggregatorEventPayloadMap["runs"]): void;
  function emit(event: "gates", data: AggregatorEventPayloadMap["gates"]): void;
  function emit(event: "activity", data: AggregatorEventPayloadMap["activity"]): void;
  function emit(event: "context-trend", data: AggregatorEventPayloadMap["context-trend"]): void;
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
    Pick<Snapshot, "sessions" | "loops" | "health" | "queue" | "builds"> & { healthRevision: number }
  > {
    const sessions = sortSessions(safeCall("sessions", () => collectSessions(deps.projectsDir, Date.now()), []));
    const loops = sortLoops(safeCall("loops", () => collectLoops(deps.loopsDir), []));
    // health reads usage transcripts (I/O-bound, hence async) and has no
    // dedicated fs signal of its own to watch beyond the projects dir already
    // watched for sessions — it rides along with the activity slice rather
    // than getting its own timer. loopsDir is passed through so the cost
    // tiles (costWeek/costMonth) read sibling retro.json files from the same
    // tree collectLoops walks.
    const revision = ++healthRevision;
    const health = await safeCallAsync(
      "health",
      () => collectHealth({ projectsDir: deps.projectsDir, loopsDir: deps.loopsDir }),
      []
    );
    const queue = deps.queueDir ? safeCall("queue", () => collectQueue(deps.queueDir!, queueLimit), []) : [];
    const builds = deps.buildsDir ? safeCall("builds", () => collectBuilds(deps.buildsDir!), []) : [];
    return { sessions, loops, health, queue, builds, healthRevision: revision };
  }

  const refreshActivity = singleFlight(async (): Promise<void> => {
    const { healthRevision: revision, ...collected } = await collectActivitySlice();
    if (closed) return;
    const activity = {
      ...collected,
      sessions: ageSessions(collected.sessions, Date.now()),
      health: revision === healthRevision ? collected.health : snapshot.health,
    };
    snapshot = { ...snapshot, ...activity };
    emit("activity", activity);
  });

  const refreshClockHealth = singleFlight(async (): Promise<void> => {
    const revision = ++healthRevision;
    const health = await safeCallAsync(
      "health",
      () => collectHealth({ projectsDir: deps.projectsDir, loopsDir: deps.loopsDir }),
      []
    );
    if (closed || revision !== healthRevision) return;
    snapshot = { ...snapshot, health };
    emit("activity", {
      sessions: snapshot.sessions, loops: snapshot.loops, health,
      queue: snapshot.queue, builds: snapshot.builds,
    });
  });

  // contextTrend streams every coderails orchestrator transcript under
  // projectsDir (the collector filters to slug-matching project dirs, and
  // reads only top-level session files, not subagent transcripts) — far slower than
  // the activity slice — so it collects on its OWN frame and never gates the
  // System Vitals / KPI tiles that ride the activity frame. A shared cache
  // (explicit or module-scope) makes every later refresh a stat() sweep plus a
  // re-parse of only the files that actually changed.
  const refreshContextTrend = singleFlight(async (): Promise<void> => {
    const contextTrend = await safeCallAsync(
      "contextTrend",
      () => collectContextTrend(deps.projectsDir, { cache: deps.contextTrendCache }),
      null
    );
    if (closed) return;
    snapshot = { ...snapshot, contextTrend };
    emit("context-trend", contextTrend);
  });

  const refreshGates = singleFlight(async (): Promise<void> => {
    let gates: (PrGate | PrGateError)[];
    const controller = new AbortController();
    gateAbort = controller;
    try {
      gates = sortGates(await collectPrGates(deps.cfg, undefined, controller.signal));
    } catch (err) {
      if (!closed) onError("gates", err);
      return;
    } finally {
      if (gateAbort === controller) gateAbort = undefined;
    }
    if (closed) return;
    snapshot = { ...snapshot, gates };
    emit("gates", gates);
  });

  function refreshRuns(): void {
    if (closed) return;
    const runs = safeCall("runs", () => readRuns(runsLimit, { runsDir: deps.runsDir }), []);
    snapshot = { ...snapshot, runs };
    emit("runs", runs);
  }

  function scheduleActivityRefresh(): void {
    if (closed) return;
    if (activityDebounceTimer) clearTimeout(activityDebounceTimer);
    activityDebounceTimer = setTimeout(() => void refreshActivity(), activityDebounceMs);
  }

  function scheduleContextTrendRefresh(): void {
    if (closed) return;
    if (contextTrendDebounceTimer) clearTimeout(contextTrendDebounceTimer);
    contextTrendDebounceTimer = setTimeout(() => void refreshContextTrend(), activityDebounceMs);
  }

  function scheduleGatesRefresh(): void {
    if (closed) return;
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

  function reconcileLocalSources(): void {
    const sources: [LocalSource, string | undefined][] = [
      ["projects", deps.projectsDir], ["loops", deps.loopsDir], ["runs", deps.runsDir],
      ["queue", deps.queueDir], ["builds", deps.buildsDir],
    ];
    for (const [source, dir] of sources) {
      if (!dir) continue;
      const current = sourceFingerprint(dir, source);
      if (current === fingerprints.get(source)) continue;
      fingerprints.set(source, current);
      if (source === "runs") { refreshRuns(); scheduleGatesRefresh(); }
      else {
        scheduleActivityRefresh();
        if (source === "projects") scheduleContextTrendRefresh();
      }
    }
    const aged = ageSessions(snapshot.sessions, Date.now());
    if (aged.some((session, index) => session !== snapshot.sessions[index])) {
      snapshot = { ...snapshot, sessions: aged };
      emit("activity", {
        sessions: aged, loops: snapshot.loops, health: snapshot.health,
        queue: snapshot.queue, builds: snapshot.builds,
      });
    }
    if (Date.now() - lastHealthClockRefresh >= HEALTH_CLOCK_REFRESH_MS) {
      lastHealthClockRefresh = Date.now();
      refreshClockHealth();
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
      if (closed) return;
      // Settle any runs orphaned by a server process that died mid-flight
      // (crash loop, supervisor restart, kill) before its in-process
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
      // contextTrend is much slower (streams every coderails orchestrator
      // transcript) so it runs on
      // its own frame, fired here without blocking start() and independent of
      // refreshActivity — the KPI tiles must not wait on it.
      void refreshContextTrend();

      watchDir(deps.projectsDir, () => { scheduleActivityRefresh(); scheduleContextTrendRefresh(); });
      watchDir(deps.loopsDir, scheduleActivityRefresh);
      if (deps.runsDir) watchDir(deps.runsDir, () => { refreshRuns(); scheduleGatesRefresh(); });
      if (deps.queueDir) watchDir(deps.queueDir, scheduleActivityRefresh);
      if (deps.buildsDir) watchDir(deps.buildsDir, scheduleActivityRefresh);

      for (const [source, dir] of [
        ["projects", deps.projectsDir], ["loops", deps.loopsDir], ["runs", deps.runsDir],
        ["queue", deps.queueDir], ["builds", deps.buildsDir],
      ] as [LocalSource, string | undefined][]) {
        if (dir) fingerprints.set(source, sourceFingerprint(dir, source));
      }

      void refreshGates();
      gatesTimer = setInterval(() => { if (listeners.size) void refreshGates(); }, gatesPollMs);
      activityTimer = setInterval(() => { if (listeners.size) reconcileLocalSources(); }, activityReconcileMs);

      unsubscribeRunOutput = runOutputBus.subscribe(onRunOutput);
    },

    stop(): void {
      closed = true;
      gateAbort?.abort();
      for (const watcher of watchers) watcher.close();
      watchers.length = 0;
      if (gatesTimer) clearInterval(gatesTimer);
      if (activityTimer) clearInterval(activityTimer);
      if (gatesDebounceTimer) clearTimeout(gatesDebounceTimer);
      if (activityDebounceTimer) clearTimeout(activityDebounceTimer);
      if (contextTrendDebounceTimer) clearTimeout(contextTrendDebounceTimer);
      unsubscribeRunOutput?.();
      unsubscribeRunOutput = undefined;
      listeners.clear();
    },
  };
}
