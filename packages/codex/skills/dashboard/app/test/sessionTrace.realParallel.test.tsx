// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { cp, mkdtemp, readFile, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { SessionTracePanel } from "../src/components/SessionTracePanel";
import { collectCodexSessionTrace, listCodexSessions, readCodexTraceDetail, readCodexTracePage, type TracePage } from "../src/lib/collect/sessionTrace";
import { createSessionsHandler } from "../src/app/api/sessions/route";
import { createTraceHandler } from "../src/app/api/sessions/[sessionId]/trace/route";
import { createTraceDetailHandler } from "../src/app/api/sessions/[sessionId]/trace/detail/route";

const ID = "01a0ea0d-1a4e-7480-98b5-a1e7931a13a2";
const calls = ["call_UgtoUq82RxqROkiLHk5Nj34u", "call_JgRx77kzQpJL1jNUEbqGNnR0"];
const workers = ["01a0ea63-88b7-7b80-b5c3-73cd30fb3953", "01a0ea63-b4b7-7173-950b-ac1a4ddaac60"];
const fixture = join(import.meta.dirname, "fixtures/session-trace/real-parallel/sessions");

async function setup() {
  const root = await mkdtemp(join(tmpdir(), "codex-real-parallel-"));
  const sourceRoot = join(root, "sessions");
  await cp(fixture, sourceRoot, { recursive: true });
  const deps = { token: "test-token", sourceRoot, cacheRoot: join(root, "cache"), loopsRoot: join(root, "empty-loops"),
    list: listCodexSessions, page: readCodexTracePage, detail: readCodexTraceDetail };
  const handlers = { sessions: createSessionsHandler(deps), page: createTraceHandler(deps), detail: createTraceDetailHandler(deps) };
  let details = 0;
  const fetcher = vi.fn(async (input: string) => {
    const url = new URL(input, "http://localhost:3000");
    const request = new Request(url, { headers: { host: "localhost:3000", origin: "http://localhost:3000" } });
    if (url.pathname === "/api/sessions") return handlers.sessions(request);
    const context = { params: Promise.resolve({ sessionId: ID }) };
    if (url.pathname.endsWith("/detail")) { details += 1; return handlers.detail(request, context); }
    return handlers.page(request, context);
  });
  const collectionDeps = { sourceRoot, cacheRoot: deps.cacheRoot, now: () => new Date("2026-09-29T00:00:00Z"),
    fs: { readFile: (path: string) => readFile(path, "utf8"), writeFile, stat } };
  return { sourceRoot, fetcher, collectionDeps, get details() { return details; } };
}

