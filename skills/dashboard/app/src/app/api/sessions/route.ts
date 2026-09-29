import { readFile, readdir, stat, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { homedir } from "node:os";
import { isLocalOrigin } from "../../../lib/requestGuard";
import { getRunToken, tokensEqual } from "../../../lib/runlog";
import { listClaudeSessions, readClaudeTraceDetail, readClaudeTracePage } from "../../../lib/collect/sessionTrace";
import { NATIVE_SESSION_ID, nativeRouteDefaults, type NativeRouteDeps } from "../../../lib/collect";
import type { TraceCollectionDeps } from "../../../lib/collect/sessionTrace";

async function discoverNativeGraph(sessionId: string, loopsRoot: string): Promise<{ graphRoot?: string; graphDiscoveryError?: string }> {
  const matches: string[] = [];
  let uncertain = false;
  let projects;
  try { projects = await readdir(loopsRoot, { withFileTypes: true }); }
  catch (error) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") return {};
    return { graphDiscoveryError: "unreadable graph discovery root" };
  }
  for (const project of projects) {
    if (!project.isDirectory()) continue;
    const projectPath = join(loopsRoot, project.name);
    let sessions;
    try { sessions = await readdir(projectPath, { withFileTypes: true }); }
    catch { uncertain = true; continue; }
    for (const session of sessions) {
      if (!session.isDirectory()) continue;
      const path = join(projectPath, session.name);
      try {
        const raw = await readFile(join(path, "progress.json"), "utf8");
        let progress;
        try { progress = JSON.parse(raw); }
        catch { if (session.name === sessionId || raw.includes(sessionId)) uncertain = true; continue; }
        if (progress && progress.session_id === sessionId && progress.schema_version === 3) matches.push(path);
        else if (progress?.session_id === sessionId) uncertain = true;
      } catch (error) {
        if ((error as NodeJS.ErrnoException).code !== "ENOENT" || session.name === sessionId) uncertain = true;
      }
    }
  }
  if (matches.length > 1) return { graphDiscoveryError: `multiple matching graph roots (${matches.length})` };
  if (uncertain) return { graphDiscoveryError: "unreadable or malformed graph discovery candidate" };
  return matches.length === 1 ? { graphRoot: matches[0] } : {};
}

export async function resolveNativeGraphRoot(sessionId: string, loopsRoot: string): Promise<string | undefined> {
  return (await discoverNativeGraph(sessionId, loopsRoot)).graphRoot;
}

export async function nativeTraceDeps(sessionId: string | null, deps: NativeRouteDeps): Promise<TraceCollectionDeps> {
  const graph = sessionId ? await discoverNativeGraph(sessionId, deps.loopsRoot) : {};
  return {
    sourceRoot: deps.sourceRoot, cacheRoot: deps.cacheRoot,
    auditPath: (deps as NativeRouteDeps & { auditPath?: string }).auditPath,
    ...graph,
    now: () => new Date(),
    fs: { readFile: (path) => readFile(path, "utf8"), writeFile, stat },
  };
}

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
export const sessionRouteDeps: NativeRouteDeps & { auditPath: string } = {
  ...nativeRouteDefaults("claude"), token: getRunToken(),
  auditPath: process.env.CLAUDE_DISCIPLINE_LOG ?? join(homedir(), ".claude", "discipline.log"),
  list: listClaudeSessions, page: readClaudeTracePage, detail: readClaudeTraceDetail,
};
export function routeJson(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: {
    "content-type": "application/json", "cache-control": "no-store",
  } });
}
export function authorize(request: Request, token: string): Response | null {
  if (!isLocalOrigin(request)) return routeJson(403, { error: "forbidden" });
  const supplied = new URL(request.url).searchParams.get("token");
  if (supplied === null || !tokensEqual(token, supplied)) return routeJson(401, { error: "unauthorized" });
  return null;
}
export function createSessionsHandler(deps: NativeRouteDeps) {
  return async function GET(request: Request): Promise<Response> {
    const denied = authorize(request, deps.token);
    if (denied) return denied;
    try {
      const sessions = (await deps.list(await nativeTraceDeps(null, deps))).filter((value): value is { nativeSessionId: string } =>
        typeof value === "object" && value !== null && "nativeSessionId" in value &&
        typeof value.nativeSessionId === "string" && NATIVE_SESSION_ID.test(value.nativeSessionId));
      return routeJson(200, { sessions });
    } catch { return routeJson(503, { error: "native sessions unavailable" }); }
  };
}
export const GET = createSessionsHandler(sessionRouteDeps);
