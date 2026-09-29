import { NATIVE_SESSION_ID, MAX_TRACE_PAGE, sourceInsideRoot, type NativeRouteDeps } from "../../../../../lib/collect";
import { authorize, nativeTraceDeps, routeJson, sessionRouteDeps } from "../../route";

type Context = { params: Promise<{ sessionId: string }> };
export function createTraceHandler(deps: NativeRouteDeps) {
  return async function GET(request: Request, context: Context): Promise<Response> {
    const denied = authorize(request, deps.token);
    if (denied) return denied;
    const { sessionId } = await context.params;
    if (!NATIVE_SESSION_ID.test(sessionId)) return routeJson(400, { error: "invalid native session ID" });
    const params = new URL(request.url).searchParams;
    const cursor = params.get("cursor");
    const rawLimit = params.get("limit") ?? "50";
    const limit = Number(rawLimit);
    const cursorMatch = cursor === null ? null : /^g:[0-9a-f]{64}:(0|[1-9][0-9]*)$/.exec(cursor);
    if ((cursor !== null && (!cursorMatch || !Number.isSafeInteger(Number(cursor.slice(67))))) ||
      !/^[1-9][0-9]*$/.test(rawLimit) || !Number.isSafeInteger(limit) || limit > MAX_TRACE_PAGE)
      return routeJson(400, { error: "invalid trace page" });
    try {
      const traceDeps = await nativeTraceDeps(sessionId, deps);
      const page = await deps.page(sessionId, cursor, limit, traceDeps);
      const contained = await Promise.all(page.events.map((event) => {
        const sourceId = event.provenance.sourceId;
        if (sourceId === "audit/discipline.log")
          return Boolean(traceDeps.auditPath) && event.provenance.sourceRef.kind === "codex_hook_audit_record";
        if (sourceId.startsWith("graph/"))
          return Boolean(traceDeps.graphRoot) && ["graph/progress.json", "graph/evals.json", "graph/proof.json", "graph/retro.json"].includes(sourceId) &&
            sourceInsideRoot(sourceId.slice(6), traceDeps.graphRoot!);
        return sourceInsideRoot(sourceId, deps.sourceRoot);
      }));
      if (contained.some((value) => !value)) return routeJson(400, { error: "invalid source reference" });
      return routeJson(200, page);
    } catch (error) {
      if (error instanceof Error && /stale trace.*cursor/i.test(error.message))
        return routeJson(409, { error: "stale trace cursor", restart: true });
      return routeJson(404, { error: "native trace unavailable" });
    }
  };
}
export const GET = createTraceHandler(sessionRouteDeps);
