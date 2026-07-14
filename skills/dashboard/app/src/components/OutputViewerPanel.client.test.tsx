// @vitest-environment jsdom
// Client-side (jsdom + testing-library) coverage for the run-output OVERLAY that replaced the
// inline below-the-list <pre> viewer (Task T10). SSR tests in ../../test/OutputViewerPanel.test.ts
// still cover the retained history list and the pure fetch/select helpers; the overlay is
// closed-by-default and interactive (click to open, ESC/backdrop/close to dismiss, live-stream
// append), none of which renderToStaticMarkup can exercise.
import { describe, it, expect, vi, afterEach } from "vitest";
import { createElement } from "react";
import { render, cleanup, fireEvent, act, waitFor } from "@testing-library/react";
import { DashboardContextTestProvider } from "../../test/testUtils/DashboardContextTestProvider";
import { OutputViewerPanel } from "./OutputViewerPanel";
import type { DashboardSnapshot } from "@/hooks/useDashboardState";
import type { RunRecord } from "@/lib/runlog";

function emptySnapshot(overrides: Partial<DashboardSnapshot> = {}): DashboardSnapshot {
  return { sessions: [], loops: [], gates: [], health: [], runs: [], queue: [], builds: [], ...overrides };
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

function historyRow(container: HTMLElement, runId: string): HTMLButtonElement {
  const row = Array.from(container.querySelectorAll("button.hud-run-row-selectable")).find((b) =>
    b.textContent?.includes(runId)
  );
  if (!row) throw new Error(`history row not found for runId: ${runId}`);
  return row as HTMLButtonElement;
}

function overlay(): HTMLElement | null {
  return document.querySelector(".hud-overlay");
}

const MARKDOWN_FIXTURE = "# Run Report\n\nAll good.\n\n```\nnpm test\n```\n";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("OutputViewerPanel — run-output overlay", () => {
  it("(d) does not render the old inline output <pre> region", () => {
    const finished = run({ runId: "done1", startedAt: 100, endedAt: 150, exitCode: 0 });
    const { container } = render(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [finished] }) },
        createElement(OutputViewerPanel, { token: "t" })
      )
    );
    // The retired inline viewer used a .hud-output-viewer <pre> below the list. With the overlay
    // approach nothing output-bearing renders until a row is clicked.
    expect(container.querySelector(".hud-output-viewer")).toBeNull();
    expect(overlay()).toBeNull();
  });

  it("(a) clicking a settled run row opens an overlay rendering its output as MARKDOWN elements (not raw markers)", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", output: MARKDOWN_FIXTURE }), { status: 200 })
    ) as unknown as typeof fetch;
    const finished = run({ runId: "done1", startedAt: 100, endedAt: 150, exitCode: 0 });
    const { container } = render(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [finished] }) },
        createElement(OutputViewerPanel, { token: "t" })
      )
    );

    await act(async () => {
      fireEvent.click(historyRow(container, "done1"));
      await Promise.resolve();
    });

    const el = await waitFor(() => {
      const o = overlay();
      if (!o || !o.querySelector("h1")) throw new Error("overlay markdown not ready");
      return o;
    });

    // Markdown STRUCTURE, not just text: the fixture's `# heading` must be an <h1> and its fenced
    // block a <code>/<pre>. This is what makes the mutation-check bite — render raw text instead
    // of markdown and these element assertions fail.
    const h1 = el.querySelector("h1");
    expect(h1?.textContent).toContain("Run Report");
    expect(el.querySelector("pre code")).not.toBeNull();
    expect(el.querySelector("pre code")?.textContent).toContain("npm test");
    // The literal markdown markers must NOT survive into the rendered text.
    expect(el.textContent).not.toContain("# Run Report");
    expect(el.textContent).not.toContain("```");
  });

  it("(b) closes on the close control, on backdrop click, and on ESC", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", output: MARKDOWN_FIXTURE }), { status: 200 })
    ) as unknown as typeof fetch;
    const finished = run({ runId: "done1", startedAt: 100, endedAt: 150, exitCode: 0 });
    const { container } = render(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [finished] }) },
        createElement(OutputViewerPanel, { token: "t" })
      )
    );

    async function open() {
      await act(async () => {
        fireEvent.click(historyRow(container, "done1"));
        await Promise.resolve();
      });
      await waitFor(() => {
        if (!overlay()) throw new Error("not open");
      });
    }

    // Close control (X button).
    await open();
    await act(async () => {
      fireEvent.click(document.querySelector(".hud-overlay-close") as HTMLElement);
    });
    expect(overlay()).toBeNull();

    // Backdrop click.
    await open();
    await act(async () => {
      fireEvent.click(document.querySelector(".hud-overlay-backdrop") as HTMLElement);
    });
    expect(overlay()).toBeNull();

    // ESC key.
    await open();
    await act(async () => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    expect(overlay()).toBeNull();
  });

  it("(sanitize) renders raw HTML in untrusted run output as escaped text, not live DOM (no XSS)", async () => {
    // Run output is untrusted. react-markdown (no rehype-raw, no dangerouslySetInnerHTML) renders
    // any embedded HTML as escaped text. This locks that property so a future rehype-raw regression
    // that would inject live nodes fails here.
    const malicious = "# Report\n\n<script>window.__pwned = true;</script>\n\n<img src=x onerror=\"window.__pwned=true\">\n";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", output: malicious }), { status: 200 })
    ) as unknown as typeof fetch;
    const finished = run({ runId: "done1", startedAt: 100, endedAt: 150, exitCode: 0 });
    const { container } = render(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [finished] }) },
        createElement(OutputViewerPanel, { token: "t" })
      )
    );
    await act(async () => {
      fireEvent.click(historyRow(container, "done1"));
      await Promise.resolve();
    });
    const el = await waitFor(() => {
      const o = overlay();
      if (!o || !o.querySelector("h1")) throw new Error("not ready");
      return o;
    });
    // No live <script> or <img> node was injected from the untrusted markdown source.
    expect(el.querySelector("script")).toBeNull();
    expect(el.querySelector("img")).toBeNull();
    // The markup appears as visible escaped text instead.
    expect(el.textContent).toContain("<script>");
  });

  it("(beacon) a CommonMark image in untrusted output renders NO <img> element (no tracking-beacon GET on open)", async () => {
    // Distinct from raw-HTML escaping: `![alt](url)` is parsed markdown, a different react-markdown
    // pipeline stage. Without the img component override it renders a live <img> whose GET fires on
    // overlay open with no click. This pins the override — remove it and this fails.
    const withImage = "# Report\n\n![x](https://example.com/tracker.png)\n\nbody text\n";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", output: withImage }), { status: 200 })
    ) as unknown as typeof fetch;
    const finished = run({ runId: "done1", startedAt: 100, endedAt: 150, exitCode: 0 });
    const { container } = render(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [finished] }) },
        createElement(OutputViewerPanel, { token: "t" })
      )
    );
    await act(async () => {
      fireEvent.click(historyRow(container, "done1"));
      await Promise.resolve();
    });
    const el = await waitFor(() => {
      const o = overlay();
      if (!o || !o.querySelector("h1")) throw new Error("not ready");
      return o;
    });
    // No live image element was created from the untrusted markdown source.
    expect(el.querySelector("img")).toBeNull();
    // Surrounding content still renders (the override drops only the image, not the document).
    expect(el.textContent).toContain("body text");
  });

  it("(settled-projection) a settled run whose fetch returns RAW stream-json renders projected prose, not the JSON log", async () => {
    // A crashed/killed run's server-side extractResultText falls back to the raw stream-json log
    // verbatim (no `result` line). The panel must project that on the settled path too, else the
    // overlay dumps a JSON log. Fixture = raw stream-json with a text_delta then a result line.
    const rawStreamJson =
      [
        JSON.stringify({
          type: "stream_event",
          event: { type: "content_block_delta", index: 0, delta: { type: "text_delta", text: "draft" } },
        }),
        JSON.stringify({ type: "result", subtype: "success", is_error: false, result: "# Recovered\n\nclean answer" }),
      ].join("\n") + "\n";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", output: rawStreamJson }), { status: 200 })
    ) as unknown as typeof fetch;
    const finished = run({ runId: "done1", startedAt: 100, endedAt: 150, exitCode: 0 });
    const { container } = render(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [finished] }) },
        createElement(OutputViewerPanel, { token: "t" })
      )
    );
    await act(async () => {
      fireEvent.click(historyRow(container, "done1"));
      await Promise.resolve();
    });
    const el = await waitFor(() => {
      const o = overlay();
      if (!o || !o.querySelector("h1")) throw new Error("not ready");
      return o;
    });
    // Projected prose (the result line), rendered as markdown...
    expect(el.querySelector("h1")?.textContent).toContain("Recovered");
    expect(el.textContent).toContain("clean answer");
    // ...not the raw JSONL structure.
    expect(el.textContent).not.toContain("content_block_delta");
    expect(el.textContent).not.toContain('"type":"result"');
  });

  it("(b') a click inside the overlay panel does NOT close it (only the backdrop does)", async () => {
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", output: MARKDOWN_FIXTURE }), { status: 200 })
    ) as unknown as typeof fetch;
    const finished = run({ runId: "done1", startedAt: 100, endedAt: 150, exitCode: 0 });
    const { container } = render(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [finished] }) },
        createElement(OutputViewerPanel, { token: "t" })
      )
    );
    await act(async () => {
      fireEvent.click(historyRow(container, "done1"));
      await Promise.resolve();
    });
    const panel = await waitFor(() => {
      const p = document.querySelector(".hud-overlay-panel");
      if (!p) throw new Error("not open");
      return p as HTMLElement;
    });
    await act(async () => {
      fireEvent.click(panel);
    });
    expect(overlay()).not.toBeNull();
  });

  it("(c) a live (running) run's overlay live-streams: it re-renders accumulated markdown as runOutput grows", async () => {
    const active = run({ runId: "live1", startedAt: 100 }); // no endedAt => live
    // A live run's overlay reads the live SSE buffer (runOutput), not the settled fetch. The
    // buffer is raw stream-json; the panel projects it to prose then renders as markdown.
    const firstChunk =
      JSON.stringify({
        type: "stream_event",
        event: { type: "content_block_delta", index: 0, delta: { type: "text_delta", text: "# Phase 1\n\nstarting\n" } },
      }) + "\n";
    const { container, rerender } = render(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [active] }), runOutput: { live1: firstChunk } },
        createElement(OutputViewerPanel, { token: "t" })
      )
    );

    await act(async () => {
      fireEvent.click(historyRow(container, "live1"));
      await Promise.resolve();
    });

    await waitFor(() => {
      const o = overlay();
      if (!o || !o.textContent?.includes("Phase 1")) throw new Error("first chunk not rendered");
    });
    // First chunk rendered as a heading, second not yet present.
    expect(overlay()?.querySelector("h1")?.textContent).toContain("Phase 1");
    expect(overlay()?.textContent).not.toContain("Phase 2");

    // A second SSE chunk arrives for the same run: the accumulated buffer grows.
    const secondChunk =
      firstChunk +
      JSON.stringify({
        type: "stream_event",
        event: { type: "content_block_delta", index: 0, delta: { type: "text_delta", text: "\n# Phase 2\n\ndone\n" } },
      }) +
      "\n";
    rerender(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [active] }), runOutput: { live1: secondChunk } },
        createElement(OutputViewerPanel, { token: "t" })
      )
    );

    await waitFor(() => {
      if (!overlay()?.textContent?.includes("Phase 2")) throw new Error("second chunk not appended");
    });
    // Both phases now present — progressive append, still open.
    expect(overlay()?.textContent).toContain("Phase 1");
    expect(overlay()?.textContent).toContain("Phase 2");
  });
});
