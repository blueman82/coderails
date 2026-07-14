import { describe, it, expect, afterEach, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { DashboardContextTestProvider } from "./testUtils/DashboardContextTestProvider";
import { OutputViewerPanel, fetchSettledOutput } from "../src/components/OutputViewerPanel";
import type { DashboardSnapshot } from "../src/hooks/useDashboardState";
import type { RunRecord } from "../src/lib/runlog";

function emptySnapshot(overrides: Partial<DashboardSnapshot> = {}): DashboardSnapshot {
  return {
    sessions: [],
    loops: [],
    gates: [],
    health: [],
    runs: [],
    queue: [],
    builds: [],
    ...overrides,
  };
}

function run(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    runId: "0123456789abcdef",
    button: "wiki-lint",
    argv: [],
    cwd: "/",
    profile: "standard",
    startedAt: 1000,
    outputPath: "/tmp/x.log",
    ...overrides,
  };
}

// The overlay is closed by default and only opens on click, which renderToStaticMarkup can't
// drive — so these SSR tests cover only the always-rendered history list. Open/close/markdown/
// live-stream behaviour lives in ../src/components/OutputViewerPanel.client.test.tsx (jsdom).
describe("OutputViewerPanel — history list (SSR)", () => {
  it("renders an empty state when there are no runs", () => {
    const html = renderToStaticMarkup(
      createElement(DashboardContextTestProvider, { snapshot: emptySnapshot() }, createElement(OutputViewerPanel, { token: "t" }))
    );
    expect(html).toContain("no runs yet");
  });

  it("does not render any output region until a row is clicked (no inline viewer to scroll past)", () => {
    const finished = run({ runId: "done1", startedAt: 100, endedAt: 150, exitCode: 0 });
    const html = renderToStaticMarkup(
      createElement(DashboardContextTestProvider, { snapshot: emptySnapshot({ runs: [finished] }) }, createElement(OutputViewerPanel, { token: "t" }))
    );
    // The retired inline viewer rendered a .hud-output-viewer <pre> here; the overlay renders
    // nothing until opened.
    expect(html).not.toContain("hud-output-viewer");
    expect(html).not.toContain("hud-overlay");
  });

  it("renders each run-history entry as a clickable row carrying its runId", () => {
    const a = run({ runId: "aaaa111122223333", startedAt: 100, endedAt: 150, exitCode: 0 });
    const b = run({ runId: "bbbb111122223333", startedAt: 200, endedAt: 250, exitCode: 1 });
    const html = renderToStaticMarkup(
      createElement(DashboardContextTestProvider, { snapshot: emptySnapshot({ runs: [a, b] }) }, createElement(OutputViewerPanel, { token: "t" }))
    );
    expect(html).toContain("aaaa111122223333");
    expect(html).toContain("bbbb111122223333");
    expect(html).toContain("hud-run-row-selectable");
  });
});

// fetchSettledOutput is a standalone exported function with no React dependency, tested directly
// against a stubbed global.fetch. Every failure mode returns a distinct result rather than
// collapsing to `undefined` (which the overlay would render as the same "no output" a genuinely
// empty run produces).
describe("fetchSettledOutput", () => {
  const originalFetch = global.fetch;

  afterEach(() => {
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("returns ok:true with the output string on a 200 response", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", output: "hello" }), { status: 200 })
    ) as unknown as typeof fetch;
    const result = await fetchSettledOutput("tok", "0123456789abcdef");
    expect(result).toEqual({ ok: true, output: "hello" });
  });

  it("returns a distinct error (not undefined/empty) on a 500 response", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "error", error: "boom" }), { status: 500 })
    ) as unknown as typeof fetch;
    const result = await fetchSettledOutput("tok", "0123456789abcdef");
    expect(result.ok).toBe(false);
    expect(result).toMatchObject({ kind: "error", error: "boom" });
  });

  it("falls back to a generic status-coded error when a non-2xx response has no error field", async () => {
    global.fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 403 })) as unknown as typeof fetch;
    const result = await fetchSettledOutput("tok", "0123456789abcdef");
    expect(result.ok).toBe(false);
    expect(result).toMatchObject({ kind: "error", error: "request failed (403)" });
  });

  it("returns kind:'error' (not a thrown exception) when fetch itself rejects (network error)", async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error("network down")) as unknown as typeof fetch;
    const result = await fetchSettledOutput("tok", "0123456789abcdef");
    expect(result.ok).toBe(false);
    expect(result).toMatchObject({ kind: "error", error: "network error" });
  });

  it("returns kind:'error' (not undefined) when the response body is malformed JSON", async () => {
    global.fetch = vi.fn().mockResolvedValue(new Response("not json{{{", { status: 200 })) as unknown as typeof fetch;
    const result = await fetchSettledOutput("tok", "0123456789abcdef");
    expect(result.ok).toBe(false);
    expect(result).toMatchObject({ kind: "error" });
  });

  it("returns kind:'in-progress' (distinct from both ok and error) on a 409 response", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "in-progress" }), { status: 409 })
    ) as unknown as typeof fetch;
    const result = await fetchSettledOutput("tok", "0123456789abcdef");
    expect(result).toEqual({ ok: false, kind: "in-progress" });
  });

  it("returns kind:'error' when a 200 response's output field is missing/wrong-typed", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", output: 12345 }), { status: 200 })
    ) as unknown as typeof fetch;
    const result = await fetchSettledOutput("tok", "0123456789abcdef");
    expect(result.ok).toBe(false);
  });
});
