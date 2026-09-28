// @vitest-environment jsdom
// Client-side (jsdom + testing-library) coverage for the run-output OVERLAY that replaced the
// inline below-the-list <pre> viewer (Task T10). SSR tests in ../../test/OutputViewerPanel.test.ts
// still cover the retained history list and the pure fetch/select helpers; the overlay is
// closed-by-default and interactive (click to open, ESC/backdrop/close to dismiss, live-stream
// append), none of which renderToStaticMarkup can exercise.
import { vi, afterEach } from "vitest";

import { cleanup } from "@testing-library/react";

import type { DashboardSnapshot } from "@/hooks/useDashboardState";

import type { RunRecord } from "@/lib/runlog";

function emptySnapshot(overrides: Partial<DashboardSnapshot> = {}): DashboardSnapshot {
  return { sessions: [], loops: [], gates: [], health: [], runs: [], queue: [], builds: [], contextTrend: null, ...overrides };
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

export { emptySnapshot, run, historyRow, overlay, MARKDOWN_FIXTURE };
