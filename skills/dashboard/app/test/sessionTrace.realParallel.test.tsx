// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { cp, mkdtemp, readFile, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { SessionTracePanel } from "../src/components/SessionTracePanel";
import { listClaudeSessions, readClaudeTraceDetail, readClaudeTracePage, type TraceEvent, type TracePage } from "../src/lib/collect/sessionTrace";
import { createSessionsHandler } from "../src/app/api/sessions/route";
import { createTraceHandler } from "../src/app/api/sessions/[sessionId]/trace/route";
import { createTraceDetailHandler } from "../src/app/api/sessions/[sessionId]/trace/detail/route";

const ID = "7847a501-d2d5-41f4-bbab-4076ff00d09f";
const calls = ["toolu_01Y8HLWiqtQuhGK3JXSuJHTD", "toolu_01ULvGbe6uVMCwer1UnRYj5e"];
const workers = ["aad253f6db58af8d0", "a81745d33aebf8d45"];
const fixture = join(import.meta.dirname, "fixtures/session-trace/real-parallel/projects");

async function setup() {
  const root = await mkdtemp(join(tmpdir(), "claude-real-parallel-"));
  const sourceRoot = join(root, "projects");
  await cp(fixture, sourceRoot, { recursive: true });
  const deps = { token: "test-token", sourceRoot, cacheRoot: join(root, "cache"), loopsRoot: join(root, "empty-loops"),
    list: listClaudeSessions, page: readClaudeTracePage, detail: readClaudeTraceDetail };
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
  expect(page.complete).toBe(true);
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
  expect(new Set(page.events.filter((event) => event.name === "tool_request" && calls.includes(String(event.attributes["coderails.native.call_id"])))
    .map((event) => event.spanId)).size).toBe(2);
  expect(new Set(page.events.map((event) => event.traceId)).size).toBe(1);
  expect(new Set(calls).size).toBe(2);
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("sanitized real Claude parallel session", () => {
  it("joins two native worker lanes through authenticated handlers and renders detail only on expansion", async () => {
    const env = await setup();
    const page = await readClaudeTracePage(ID, null, 100, env.collectionDeps);
    assertCorrectTrace(page);
    expect(page.events.some((event: TraceEvent) => event.attributes["coderails.elapsed_gap.basis"] === "derived")).toBe(true);
    expect(JSON.stringify(page)).not.toContain("<img");
    vi.stubGlobal("fetch", env.fetcher);
    const { container } = render(<SessionTracePanel token="test-token" dashboardRunId="separate-run" />);
    await screen.findByRole("option", { name: new RegExp(ID) });
    fireEvent.change(screen.getByLabelText("Native session"), { target: { value: ID } });
    await screen.findByRole("heading", { name: `Worker ${workers[0]}` });
    expect(screen.getByRole("heading", { name: `Worker ${workers[1]}` })).toBeTruthy();
    expect(screen.getByText(/separate-run/)).toBeTruthy();
    expect(env.details).toBe(0);
    const lane = screen.getByRole("region", { name: `Worker ${workers[0]}` });
    const workerEvent = page.events.find((event) => event.attributes["coderails.actor.id"] === workers[0])!;
    const workerRow = within(lane).getAllByRole("listitem")[0];
    const parentText = within(workerRow).getByText(/^parent:/).textContent;
    expect(parentText).toContain("derived");
    for (const key of ["method", "parent_source_ref", "child_source_ref"]) {
      const value = workerEvent.attributes[`coderails.parent_join.${key}`];
      expect(value).toBeTruthy();
      expect(parentText).toContain(String(value));
    }
    expect(within(workerRow).getByText(/record: observed in source/)).toBeTruthy();
    expect(screen.getAllByText(/start time: .*\(observed in source; ref:/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/end time: time unavailable; source order only \(unavailable\)/).length).toBeGreaterThan(0);
    fireEvent.click(within(lane).getByRole("button", { name: /Source detail for assistant/ }));
    await waitFor(() => expect(env.details).toBe(1));
    expect(env.fetcher.mock.calls.filter(([url]) => String(url).includes("/detail?") && String(url).includes("token=test-token"))).toHaveLength(1);
    expect(container.querySelector("img")).toBeNull();
    await waitFor(() => expect(container.querySelector("pre")?.textContent).toContain("<img src=x onerror=alert(1)>"));
  });

  it("rejects a broken native child link and reports an incomplete trace", async () => {
    const env = await setup();
    const parent = join(env.sourceRoot, "project", `${ID}.jsonl`);
    await writeFile(parent, (await readFile(parent, "utf8")).replace(workers[0], "missing-worker"));
    const page = await readClaudeTracePage(ID, null, 100, env.collectionDeps);
    expect(page.complete).toBe(false);
    expect(page.errors?.length).toBeGreaterThan(0);
    expect(() => assertCorrectTrace(page)).toThrow();
  });
});
