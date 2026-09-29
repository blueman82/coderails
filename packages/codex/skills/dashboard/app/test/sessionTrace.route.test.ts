import { describe, expect, it, vi } from "vitest";
import { mkdtemp, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { resolveNativeGraphRoot } from "../src/app/api/sessions/route";
import { createSessionsHandler } from "../src/app/api/sessions/route";
import { createTraceHandler } from "../src/app/api/sessions/[sessionId]/trace/route";
import { createTraceDetailHandler } from "../src/app/api/sessions/[sessionId]/trace/detail/route";
import type { TraceCollectionDeps } from "../src/lib/collect/sessionTrace";

const ID = "123e4567-e89b-42d3-a456-426614174000";
const ref = { kind: "codex_parent_record", recordId: "test/sessionTrace.route.test.ts:1", ordinal: 1 };
const provenance = { sourceId: "test/sessionTrace.route.test.ts", sourceRef: ref };
const event = { eventId: "one", provenance };
const deps = () => ({
  token: "secret", sourceRoot: process.cwd(), cacheRoot: "/tmp/trace-cache", loopsRoot: "/tmp/loop-state",
  list: vi.fn(async () => [{ nativeSessionId: ID, provider: "codex", projectLabel: "project", displayLabel: ID, lastActivity: { value: null, basis: "unavailable" } }]),
  page: vi.fn(async (_id: string, cursor: string | null, _limit: number, _traceDeps: TraceCollectionDeps) => {
    void _limit; void _traceDeps;
    return { events: [event], inputCursor: cursor, nextCursor: cursor ? null : `g:${"a".repeat(64)}:1`, complete: true };
  }),
  detail: vi.fn(async () => ({ sourceRef: ref, provenance, content: "Sensitive <script>payload</script>" })),
});
const request = (path: string, origin = "http://localhost:3000") => new Request(`http://localhost:3000${path}`, { headers: { host: "localhost:3000", origin } });
const context = { params: Promise.resolve({ sessionId: ID }) };

describe("native session routes", () => {
  it("requires local origin and token before discovery", async () => {
    const d = deps(); const get = createSessionsHandler(d);
    expect((await get(request("/api/sessions?token=secret", "https://evil.example"))).status).toBe(403);
    expect((await get(request("/api/sessions?token=wrong"))).status).toBe(401);
    expect(d.list).not.toHaveBeenCalled();
    const response = await get(request("/api/sessions?token=secret"));
    expect(response.status).toBe(200);
    expect(JSON.stringify(await response.json())).not.toContain("Sensitive");
    const valid = (await d.list())[0];
    d.list.mockResolvedValueOnce([{ ...valid, nativeSessionId: "dashboard-run-123" }, valid]);
    expect((await (await get(request("/api/sessions?token=secret"))).json()).sessions).toEqual([valid]);
  });

  it("rejects bad session IDs and bounds stable cursor pages", async () => {
    const d = deps(); const get = createTraceHandler(d);
    expect((await get(request("/api/sessions/x/trace?token=secret"), { params: Promise.resolve({ sessionId: "../../etc" }) })).status).toBe(400);
    expect((await get(request(`/api/sessions/${ID}/trace?token=secret&limit=1001`), context)).status).toBe(400);
    expect((await get(request(`/api/sessions/${ID}/trace?token=secret&cursor=-1`), context)).status).toBe(400);
    expect((await get(request(`/api/sessions/${ID}/trace?token=wrong`), context)).status).toBe(401);
    expect((await get(request(`/api/sessions/${ID}/trace?token=secret`, "https://evil.example"), context)).status).toBe(403);
    const first = await (await get(request(`/api/sessions/${ID}/trace?token=secret&limit=1`), context)).json();
    const second = await (await get(request(`/api/sessions/${ID}/trace?token=secret&limit=1&cursor=${first.nextCursor}`), context)).json();
    expect(first.nextCursor).toBe(`g:${"a".repeat(64)}:1`); expect(second.nextCursor).toBeNull();
    expect(d.page).toHaveBeenLastCalledWith(ID, first.nextCursor, 1, expect.anything());
    for (const cursor of ["1", `g:${"A".repeat(64)}:1`, `g:${"a".repeat(64)}:01`, `g:${"a".repeat(64)}:-1`, `g:${"a".repeat(64)}:9007199254740992`])
      expect((await get(request(`/api/sessions/${ID}/trace?token=secret&cursor=${cursor}`), context)).status).toBe(400);
    d.page.mockRejectedValueOnce(new Error("Stale trace page cursor; restart pagination"));
    const stale = await get(request(`/api/sessions/${ID}/trace?token=secret&cursor=${first.nextCursor}`), context);
    expect(stale.status).toBe(409);
    expect(await stale.json()).toEqual({ error: "stale trace cursor", restart: true });
    expect(JSON.stringify(first)).not.toContain("Sensitive");
    d.page.mockResolvedValueOnce({ events: [{ ...event, provenance: { ...provenance, sourceId: "../outside.jsonl" } }], inputCursor: null, nextCursor: null, complete: true });
    expect((await get(request(`/api/sessions/${ID}/trace?token=secret`), context)).status).toBe(400);
  });

  it("only reveals requested detail after validating source containment", async () => {
    const d = deps(); const get = createTraceDetailHandler(d);
    d.sourceRoot = await mkdtemp(join(tmpdir(), "route-source-"));
    await writeFile(join(d.sourceRoot, "parent.jsonl"), "{}\n");
    const nativeRef = { ...ref, recordId: "parent.jsonl:1" };
    d.page.mockImplementation(async () => { throw new Error("detail must not scan trace pages"); });
    const query = `?token=secret&ref=${encodeURIComponent(JSON.stringify(nativeRef))}`;
    expect((await get(request(`/api/sessions/${ID}/trace/detail${query}`, "https://evil.example"), context)).status).toBe(403);
    expect((await get(request(`/api/sessions/${ID}/trace/detail?token=wrong&ref=${encodeURIComponent(JSON.stringify(nativeRef))}`), context)).status).toBe(401);
    expect((await get(request(`/api/sessions/${ID}/trace/detail?token=secret&ref=${encodeURIComponent(JSON.stringify({ ...ref, recordId: "../../escape" }))}`), context)).status).toBe(400);
    expect((await get(request(`/api/sessions/${ID}/trace/detail?token=secret&ref=${encodeURIComponent(JSON.stringify({ ...ref, recordId: "../outside.jsonl:1" }))}`), context)).status).toBe(400);
    expect(d.detail).not.toHaveBeenCalled();
    const response = await get(request(`/api/sessions/${ID}/trace/detail${query}`), context);
    expect(response.status).toBe(200);
    expect((await response.json()).content).toContain("Sensitive <script>");
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(d.page).not.toHaveBeenCalled();
    d.detail.mockRejectedValueOnce(new Error("not indexed"));
    expect((await get(request(`/api/sessions/${ID}/trace/detail?token=secret&ref=${encodeURIComponent(JSON.stringify({ ...nativeRef, recordId: "parent.jsonl:2", ordinal: 2 }))}`), context)).status).toBe(404);
  });

  it("accepts hook audit references only with an explicit configured audit source", async () => {
    const d = { ...deps(), auditPath: join(process.cwd(), "audit.log") };
    const auditRef = { kind: "codex_hook_audit_record", recordId: "audit:1", ordinal: 1 };
    d.page.mockResolvedValueOnce({ events: [{ ...event, provenance: { sourceId: "audit/discipline.log", sourceRef: auditRef } }], inputCursor: null, nextCursor: null, complete: true });
    expect((await createTraceHandler(d)(request(`/api/sessions/${ID}/trace?token=secret`), context)).status).toBe(200);
    expect((await createTraceDetailHandler(d)(request(`/api/sessions/${ID}/trace/detail?token=secret&ref=${encodeURIComponent(JSON.stringify(auditRef))}`), context)).status).toBe(200);
    expect((await createTraceDetailHandler(deps())(request(`/api/sessions/${ID}/trace/detail?token=secret&ref=${encodeURIComponent(JSON.stringify(auditRef))}`), context)).status).toBe(400);
  });

  it("links graph artifacts only through matching progress.session_id", async () => {
    const root = await mkdtemp(join(tmpdir(), "route-graph-"));
    const foreign = join(root, "project", ID);
    const matching = join(root, "project", "opaque-folder");
    await mkdir(foreign, { recursive: true }); await mkdir(matching);
    await writeFile(join(foreign, "progress.json"), JSON.stringify({ schema_version: 3, session_id: "foreign" }));
    await writeFile(join(matching, "progress.json"), JSON.stringify({ schema_version: 3, session_id: ID }));
    expect(await resolveNativeGraphRoot(ID, root)).toBe(matching);
    await writeFile(join(foreign, "progress.json"), JSON.stringify({ schema_version: 3, session_id: ID }));
    expect(await resolveNativeGraphRoot(ID, root)).toBeUndefined();
    const d = { ...deps(), loopsRoot: root };
    d.page.mockImplementation(async (_id, cursor, _limit, traceDeps) => ({ events: [event], inputCursor: cursor,
      nextCursor: null, complete: !traceDeps.graphDiscoveryError, errors: traceDeps.graphDiscoveryError ? [traceDeps.graphDiscoveryError] : [] }));
    const page = await (await createTraceHandler(d)(request(`/api/sessions/${ID}/trace?token=secret`), context)).json();
    expect(page.complete).toBe(false);
    expect(page.errors[0]).toMatch(/multiple matching graph roots/);
  });

  it("distinguishes a missing graph from a malformed matching candidate", async () => {
    const root = await mkdtemp(join(tmpdir(), "route-graph-"));
    expect(await resolveNativeGraphRoot(ID, root)).toBeUndefined();
    const candidate = join(root, "project", ID);
    await mkdir(candidate, { recursive: true });
    await writeFile(join(candidate, "progress.json"), "{bad json");
    const d = { ...deps(), loopsRoot: root };
    d.page.mockImplementation(async (_id, cursor, _limit, traceDeps) => ({
      events: [event], inputCursor: cursor, nextCursor: null, complete: !traceDeps.graphDiscoveryError,
      errors: traceDeps.graphDiscoveryError ? [traceDeps.graphDiscoveryError] : [],
    }));
    const page = await (await createTraceHandler(d)(request(`/api/sessions/${ID}/trace?token=secret`), context)).json();
    expect(page.complete).toBe(false);
    expect(page.errors[0]).toMatch(/unreadable or malformed graph discovery candidate/);
  });
});
