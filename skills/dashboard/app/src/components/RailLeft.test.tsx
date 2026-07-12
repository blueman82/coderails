// @vitest-environment jsdom
import { describe, it, expect, afterEach } from "vitest";
import { createElement } from "react";
import { render, cleanup } from "@testing-library/react";
import { DashboardContextTestProvider } from "../../test/testUtils/DashboardContextTestProvider";
import { RailLeft } from "./RailLeft";
import type { DashboardSnapshot } from "@/hooks/useDashboardState";
import type { LoopInfo } from "@/lib/collect/sessions";

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

function loop(overrides: Partial<LoopInfo> = {}): LoopInfo {
  return {
    slug: "-project",
    name: "-project",
    sessionId: "S1",
    status: "in-progress",
    workUnitsDone: 1,
    workUnitsTotal: 2,
    evalsFrozen: false,
    unitTitles: [{ title: "wu1", done: true }],
    decisions: [],
    ...overrides,
  };
}

describe("RailLeft — loop decisions", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders the loop's decisions as one-line entries under the Directives block", () => {
    const { container } = render(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ loops: [loop({ decisions: ["13: closed the gap", "6: kept the fallback"] })] }) },
        createElement(RailLeft)
      )
    );

    expect(container.textContent).toContain("13: closed the gap");
    expect(container.textContent).toContain("6: kept the fallback");
  });

  it("renders no decisions sub-list when the active loop's decisions array is empty, leaving the rest of the card unchanged", () => {
    const { container } = render(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ loops: [loop({ decisions: [] })] }) },
        createElement(RailLeft)
      )
    );

    expect(container.querySelectorAll(".hud-decision-item").length).toBe(0);
    expect(container.textContent).toContain("wu1");
    expect(container.textContent).toContain("Loop Evals:");
  });
});
