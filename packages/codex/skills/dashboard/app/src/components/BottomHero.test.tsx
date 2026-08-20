// @vitest-environment jsdom
import { describe, it, expect, afterEach } from "vitest";
import { createElement } from "react";
import { render, cleanup } from "@testing-library/react";
import { DashboardContextTestProvider } from "../../test/testUtils/DashboardContextTestProvider";
import { BottomHero } from "./BottomHero";
import type { DashboardSnapshot } from "@/hooks/useDashboardState";
import type { LoopInfo } from "@/lib/collect/sessions";

function minutesAgo(minutes: number): number {
  return Date.now() - minutes * 60_000;
}

function emptySnapshot(overrides: Partial<DashboardSnapshot> = {}): DashboardSnapshot {
  return {
    sessions: [],
    loops: [],
    gates: [],
    health: [],
    runs: [],
    queue: [],
    builds: [],
    contextTrend: null,
    ...overrides,
  };
}

function loop(overrides: Partial<LoopInfo> = {}): LoopInfo {
  return {
    slug: "-project",
    title: "-project",
    sessionId: "S1",
    status: "in-progress",
    workUnitsDone: 1,
    workUnitsTotal: 2,
    evalsFrozen: false,
    lastUpdatedMs: minutesAgo(5),
    units: [{ key: "wu1", status: "done" }],
    decisions: [],
    ...overrides,
  };
}

function renderHero(snapshot: DashboardSnapshot) {
  return render(
    createElement(DashboardContextTestProvider, { snapshot }, createElement(BottomHero))
  );
}

describe("BottomHero — follows the most-recent live loop", () => {
  afterEach(() => {
    cleanup();
  });

  it("shows the most recently updated live loop (liveLoops[0])", () => {
    const { container } = renderHero(
      emptySnapshot({
        loops: [
          loop({ sessionId: "older", title: "older-loop", lastUpdatedMs: minutesAgo(30), workUnitsDone: 2, workUnitsTotal: 5 }),
          loop({ sessionId: "newer", title: "newer-loop", lastUpdatedMs: minutesAgo(2), workUnitsDone: 4, workUnitsTotal: 9 }),
        ],
      })
    );
    expect(container.textContent).toContain("newer-loop");
    expect(container.textContent).not.toContain("older-loop");
    expect(container.textContent).toContain("4/9");
  });

  it("ignores stalled loops when choosing the hero loop", () => {
    const { container } = renderHero(
      emptySnapshot({
        loops: [
          loop({ sessionId: "stale", title: "stalled-loop", lastUpdatedMs: minutesAgo(200) }),
          loop({ sessionId: "live", title: "live-loop", lastUpdatedMs: minutesAgo(3) }),
        ],
      })
    );
    expect(container.textContent).toContain("live-loop");
    expect(container.textContent).not.toContain("stalled-loop");
  });

  it("shows the empty state when there are no loops at all", () => {
    const { container } = renderHero(emptySnapshot({ loops: [] }));
    expect(container.textContent).toContain("no active loop");
  });

  it("shows the empty state when the only loops are stalled (none live)", () => {
    const { container } = renderHero(
      emptySnapshot({ loops: [loop({ sessionId: "stale", title: "stalled-loop", lastUpdatedMs: minutesAgo(200) })] })
    );
    expect(container.textContent).toContain("no active loop");
    expect(container.textContent).not.toContain("stalled-loop");
  });
});
