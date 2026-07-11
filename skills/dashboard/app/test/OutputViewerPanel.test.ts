import { describe, it, expect, afterEach, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { DashboardContextTestProvider } from "./testUtils/DashboardContextTestProvider";
import { OutputViewerPanel, selectDefaultRunId, fetchSettledOutput } from "../src/components/OutputViewerPanel";
import type { DashboardSnapshot } from "../src/hooks/useDashboardState";
import type { RunRecord } from "../src/lib/runlog";

function emptySnapshot(overrides: Partial<DashboardSnapshot> = {}): DashboardSnapshot {
  return {
    sessions: [],
    loops: [],
    gates: [],
    trail: [],
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

describe("selectDefaultRunId", () => {
  it("returns undefined for an empty run list", () => {
    expect(selectDefaultRunId([])).toBeUndefined();
  });

  it("prefers a still-active run (no endedAt) over a finished one, even if the finished run started later", () => {
    const active = run({ runId: "a", startedAt: 100 });
    const finished = run({ runId: "b", startedAt: 200, endedAt: 250, exitCode: 0 });
    expect(selectDefaultRunId([finished, active])).toBe("a");
  });

  it("falls back to the most recently started run when nothing is active", () => {
    const older = run({ runId: "a", startedAt: 100, endedAt: 150, exitCode: 0 });
    const newer = run({ runId: "b", startedAt: 200, endedAt: 250, exitCode: 0 });
    expect(selectDefaultRunId([older, newer])).toBe("b");
  });
});

describe("OutputViewerPanel — rendering (SSR)", () => {
  it("renders an empty state when there are no runs", () => {
    const html = renderToStaticMarkup(
      createElement(DashboardContextTestProvider, { snapshot: emptySnapshot() }, createElement(OutputViewerPanel, { token: "t" }))
    );
    expect(html).toContain("no output");
  });

  it("renders live output from the runOutput map for the default-selected (active) run", () => {
    const active = run({ runId: "live1", startedAt: 100 });
    const html = renderToStaticMarkup(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [active] }), runOutput: { live1: "streaming chunk one" } },
        createElement(OutputViewerPanel, { token: "t" })
      )
    );
    expect(html).toContain("streaming chunk one");
  });

  it("appends a second chunk when runOutput for the same runId grows (chunk-append rendering)", () => {
    const active = run({ runId: "live1", startedAt: 100 });
    const html = renderToStaticMarkup(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [active] }), runOutput: { live1: "chunk one chunk two" } },
        createElement(OutputViewerPanel, { token: "t" })
      )
    );
    expect(html).toContain("chunk one chunk two");
  });

  it("renders each run-history entry as a clickable row carrying its runId", () => {
    const a = run({ runId: "aaaa111122223333", startedAt: 100, endedAt: 150, exitCode: 0 });
    const b = run({ runId: "bbbb111122223333", startedAt: 200, endedAt: 250, exitCode: 1 });
    const html = renderToStaticMarkup(
      createElement(DashboardContextTestProvider, { snapshot: emptySnapshot({ runs: [a, b] }) }, createElement(OutputViewerPanel, { token: "t" }))
    );
    expect(html).toContain("aaaa111122223333");
    expect(html).toContain("bbbb111122223333");
  });

  it("does not render live output for a finished run even if a stale runOutput entry exists for it (live→settled: finished runs never read the live buffer)", () => {
    const finished = run({ runId: "done1", startedAt: 100, endedAt: 150, exitCode: 0 });
    const html = renderToStaticMarkup(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [finished] }), runOutput: { done1: "leftover live text" } },
        createElement(OutputViewerPanel, { token: "t" })
      )
    );
    // SSR never fires the fetch effect, so a finished run's settled output is simply not yet
    // loaded — it must not fall back to rendering the stale live buffer instead.
    expect(html).not.toContain("leftover live text");
  });

  it("renders the projected clean prose by default for a live run's raw stream-json output, not the raw JSON lines", () => {
    // Real shape produced by `claude -p --output-format stream-json`: a text_delta stream_event
    // followed by a final result line — see streamJson.test.ts's projectAssistantText coverage.
    const rawStreamJson =
      [
        JSON.stringify({
          type: "stream_event",
          event: { type: "content_block_delta", index: 0, delta: { type: "text_delta", text: "draft" } },
        }),
        JSON.stringify({ type: "result", subtype: "success", is_error: false, result: "Clean final answer." }),
      ].join("\n") + "\n";
    const active = run({ runId: "live1", startedAt: 100 });
    const html = renderToStaticMarkup(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [active] }), runOutput: { live1: rawStreamJson } },
        createElement(OutputViewerPanel, { token: "t" })
      )
    );
    // Default view shows the projected prose...
    expect(html).toContain("Clean final answer.");
    // ...not the raw JSONL structure (proves default = clean projection, not raw passthrough).
    expect(html).not.toContain("content_block_delta");
    expect(html).not.toContain('"type":"result"');
    // The toggle back to raw is present for a live run — the raw stream-json client-side buffer
    // genuinely differs from the projected clean view.
    expect(html).toContain("hud-output-toggle");
  });

  it("does not render the raw/clean toggle for a settled run (server already extracts clean prose; there is no raw JSONL client-side to toggle to)", () => {
    const finished = run({ runId: "done1", startedAt: 100, endedAt: 150, exitCode: 0 });
    const html = renderToStaticMarkup(
      createElement(DashboardContextTestProvider, { snapshot: emptySnapshot({ runs: [finished] }) }, createElement(OutputViewerPanel, { token: "t" }))
    );
    expect(html).not.toContain("hud-output-toggle");
  });
});

// fetchSettledOutput previously had zero direct coverage (it was only exercised indirectly
// through a mount effect the SSR tests above never fire). It's a standalone exported function
// with no React dependency, so it's tested directly here against a stubbed global.fetch — this
// is also the regression test for the fix: every failure mode used to collapse to `undefined`
// (rendered as the same "no output" a genuinely empty run produces), with nothing logged and no
// way to distinguish "empty" from "the fetch blew up".
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
