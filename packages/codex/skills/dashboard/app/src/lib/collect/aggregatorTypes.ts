import type { DashboardConfig } from "../config";
import type { RunRecord } from "../runlog";
import type { RunOutputBus, RunOutputEvent } from "../runOutputBus";
import type { BuildEntry } from "./builds";
import type { HealthTile } from "./health";
import type { PrGate, PrGateError } from "./prGates";
import type { QueueEntry } from "./queue";
import type { SessionInfo, LoopInfo } from "./sessions";
import type { ContextTrendSummary } from "./contextTrend";

export interface Snapshot {
  sessions: SessionInfo[];
  loops: LoopInfo[];
  gates: (PrGate | PrGateError)[];
  health: HealthTile[];
  runs: RunRecord[];
  queue: QueueEntry[];
  builds: BuildEntry[];
  // Three states, because contextTrend collects on its OWN frame (it streams
  // every coderails orchestrator transcript under projectsDir — far slower
  // than the activity slice —
  // so it must not gate the System Vitals / KPI tiles that ride the activity
  // frame):
  //   undefined = its collect hasn't resolved yet (loading)
  //   null      = source unreadable (no ~/.codex/projects), same degrade
  //               stance as the usage tiles — distinct from a real summary
  //               with zero sessions
  //   summary   = data
  contextTrend: ContextTrendSummary | null | undefined;
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
  activityReconcileMs?: number;
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

export type AggregatorEventName = "runs" | "gates" | "activity" | "context-trend" | "run-output";

// Maps each event name to the real payload type emitted alongside it, so a
// call site that emits/handles the wrong shape for a given name is a compile
// error rather than something only caught (or missed) at runtime — "data" was
// previously typed as bare `unknown` here.
export interface AggregatorEventPayloadMap {
  runs: RunRecord[];
  gates: (PrGate | PrGateError)[];
  activity: Pick<Snapshot, "sessions" | "loops" | "health" | "queue" | "builds">;
  // contextTrend collects on its own (slow) frame, decoupled from activity so
  // it never gates the KPI tiles. null = unreadable source; a summary = data.
  // The "loading" state is the absence of this frame (Snapshot.contextTrend
  // starts undefined), so this payload is never undefined.
  "context-trend": ContextTrendSummary | null;
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
  (event: "context-trend", data: AggregatorEventPayloadMap["context-trend"]): void;
  (event: "run-output", data: AggregatorEventPayloadMap["run-output"]): void;
}

export interface Aggregator {
  getSnapshot(): Snapshot;
  subscribe(listener: AggregatorEventListener): () => void;
  start(): void;
  stop(): void;
}
