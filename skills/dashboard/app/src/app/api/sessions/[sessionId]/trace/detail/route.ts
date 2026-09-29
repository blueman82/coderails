import { NATIVE_SESSION_ID, sourceInsideRoot, validSourceRef, type NativeRouteDeps } from "../../../../../../lib/collect";
import { authorize, nativeTraceDeps, routeJson, sessionRouteDeps } from "../../../route";

type Context = { params: Promise<{ sessionId: string }> };
export function createTraceDetailHandler(deps: NativeRouteDeps) {
  return async function GET(request: Request, context: Context): Promise<Response> {
    const denied = authorize(request, deps.token);
    if (denied) return denied;
    const { sessionId } = await context.params;
    if (!NATIVE_SESSION_ID.test(sessionId)) return routeJson(400, { error: "invalid native session ID" });
    const rawRef = new URL(request.url).searchParams.get("ref");
    if (!rawRef || rawRef.length > 2048) return routeJson(400, { error: "invalid source reference" });
    let ref: unknown;
    try { ref = JSON.parse(rawRef); }
    catch { return routeJson(400, { error: "invalid source reference" }); }
    if (!validSourceRef(ref)) return routeJson(400, { error: "invalid source reference" });
    try {
      const traceDeps = await nativeTraceDeps(sessionId, deps);
      if (ref.kind === "claude_hook_audit_record") {
        if (!traceDeps.auditPath || ref.recordId !== `audit:${ref.ordinal}`)
          return routeJson(400, { error: "invalid source reference" });
      } else if (ref.kind === "claude_graph_record") {
        const name = ref.recordId.split("#", 1)[0];
        if (!traceDeps.graphRoot || !["progress.json", "evals.json", "proof.json", "retro.json"].includes(name) ||
          !ref.recordId.startsWith(`${name}#/`) && ref.recordId !== `${name}#` ||
          !(await sourceInsideRoot(name, traceDeps.graphRoot)))
          return routeJson(400, { error: "invalid source reference" });
      } else {
        if (ref.kind !== "claude_parent_record" && ref.kind !== "claude_child_record")
          return routeJson(400, { error: "invalid source reference" });
        const match = /^(.*\.jsonl):([1-9][0-9]*)(?::item:(0|[1-9][0-9]*))?$/.exec(ref.recordId);
        if (!match || Number(match[2]) !== ref.ordinal || !Number.isSafeInteger(Number(match[2])) ||
          match[3] !== undefined && !Number.isSafeInteger(Number(match[3])) ||
          !(await sourceInsideRoot(match[1], deps.sourceRoot)))
          return routeJson(400, { error: "invalid source reference" });
      }
      return routeJson(200, await deps.detail(sessionId, ref, traceDeps));
    } catch { return routeJson(404, { error: "source detail unavailable" }); }
  };
}
export const GET = createTraceDetailHandler(sessionRouteDeps);
