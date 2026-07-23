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
      onError: (source, err) => {
        console.error(`[api/events] collector "${source}" failed:`, err);
      },
    });

    let unsubscribe: (() => void) | undefined;

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
            // nothing to do, cancel() will run the teardown.
          }
        });
      },
      cancel() {
        unsubscribe?.();
        aggregator.stop();
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
