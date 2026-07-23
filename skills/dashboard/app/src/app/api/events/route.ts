import { homedir } from "node:os";
import { join } from "node:path";
import { loadConfig, type DashboardConfig } from "../../../lib/config";
import { createAggregator, type Aggregator, type AggregatorDeps } from "../../../lib/collect";
import { isLocalOrigin } from "../../../lib/requestGuard";
import type { ContextTrendFileCache } from "../../../lib/collect/contextTrend";

const DEFAULT_PROJECTS_DIR = join(homedir(), ".claude", "projects");
const DEFAULT_LOOPS_DIR = join(homedir(), ".claude", "agentic-loop");
const DEFAULT_RUNS_DIR = join(homedir(), ".claude", "coderails-dashboard", "runs");
const DEFAULT_QUEUE_DIR = join(homedir(), ".claude", "coderails-dashboard", "approvals");
const DEFAULT_BUILDS_DIR = join(homedir(), ".claude", "coderails-dashboard", "builds");

// Shared cache for contextTrend across all SSE connections. The collectors
// stream transcript files (hundreds to thousands) and cache their parse
// results keyed by (mtime, size). Sharing this cache across connections
// means subsequent connections get a stat()-only pass instead of re-parsing.
// This is especially critical for contextTrend in production, where module
// scope caches can be less reliable due to bundling: explicitly passing a
// reference ensures it persists across requests.
const sharedContextTrendCache: ContextTrendFileCache = new Map();

function sseFrame(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

export interface EventsHandlerDeps {
  config: DashboardConfig;
  createAggregatorImpl?: (deps: AggregatorDeps) => Aggregator;
  projectsDir?: string;
  loopsDir?: string;
  runsDir?: string;
  queueDir?: string;
  buildsDir?: string;
  gatesPollMs?: number;
  activityDebounceMs?: number;
}

// Builds the GET /api/events handler. NEVER writes the CSRF token into any
// event or response body — the security-critical property that a hostile
// tab's EventSource must not be able to recover it (see runlog.ts's
// mintToken comment: the token reaches the page exclusively via
// server-render). The stream itself never dies on a collector throw — each
// collector call inside the aggregator is individually wrapped, and any
// aggregator-level error here is logged once and the connection is simply
// closed rather than throwing past the framework.
export function createEventsHandler(deps: EventsHandlerDeps) {
  const createAggregatorImpl = deps.createAggregatorImpl ?? createAggregator;

  return function GET(request: Request): Response {
    if (!isLocalOrigin(request)) {
      return new Response(JSON.stringify({ error: "forbidden" }), {
        status: 403,
        headers: { "content-type": "application/json" },
      });
    }

    const aggregator = createAggregatorImpl({
      cfg: deps.config,
      projectsDir: deps.projectsDir ?? DEFAULT_PROJECTS_DIR,
      loopsDir: deps.loopsDir ?? DEFAULT_LOOPS_DIR,
      runsDir: deps.runsDir ?? DEFAULT_RUNS_DIR,
      queueDir: deps.queueDir ?? DEFAULT_QUEUE_DIR,
      buildsDir: deps.buildsDir ?? DEFAULT_BUILDS_DIR,
      gatesPollMs: deps.gatesPollMs,
      activityDebounceMs: deps.activityDebounceMs,
      contextTrendCache: sharedContextTrendCache,
      onError: (source, err) => {
        console.error(`[api/events] collector "${source}" failed:`, err);
      },
    });

    let unsubscribe: (() => void) | undefined;

    // Teardown must be idempotent AND reachable from more than one path.
    //
    // ReadableStream.cancel() only fires when the response *consumer* cancels.
    // A client that simply goes away (tab closed, network drop, curl killed)
    // does not reliably trigger it, so relying on cancel() alone leaked the
    // whole aggregator per abandoned connection: a recursive fs.watch handle on
    // each of projectsDir/loopsDir/runsDir/queueDir/buildsDir, plus the gates
    // setInterval, never released.
    //
    // That leak is fatal under launchd, which caps this process at
    // `launchctl limit maxfiles` = 256 — not the shell's soft limit. A handful
    // of page loads exhausts the descriptor table; after that the server still
    // accepts TCP but cannot open files or watches, and it wedges: HTTP 000 on
    // every route, no SSE frames, panels stuck on "loading…".
    //
    // So we tear down from request abort as well, and guard with a flag because
    // both paths can fire for the same connection.
    let released = false;
    const release = () => {
      if (released) return;
      released = true;
      unsubscribe?.();
      aggregator.stop();
    };

    request.signal?.addEventListener("abort", release, { once: true });

    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        const encoder = new TextEncoder();
        aggregator.start();
        controller.enqueue(encoder.encode(sseFrame("snapshot", aggregator.getSnapshot())));
        unsubscribe = aggregator.subscribe((event, data) => {
          try {
            controller.enqueue(encoder.encode(sseFrame(event, data)));
          } catch {
            // controller already closed (client disconnected mid-emit) —
            // nothing to do, release() runs from cancel()/abort.
          }
        });
      },
      cancel() {
        release();
      },
    });

    return new Response(stream, {
      status: 200,
      headers: {
        "content-type": "text/event-stream",
        "cache-control": "no-cache, no-transform",
        connection: "keep-alive",
      },
    });
  };
}

let cachedConfig: DashboardConfig | undefined;

function getConfig(): DashboardConfig {
  if (!cachedConfig) cachedConfig = loadConfig();
  return cachedConfig;
}

export function GET(request: Request): Response {
  return createEventsHandler({ config: getConfig() })(request);
}
