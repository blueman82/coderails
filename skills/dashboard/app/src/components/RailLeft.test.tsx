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
    title: "-project",
    sessionId: "S1",
    status: "in-progress",
    workUnitsDone: 1,
    workUnitsTotal: 2,
    evalsFrozen: false,
    lastUpdatedMs: 0,
    units: [{ key: "wu1", status: "done" }],
    decisions: [],
    ...overrides,
  };
}

describe("RailLeft — loop decisions", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders the loop's decisions as one-line .hud-decision-item entries, in the given order, under the Directives block", () => {
    const { container } = render(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ loops: [loop({ decisions: ["13: closed the gap", "6: kept the fallback"] })] }) },
        createElement(RailLeft)
      )
    );

    const items = container.querySelectorAll(".hud-decision-item");
    expect(items.length).toBe(2);
    expect(items[0].textContent).toBe("13: closed the gap");
    expect(items[1].textContent).toBe("6: kept the fallback");

    const directives = container.querySelector(".hud-directive-footer");
    expect(directives).not.toBeNull();
  });

  it("renders duplicate decision strings as distinct entries without collapsing them", () => {
    const { container } = render(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ loops: [loop({ decisions: ["6: same text", "6: same text"] })] }) },
        createElement(RailLeft)
      )
    );

    const items = container.querySelectorAll(".hud-decision-item");
    expect(items.length).toBe(2);
    expect(items[0].textContent).toBe("6: same text");
    expect(items[1].textContent).toBe("6: same text");
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