function assertCorrectTrace(page: TracePage) {
  expect(page.complete, JSON.stringify(page.errors)).toBe(true);
  expect(page.errors).toEqual([]);
  const orchestrator = page.events.filter((event) => event.attributes["coderails.actor.kind"] === "orchestrator");
  expect(orchestrator.length).toBeGreaterThanOrEqual(2);
  for (let index = 0; index < workers.length; index += 1) {
    const lane = page.events.filter((event) => event.attributes["coderails.actor.id"] === workers[index]);
    expect(lane.length).toBeGreaterThan(0);
    const parent = page.events.find((event) => event.spanId === lane[0].parentSpanId);
    expect(parent?.attributes["coderails.native.call_id"]).toBe(calls[index]);
    expect(lane.every((event) => event.parentSpanId === parent?.spanId)).toBe(true);
    expect(lane[0].attributes["coderails.parent_join.basis"]).toBe("derived");
    expect(lane[0].attributes["coderails.parent_join.parent_source_ref"]).toBeTruthy();
  }
  expect(new Set(page.events.filter((event) => calls.includes(String(event.attributes["coderails.native.call_id"])))
    .map((event) => event.spanId)).size).toBe(2);
  expect(new Set(page.events.map((event) => event.traceId))).toEqual(new Set([page.events[0].traceId]));
  expect(new Set(calls).size).toBe(2);
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("sanitized real Codex parallel session", () => {
  it("offers only the parent session", async () => {
    const env = await setup();
    expect((await listCodexSessions(env.collectionDeps)).map((session) => session.nativeSessionId)).toEqual([ID]);
  });

  it("refuses to relabel an explicitly requested child as an orchestrator", async () => {
    const env = await setup();
    const child = await collectCodexSessionTrace(workers[0], env.collectionDeps);
    expect(child.complete).toBe(false);
    expect(child.eventCount).toBe(0);
    expect(child.errors.length).toBeGreaterThan(0);
  });

  it("does not emit orchestrator audit events for an explicitly requested child", async () => {
    const env = await setup();
    const auditPath = join(env.sourceRoot, "discipline.log");
    await writeFile(auditPath, `2026-09-28T23:40:00Z hook=test_gate session=${workers[0]} blocked=1\n`);
    const child = await collectCodexSessionTrace(workers[0], { ...env.collectionDeps, auditPath });
    expect(child.complete).toBe(false);
    expect(child.eventCount).toBe(0);
    expect(child.sources.some((source) => source.sourceId === "audit/discipline.log")).toBe(false);
  });

  it("does not attach orchestrator audit events when child metadata cannot be read", async () => {
    const env = await setup();
    const auditPath = join(env.sourceRoot, "discipline.log");
    await writeFile(auditPath, `2026-09-28T23:40:00Z hook=test_gate session=${workers[0]} blocked=1\n`);
    const childPath = join(env.sourceRoot, `rollout-${workers[0]}.jsonl`);
    const deps = { ...env.collectionDeps, auditPath, fs: { ...env.collectionDeps.fs,
      readFile: (path: string) => path === childPath ? Promise.reject(new Error("read failed")) : readFile(path, "utf8") } };
    const child = await collectCodexSessionTrace(workers[0], deps);
    expect(child.complete).toBe(false);
    expect(child.eventCount).toBe(0);
  });

  it("joins two native worker lanes through authenticated handlers and renders detail only on expansion", async () => {
    const env = await setup();
    const page = await readCodexTracePage(ID, null, 100, env.collectionDeps);
    assertCorrectTrace(page);
    expect(JSON.stringify(page)).not.toContain("<img");
    vi.stubGlobal("fetch", env.fetcher);
    const { container } = render(<SessionTracePanel token="test-token" dashboardRunId="separate-run" />);
    await screen.findByRole("option", { name: new RegExp(ID.slice(0, 8)) });
    fireEvent.change(screen.getByLabelText("Native session"), { target: { value: ID } });
    expect(await screen.findAllByText(`Actor: Worker ${workers[0]}`)).not.toHaveLength(0);
    expect(screen.getAllByText(`Actor: Worker ${workers[1]}`)).not.toHaveLength(0);
    expect(screen.getByText(/separate-run/)).toBeTruthy();
    expect(env.details).toBe(0);
    const workerEvent = page.events.find((event) => event.attributes["coderails.actor.id"] === workers[0])!;
    const timeline = within(screen.getByRole("list", { name: "Trace timeline" }));
    const workerRow = timeline.getAllByRole("listitem")
      .find((row) => row.textContent?.includes(`Actor: Worker ${workers[0]}`))!;
    const parentText = within(workerRow).getByText(/^parent:/).textContent;
    expect(parentText).toContain("derived");
    for (const key of ["method", "parent_source_ref", "child_source_ref"]) {
      const value = workerEvent.attributes[`coderails.parent_join.${key}`];
      expect(value).toBeTruthy();
      expect(parentText).toContain(String(value));
    }
    expect(within(workerRow).getByText(/record: observed in source/)).toBeTruthy();
    const orchestratorRow = timeline.getAllByRole("listitem")
      .find((row) => row.textContent?.includes("Actor: Orchestrator and evidence") && row.textContent?.includes("function_call"))!;
    fireEvent.click(within(orchestratorRow).getByRole("button", { name: /Source detail for function_call/ }));
    await waitFor(() => expect(env.details).toBe(1));
    expect(env.fetcher.mock.calls.filter(([url]) => String(url).includes("/detail?") && String(url).includes("token=test-token"))).toHaveLength(1);
    expect(container.querySelector("img")).toBeNull();
    await waitFor(() => expect(container.querySelector("pre")?.textContent).toContain("<img src=x onerror=alert(1)>"));
  });

  it("rejects a broken native child link and reports an incomplete trace", async () => {
    const env = await setup();
    const child = join(env.sourceRoot, `rollout-${workers[0]}.jsonl`);
    await writeFile(child, (await readFile(child, "utf8")).replace(`"parent_thread_id":"${ID}"`, '"parent_thread_id":"foreign-session"'));
    const page = await readCodexTracePage(ID, null, 100, env.collectionDeps);
    expect(page.complete).toBe(false);
    expect(page.errors?.length).toBeGreaterThan(0);
    expect(() => assertCorrectTrace(page)).toThrow();
  });
});
