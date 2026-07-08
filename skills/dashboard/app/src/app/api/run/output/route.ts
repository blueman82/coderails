import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { isLocalOrigin } from "../../../../lib/requestGuard";
import { getRunToken, readRuns } from "../../../../lib/runlog";

const DEFAULT_RUNS_DIR = join(homedir(), ".claude", "coderails-dashboard", "runs");
// A run's history is capped to whatever the dashboard SSE aggregator keeps (runsLimit in
// lib/collect/index.ts, default 20) — this route only ever needs to find one record by runId,
// not paginate, so it reads generously past that cap rather than importing the aggregator's
// limit constant for a lookup-by-id.
const RUNS_LOOKUP_LIMIT = 10_000;

// runId is always exactly 16 lowercase hex chars — randomBytes(8).toString("hex") in
// api/run/route.ts, the sole place a runId is minted. Any other shape (including a
// path-traversal attempt like "../../../etc/passwd") is rejected before any lookup happens.
const RUN_ID_PATTERN = /^[0-9a-f]{16}$/;

export interface RunOutputHandlerDeps {
  token: string;
  runsDir?: string;
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

// Builds the GET /api/run/output handler: reads a run's full output for the run-history "select
// a past run" case (a still-live run's output instead streams over the SSE run-output event —
// see runOutputBus.ts). Deliberately does NOT accept or join a client-supplied filesystem path:
// the only input is `runId`, format-validated against RUN_ID_PATTERN, then used purely as a key
// to look up the matching RunRecord in runs.jsonl (server-written by api/run/route.ts) — the
// path actually read is that record's own `outputPath` field, never
// `join(runsDir, runId + ".log")` built from the request. This mirrors the queue route's
// hash-format-then-lookup pattern (queueActions.ts's HASH_PATTERN comment) but goes one step
// further: even a validated runId is never itself joined into a path here.
export function createRunOutputHandler(deps: RunOutputHandlerDeps) {
  const runsDir = deps.runsDir ?? DEFAULT_RUNS_DIR;

  return async function GET(request: Request): Promise<Response> {
    if (!isLocalOrigin(request)) {
      return jsonResponse(403, { error: "forbidden" });
    }

    const url = new URL(request.url);
    const token = url.searchParams.get("token");
    if (token !== deps.token) {
      return jsonResponse(401, { error: "unauthorized" });
    }

    const runId = url.searchParams.get("runId");
    if (!runId || !RUN_ID_PATTERN.test(runId)) {
      return jsonResponse(400, { error: "invalid runId" });
    }

    const record = readRuns(RUNS_LOOKUP_LIMIT, { runsDir }).find((r) => r.runId === runId);
    if (!record) {
      return jsonResponse(404, { error: "unknown run" });
    }

    let output: string;
    try {
      output = readFileSync(record.outputPath, "utf-8");
    } catch {
      // Log file not (yet) written, or since removed — an absent log is not an error state a
      // caller needs to distinguish from "no output yet"; both render the same empty viewer.
      output = "";
    }

    return jsonResponse(200, { output });
  };
}

// getRunToken() already caches internally (see runlog.ts) — no need for a second cache here,
// same as api/queue/route.ts's GET/POST export below it.
export async function GET(request: Request): Promise<Response> {
  return createRunOutputHandler({ token: getRunToken() })(request);
}
