// @vitest-environment jsdom
import { emptySnapshot, run, historyRow, overlay, MARKDOWN_FIXTURE } from "./OutputViewerPanel.client.fixture";
import { describe, it, expect, vi } from "vitest";
import { createElement } from "react";
import { render, fireEvent, act, waitFor } from "@testing-library/react";
import { DashboardContextTestProvider } from "../../test/testUtils/DashboardContextTestProvider";
import { OutputViewerPanel } from "./OutputViewerPanel";

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

  it("(gfm-table) a GFM table in run output renders as a real <table>, not literal pipe text", async () => {
    // Bare CommonMark (no remark-gfm) has no table syntax, so a GFM table falls through as one
    // line of literal '| A | B |' text. This pins remarkGfm being wired into the ReactMarkdown
    // pipeline — drop the plugin and this fails (mutation-check).
    const withTable = "# Report\n\n| Field | Value |\n|---|---|\n| Day | Sunday |\n| Count | 3 |\n";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", output: withTable }), { status: 200 })
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
    const table = el.querySelector("table");
    expect(table).not.toBeNull();
    const headers = Array.from(table?.querySelectorAll("th") ?? []).map((th) => th.textContent);
    expect(headers).toEqual(["Field", "Value"]);
    const cells = Array.from(table?.querySelectorAll("td") ?? []).map((td) => td.textContent);
    expect(cells).toEqual(["Day", "Sunday", "Count", "3"]);
    // The literal pipe markers must NOT survive into the rendered text as raw table syntax.
    expect(el.textContent).not.toContain("|---|---|");
  });

  it("(gfm-autolink) a bare URL in run output renders as a real <a>, and a javascript: URL is inerted", async () => {
    // GFM autolink support turns a bare URL into a live <a>. Links are click-gated (unlike the
    // passive image beacon above), so this is acceptable new surface — but confirm react-markdown's
    // default urlTransform still strips javascript: hrefs even with remark-gfm's autolink active.
    const withLinks =
      "# Report\n\nSee https://example.com/results for details.\n\njavascript:alert(1)\n";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", output: withLinks }), { status: 200 })
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
    const links = Array.from(el.querySelectorAll("a"));
    const httpsLink = links.find((a) => a.textContent === "https://example.com/results");
    expect(httpsLink).toBeDefined();
    expect(httpsLink?.getAttribute("href")).toBe("https://example.com/results");
    // A bare `javascript:` URI is NOT autolinked into a live anchor with that scheme as href.
    const jsLink = links.find((a) => a.getAttribute("href")?.startsWith("javascript:"));
    expect(jsLink).toBeUndefined();
  });

  it("(settled-projection) a settled run whose fetch returns RAW stream-json renders projected prose, not the JSON log", async () => {
    // The settled route normally projects current Codex JSONL. Keep the client defensive when a
    // raw log reaches it by projecting the native agent_message event before rendering markdown.
    const rawStreamJson =
      [
        JSON.stringify({ type: "thread.started", thread_id: "t1" }),
        JSON.stringify({ type: "turn.started" }),
        JSON.stringify({
          type: "item.completed",
          item: { id: "item_0", type: "agent_message", text: "# Recovered\n\nclean answer" },
        }),
        JSON.stringify({ type: "turn.completed", usage: {} }),
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
    expect(el.textContent).not.toContain("thread.started");
    expect(el.textContent).not.toContain('"type":"item.completed"');
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
});
