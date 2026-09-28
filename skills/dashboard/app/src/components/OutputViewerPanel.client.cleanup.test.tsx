// @vitest-environment jsdom
import { emptySnapshot, run, historyRow, overlay } from "./OutputViewerPanel.client.fixture";
import { describe, it, expect } from "vitest";
import { createElement } from "react";
import { render, fireEvent, act, waitFor } from "@testing-library/react";
import { DashboardContextTestProvider } from "../../test/testUtils/DashboardContextTestProvider";
import { OutputViewerPanel } from "./OutputViewerPanel";

describe("OutputViewerPanel — run-output overlay", () => {

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
