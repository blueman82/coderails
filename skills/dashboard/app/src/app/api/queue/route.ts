import { homedir } from "node:os";
import { join } from "node:path";
import { isLocalOrigin } from "../../../lib/requestGuard";
import { getRunToken } from "../../../lib/runlog";
import { resolveQueueEntry, QueueActionError } from "../../../lib/collect/queueActions";

const DEFAULT_QUEUE_DIR = join(homedir(), ".claude", "coderails-dashboard", "queue");

export interface QueueActionHandlerDeps {
  token: string;
  queueDir?: string;
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

// Builds the POST /api/queue handler: the dashboard's Approve/Deny action.
// This is the only writer of the approved/denied transition per the queue
// contract (docs/coderails/specs/2026-07-06-assistant-link-panel-design.md)
// — it performs an in-place JSON rewrite of the target <hash>.json file's
// status field, never a separate decision-file mechanism. Mirrors
// api/run/route.ts's token + Origin/Host guard pattern exactly.
export function createQueueActionHandler(deps: QueueActionHandlerDeps) {
  const queueDir = deps.queueDir ?? DEFAULT_QUEUE_DIR;

  return async function POST(request: Request): Promise<Response> {
    if (!isLocalOrigin(request)) {
      return jsonResponse(403, { error: "forbidden" });
    }

    let payload: { token?: unknown; hash?: unknown; decision?: unknown };
    try {
      payload = (await request.json()) as typeof payload;
    } catch {
      return jsonResponse(400, { error: "invalid JSON body" });
    }

    if (typeof payload.token !== "string" || payload.token !== deps.token) {
      return jsonResponse(401, { error: "unauthorized" });
    }

    if (typeof payload.hash !== "string" || !payload.hash) {
      return jsonResponse(400, { error: "missing hash" });
    }

    if (payload.decision !== "approved" && payload.decision !== "denied") {
      return jsonResponse(400, { error: "decision must be 'approved' or 'denied'" });
    }

    try {
      resolveQueueEntry(queueDir, payload.hash, payload.decision);
    } catch (err) {
      if (err instanceof QueueActionError) {
        return jsonResponse(404, { error: "unknown queue entry" });
      }
      throw err;
    }

    return jsonResponse(200, { hash: payload.hash, status: payload.decision });
  };
}

export function POST(request: Request): Promise<Response> {
  return createQueueActionHandler({ token: getRunToken() })(request);
}
