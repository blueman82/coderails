import { homedir } from "node:os";
import { join } from "node:path";
import { isLocalOrigin } from "../../../lib/requestGuard";
import { getRunToken } from "../../../lib/runlog";
import {
  resolveQueueEntry,
  QueueActionError,
  type QueueEntrySnapshot,
} from "../../../lib/collect/queueActions";
import {
  claimAndSpawnBuild as claimAndSpawnBuildReal,
  type ClaimAndSpawnBuildResult,
} from "../../../lib/build/spawn";

const DEFAULT_QUEUE_DIR = join(homedir(), ".claude", "coderails-dashboard", "approvals");
const WRAPPER_PATH = join(process.cwd(), "..", "scripts", "run-builder.sh");
// process.cwd() for a Next.js server process is the app root
// (skills/dashboard/app); scripts/run-builder.sh lives one level up at
// skills/dashboard/scripts/ per the file map.

// hash is the hex SHA-256 filename stem per the queue contract (see
// docs/coderails/specs/2026-07-06-assistant-link-panel-design.md) — never
// anything else. Rejecting anything outside that shape at the API boundary
// closes off path traversal (e.g. "../../../etc/passwd") before it ever
// reaches queueActions.ts's join(queueDir, `${hash}.json`).
const HASH_PATTERN = /^[0-9a-f]{64}$/;

export interface QueueActionHandlerDeps {
  token: string;
  queueDir?: string;
  claimAndSpawnBuild?: (entry: QueueEntrySnapshot) => ClaimAndSpawnBuildResult;
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

    if (typeof payload.hash !== "string" || !HASH_PATTERN.test(payload.hash)) {
      return jsonResponse(400, { error: "invalid hash" });
    }

    if (payload.decision !== "approved" && payload.decision !== "denied") {
      return jsonResponse(400, { error: "decision must be 'approved' or 'denied'" });
    }

    try {
      const entry = resolveQueueEntry(queueDir, payload.hash, payload.decision);
      let build: ClaimAndSpawnBuildResult | undefined;
      if (
        entry.status === "approved" &&
        entry.toolName === "workflow-audit:propose-skill" &&
        deps.claimAndSpawnBuild
      ) {
        build = deps.claimAndSpawnBuild(entry);
      }
      return jsonResponse(200, { hash: payload.hash, status: payload.decision, ...(build ? { build } : {}) });
    } catch (err) {
      if (err instanceof QueueActionError) {
        if (err.message.includes("is not pending")) {
          return jsonResponse(409, { error: "entry is not pending" });
        }
        return jsonResponse(404, { error: "unknown queue entry" });
      }
      throw err;
    }
  };
}

export function POST(request: Request): Promise<Response> {
  return createQueueActionHandler({
    token: getRunToken(),
    claimAndSpawnBuild: (entry) => claimAndSpawnBuildReal(entry, { wrapperPath: WRAPPER_PATH }),
  })(request);
}
