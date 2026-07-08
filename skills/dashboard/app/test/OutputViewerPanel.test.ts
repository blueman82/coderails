import { describe, it, expect } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { DashboardContextTestProvider } from "./testUtils/DashboardContextTestProvider";
import { OutputViewerPanel, selectDefaultRunId } from "../src/components/OutputViewerPanel";
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
});
