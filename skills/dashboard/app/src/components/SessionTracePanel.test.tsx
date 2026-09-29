// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { SessionTracePanel } from "./SessionTracePanel";
import { mkdtemp, mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { readClaudeTracePage, type TraceCollectionDeps } from "@/lib/collect/sessionTrace";
import type { TraceEvent } from "@/lib/collect/sessionTrace";

const FIRST = "11111111-1111-4111-8111-111111111111";
const SECOND = "22222222-2222-4222-8222-222222222222";

function event(name: string, ordinal: number, extra: Partial<TraceEvent> = {}): TraceEvent {
  return {
    schemaVersion: 1, eventId: `event-${ordinal}`, traceId: "trace", spanId: `span-${ordinal}`,
    parentSpanId: null, name, kind: "internal", status: { value: "unavailable", basis: "unavailable" },
    startTimeUnixNano: null, endTimeUnixNano: null, events: [], attributes: { "coderails.actor.kind": "orchestrator",
      "coderails.start_time.basis": "unavailable", "coderails.end_time.basis": "unavailable",
      "coderails.duration_ms": null, "coderails.duration.basis": "unavailable" },
    provenance: { provider: "claude", nativeSessionId: FIRST, sourceId: "parent.jsonl",
      sourceOrdinal: ordinal, basis: "observed",
      sourceRef: { kind: "claude_parent_record", recordId: `parent.jsonl:${ordinal}`, ordinal } },
    ...extra,
  };
}

function response(value: unknown): Response {
  return { ok: true, json: async () => value } as Response;
}

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("SessionTracePanel", () => {
  it("renders the adapter's derived request/result gap separately from native duration", async () => {
    const root = await mkdtemp(join(tmpdir(), "claude-panel-gap-"));
    const sourceRoot = join(root, "projects");
    const parent = join(sourceRoot, "project", "s1.jsonl");
    await mkdir(join(sourceRoot, "project", "s1", "subagents"), { recursive: true });
    const native = JSON.parse(await readFile(join(process.cwd(), "test/fixtures/session-trace/claude/native-shape.json"), "utf8"));
    native.parent[1].timestamp = "2026-09-28T12:00:01Z";
    await writeFile(parent, native.parent.map((row: unknown) => JSON.stringify(row)).join("\n") + "\n");
    await writeFile(join(sourceRoot, "project", "s1", "subagents", "agent-a1.jsonl"),
      native.child.map((row: unknown) => JSON.stringify(row)).join("\n") + "\n");
    const deps: TraceCollectionDeps = { sourceRoot, cacheRoot: join(root, "cache"),
      now: () => new Date("2026-09-28T13:00:00Z"), fs: { readFile: (path) => readFile(path, "utf8"), writeFile, stat } };
    const page = await readClaudeTracePage("s1", null, 50, deps);
    const fetcher = vi.fn(async (input: string) => {
      const url = new URL(input, "http://localhost");
      if (url.pathname === "/api/sessions") return response({ sessions: [{ nativeSessionId: "s1", provider: "claude",
        projectLabel: "project", displayLabel: "session", lastActivity: { value: null, basis: "unavailable" } }] });
      return response(page);
    });
    vi.stubGlobal("fetch", fetcher);
    render(<SessionTracePanel token="secret" />);
    await screen.findByRole("option", { name: /session/ });
    fireEvent.change(screen.getByLabelText("Native session"), { target: { value: "s1" } });
    await screen.findByText(/request\/result elapsed gap: 1000 ms \(derived from source timestamps; cause unknown\)/);
    expect(screen.getByText(/Project directory label: project \(derived from local directory name\)/)).toBeTruthy();
    expect(screen.getByText(/Indexed source records: 5 \(derived from local source scan\).*Emitted events: 5 \(derived from local trace index; not a native event count\)/)).toBeTruthy();
    expect(screen.getAllByText(/duration: unavailable/).length).toBeGreaterThan(0);
    expect(screen.getByText(/gap source refs:/)).toBeTruthy();
  });
  it("clears a stale page and offers an explicit restart without mixing generations", async () => {
    let firstLoads = 0;
    const fetcher = vi.fn(async (input: string) => {
      const path = new URL(input, "http://localhost");
      if (path.pathname === "/api/sessions") return response({ sessions: [{ nativeSessionId: FIRST,
        provider: "claude", projectLabel: "p", displayLabel: "first", lastActivity: { value: null, basis: "unavailable" } }] });
      if (path.searchParams.has("cursor")) return { ok: false, status: 409, json: async () => ({ error: "stale trace cursor", restart: true }) } as Response;
      firstLoads += 1;
      return response({ events: [event(firstLoads === 1 ? "old_event" : "new_event", firstLoads)],
        nextCursor: `g:${"a".repeat(64)}:1`, complete: true });
    });
    vi.stubGlobal("fetch", fetcher);
    render(<SessionTracePanel token="secret" />);
    await screen.findByRole("option", { name: /first/ });
    fireEvent.change(screen.getByLabelText("Native session"), { target: { value: FIRST } });
    await screen.findByText("old_event");
    fireEvent.click(screen.getByRole("button", { name: "Load more trace events" }));
    await screen.findByRole("button", { name: "Restart trace" });
    expect(screen.queryByText("old_event")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Restart trace" }));
    await screen.findByText("new_event");
    expect(screen.queryByText("old_event")).toBeNull();
  });

  it("shows safe tool metadata and duration basis without fetching source detail", async () => {
    const tool = event("tool_request", 1, { attributes: { "coderails.actor.kind": "orchestrator",
      "tool.name": "exec_command", "coderails.native.call_id": "call-123", "coderails.duration_ms": 37,
      "coderails.duration.basis": "derived" } });
    const fetcher = vi.fn(async (input: string) => {
      const path = new URL(input, "http://localhost");
      if (path.pathname === "/api/sessions") return response({ sessions: [{ nativeSessionId: FIRST,
        provider: "claude", projectLabel: "p", displayLabel: "first", lastActivity: { value: null, basis: "unavailable" } }] });
      return response({ events: [tool], nextCursor: null, complete: true });
    });
    vi.stubGlobal("fetch", fetcher);
    render(<SessionTracePanel token="secret" />);
    await screen.findByRole("option", { name: /first/ });
    fireEvent.change(screen.getByLabelText("Native session"), { target: { value: FIRST } });
    await screen.findByText(/tool: exec_command/);
    expect(screen.getByText(/native call: call-123/)).toBeTruthy();
    expect(screen.getByText(/duration: 37 ms \(derived\)/)).toBeTruthy();
    expect(fetcher.mock.calls.some(([url]) => String(url).includes("/detail"))).toBe(false);
  });

  it("selects a native session independently of a dashboard run and groups parallel workers", async () => {
    const workerA = event("worker_turn", 3, { eventId: "worker-a", parentSpanId: "span-1",
      attributes: { "coderails.actor.kind": "worker", "coderails.actor.id": "agent-a", "coderails.node.id": "A" } });
    const workerB = event("worker_turn", 4, { eventId: "worker-b", parentSpanId: "span-1",
      attributes: { "coderails.actor.kind": "worker", "coderails.actor.id": "agent-b", "coderails.node.id": "B" } });
    const fetcher = vi.fn(async (input: string) => {
      const url = new URL(input, "http://localhost");
      if (url.pathname === "/api/sessions") return response({ sessions: [
        { nativeSessionId: FIRST, provider: "claude", projectLabel: "project", displayLabel: "first", lastActivity: { value: null, basis: "unavailable" } },
        { nativeSessionId: SECOND, provider: "claude", projectLabel: "project", displayLabel: "second", lastActivity: { value: null, basis: "unavailable" } },
      ] });
      return response({ events: [event("tool_request", 1), workerA, workerB, event("graph_retry", 5,
        { attributes: { "coderails.node.id": "A", "coderails.attempt": 2 }, provenance: { ...event("x", 5).provenance, basis: "derived", derivation: { method: "graph snapshot", sourceIds: ["progress"] } } }),
        event("graph_hard_stop", 6)], nextCursor: null, complete: false,
        errors: ["multiple matching graph roots (3)"] });
    });
    vi.stubGlobal("fetch", fetcher);
    render(<SessionTracePanel token="secret" dashboardRunId="run-123" />);
    expect(screen.getByText(/run-123/)).toBeTruthy();
    await screen.findByRole("option", { name: /first/ });
    fireEvent.change(screen.getByLabelText("Native session"), { target: { value: FIRST } });
    await screen.findByText("graph_hard_stop");
    expect(screen.getByText(/agent-a/)).toBeTruthy();
    expect(screen.getByText(/agent-b/)).toBeTruthy();
    expect(screen.getAllByText(/parent:.*join unavailable; method: unavailable; parent source: unavailable; child source: unavailable/)).toHaveLength(2);
    expect(screen.getByText(/unresolved trace/i)).toBeTruthy();
    expect(screen.getByText(/multiple matching graph roots \(3\)/)).toBeTruthy();
    expect(screen.getByText(/display tie break/)).toBeTruthy();
    expect(screen.getAllByText(/usage unavailable/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/cost unavailable/).length).toBeGreaterThan(0);
    expect(fetcher.mock.calls.some(([url]) => String(url).includes(`/api/sessions/${FIRST}/trace?`))).toBe(true);
    expect(fetcher.mock.calls.some(([url]) => String(url).includes("run-123/trace"))).toBe(false);
  });

  it("loads source detail only on expansion and renders source text without HTML", async () => {
    const fetcher = vi.fn(async (input: string) => {
      const url = new URL(input, "http://localhost");
      if (url.pathname === "/api/sessions") return response({ sessions: [{ nativeSessionId: FIRST, provider: "claude", projectLabel: "p", displayLabel: "first", lastActivity: { value: null, basis: "unavailable" } }] });
      if (url.pathname.endsWith("/detail")) return response({ content: "<img src=x onerror=alert(1)>" });
      return response({ events: [event("tool_request", 1)], nextCursor: null, complete: true });
    });
    vi.stubGlobal("fetch", fetcher);
    const { container } = render(<SessionTracePanel token="secret" />);
    await screen.findByRole("option", { name: /first/ });
    fireEvent.change(screen.getByLabelText("Native session"), { target: { value: FIRST } });
    await screen.findByText("tool_request");
    expect(fetcher.mock.calls.filter(([url]) => String(url).includes("/detail"))).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: /source detail.*tool_request/i }));
    await screen.findByText("<img src=x onerror=alert(1)>");
    expect(container.querySelector("img")).toBeNull();
    expect(fetcher.mock.calls.filter(([url]) => String(url).includes("/detail"))).toHaveLength(1);
    expect(fetcher.mock.calls.some(([url]) => String(url).includes("token=secret") && String(url).includes("ref="))).toBe(true);
  });

  it("shows pagination and unresolved state without implying completion", async () => {
    const fetcher = vi.fn(async (input: string) => {
      const url = new URL(input, "http://localhost");
      if (url.pathname === "/api/sessions") return response({ sessions: [{ nativeSessionId: FIRST, provider: "claude", projectLabel: "p", displayLabel: "first", lastActivity: { value: null, basis: "unavailable" } }] });
      if (url.searchParams.get("cursor") === "1") return response({ events: [event("turn_aborted", 2, { status: { value: "error", basis: "observed" } })], nextCursor: null, complete: false });
      return response({ events: [event("graph_node", 1)], nextCursor: "1", complete: false });
    });
    vi.stubGlobal("fetch", fetcher);
    render(<SessionTracePanel token="secret" />);
    await screen.findByRole("option", { name: /first/ });
    fireEvent.change(screen.getByLabelText("Native session"), { target: { value: FIRST } });
    await screen.findByText("graph_node");
    fireEvent.click(screen.getByRole("button", { name: "Load more trace events" }));
    await screen.findByText("turn_aborted");
    expect(screen.getByText(/unresolved trace/i)).toBeTruthy();
    expect(screen.getByText(/status: error.*observed/i)).toBeTruthy();
    expect(screen.queryByText(/verified completion/i)).toBeNull();
    await waitFor(() => expect(fetcher.mock.calls.some(([url]) => String(url).includes("cursor=1"))).toBe(true));
  });

  it("labels derived and unavailable facts and exposes evidence references without elevating attempts", async () => {
    const derived = event("graph_retry", 1, {
      parentSpanId: "missing-parent", status: { value: "unavailable", basis: "unavailable" },
      attributes: { "coderails.node.id": "A", "coderails.attempt": 2,
        "coderails.loop.id": "loop-1", "coderails.wave.id": "wave-2" },
      provenance: { ...event("x", 1).provenance, basis: "derived",
        derivation: { method: "snapshot correlation", sourceIds: ["progress.json"] } },
    });
    const evidence = event("proof_reference", 2, { attributes: {
      "coderails.evidence.kind": "proof", "coderails.evidence.id": "proof.json",
    } });
    const fetcher = vi.fn(async (input: string) => {
      const url = new URL(input, "http://localhost");
      if (url.pathname === "/api/sessions") return response({ sessions: [{ nativeSessionId: FIRST, provider: "claude", projectLabel: "p", displayLabel: "first", lastActivity: { value: null, basis: "unavailable" } }] });
      return response({ events: [derived, evidence, event("evals_reference", 3), event("retro_reference", 4)], nextCursor: null, complete: false });
    });
    vi.stubGlobal("fetch", fetcher);
    render(<SessionTracePanel token="secret" />);
    await screen.findByRole("option", { name: /first/ });
    fireEvent.change(screen.getByLabelText("Native session"), { target: { value: FIRST } });
    await screen.findByText("graph_retry");
    expect(screen.getByText(/derived: snapshot correlation from progress.json/)).toBeTruthy();
    expect(screen.getByText(/parent join unresolved/)).toBeTruthy();
    expect(screen.getByText(/evidence.kind: proof · evidence.id: proof.json/)).toBeTruthy();
    expect(screen.getByText("evals_reference")).toBeTruthy();
    expect(screen.getByText("retro_reference")).toBeTruthy();
    expect(screen.getAllByText(/status: unavailable/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/verified completion/i)).toBeNull();
  });
  it("shows a derived timestamp's method and source references separately from record provenance", async () => {
    const ref = event("x", 1).provenance.sourceRef;
    const derived = event("derived_time", 1, { startTimeUnixNano: "1727524800000000000",
      attributes: { "coderails.start_time.basis": "derived", "coderails.start_time.method": "trusted_offset",
        "coderails.start_time.source_refs": JSON.stringify([ref]), "coderails.end_time.basis": "unavailable",
        "coderails.duration_ms": null, "coderails.duration.basis": "unavailable" } });
    vi.stubGlobal("fetch", vi.fn(async (input: string) => new URL(input, "http://localhost").pathname === "/api/sessions"
      ? response({ sessions: [{ nativeSessionId: FIRST, provider: "claude", projectLabel: "p", displayLabel: "first",
        lastActivity: { value: null, basis: "unavailable" } }] })
      : response({ events: [derived], nextCursor: null, complete: true })));
    render(<SessionTracePanel token="secret" />);
    await screen.findByRole("option", { name: /first/ });
    fireEvent.change(screen.getByLabelText("Native session"), { target: { value: FIRST } });
    await screen.findByText("derived_time");
    expect(screen.getByText(/start time: .*derived: trusted_offset from parent\.jsonl:1/)).toBeTruthy();
    expect(screen.getByText(/record: observed in source/)).toBeTruthy();
  });
});
