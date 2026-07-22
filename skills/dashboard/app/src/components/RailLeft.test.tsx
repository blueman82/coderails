// @vitest-environment jsdom
import { describe, it, expect, afterEach, vi } from "vitest";
import { createElement } from "react";
import { render, cleanup, act } from "@testing-library/react";
import { DashboardContextTestProvider } from "../../test/testUtils/DashboardContextTestProvider";
import { RailLeft } from "./RailLeft";
import { LOOP_LIVE_WINDOW_MS } from "@/hooks/useDashboardState";
import type { DashboardSnapshot } from "@/hooks/useDashboardState";
import type { LoopInfo } from "@/lib/collect/sessions";

// A fixed "now" the fixtures anchor their lastUpdatedMs against. The provider's
// snapshot is static, but RailLeft reads Date.now() for the live/stalled split,
// so fixtures set lastUpdatedMs relative to real wall-clock time instead.
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

function renderRail(snapshot: DashboardSnapshot) {
  return render(
    createElement(
      DashboardContextTestProvider,
      { snapshot },
      createElement(RailLeft)
    )
  );
}

describe("RailLeft — multi-loop Directives panel", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders one loop-card per live loop", () => {
    const { container } = renderRail(
      emptySnapshot({
        loops: [
          loop({ sessionId: "A", title: "loop-a", lastUpdatedMs: minutesAgo(2) }),
          loop({ sessionId: "B", title: "loop-b", lastUpdatedMs: minutesAgo(10) }),
        ],
      })
    );
    expect(container.querySelectorAll('[data-testid="loop-card"]').length).toBe(2);
  });

  it("shows Live.N in the header suffix counting live loops, not total loops", () => {
    const { container } = renderRail(
      emptySnapshot({
        loops: [
          loop({ sessionId: "A", lastUpdatedMs: minutesAgo(2) }),
          loop({ sessionId: "B", lastUpdatedMs: minutesAgo(10) }),
          loop({ sessionId: "C", lastUpdatedMs: minutesAgo(120) }), // stalled, not counted
        ],
      })
    );
    // The Directives block is the second .hud-block (System Vitals is first).
    const directivesBlock = container.querySelectorAll(".hud-block")[1];
    const suffix = directivesBlock.querySelector(".hud-suffix");
    expect(suffix?.textContent).toBe("Live.2");
    // No legacy Loop.N literal may survive anywhere in the rendered output.
    expect(container.textContent).not.toContain("Loop.");
  });

  it("renders each card's title line with the loop title and done/total counts", () => {
    const { container } = renderRail(
      emptySnapshot({ loops: [loop({ title: "multi-loop panel", workUnitsDone: 3, workUnitsTotal: 7 })] })
    );
    const card = container.querySelector('[data-testid="loop-card"]');
    expect(card?.textContent).toContain("multi-loop panel");
    expect(card?.textContent).toContain("3/7");
  });

  it("renders a per-card evals footer reflecting each loop's evalsFrozen state", () => {
    const { container } = renderRail(
      emptySnapshot({
        loops: [
          loop({ sessionId: "A", evalsFrozen: true, lastUpdatedMs: minutesAgo(2) }),
          loop({ sessionId: "B", evalsFrozen: false, lastUpdatedMs: minutesAgo(10) }),
        ],
      })
    );
    const footers = container.querySelectorAll(".hud-directive-footer");
    expect(footers.length).toBe(2);
    expect(footers[0].textContent).toContain("Frozen ✓");
    expect(footers[1].textContent).toContain("Not Frozen");
  });

  it("renders unit rows with distinct glyphs for done, in-flight, and pending", () => {
    const { container } = renderRail(
      emptySnapshot({
        loops: [
          loop({
            units: [
              { key: "u-done", status: "done" },
              { key: "u-flight", status: "in-flight" },
              { key: "u-pending", status: "pending" },
            ],
          }),
        ],
      })
    );
    const card = container.querySelector('[data-testid="loop-card"]')!;
    const boxes = Array.from(card.querySelectorAll(".hud-box")).map((b) => b.textContent);
    // Three distinct glyphs — one per union state.
    expect(new Set(boxes).size).toBe(3);
    expect(card.textContent).toContain("u-done");
    expect(card.textContent).toContain("u-flight");
    expect(card.textContent).toContain("u-pending");
  });

  it("renders a PR chip on unit rows that carry a pr number, and none otherwise", () => {
    const { container } = renderRail(
      emptySnapshot({
        loops: [
          loop({
            units: [
              { key: "u-pr", status: "done", pr: 166 },
              { key: "u-nopr", status: "pending" },
            ],
          }),
        ],
      })
    );
    const card = container.querySelector('[data-testid="loop-card"]')!;
    const chips = card.querySelectorAll(".hud-pr-chip");
    expect(chips.length).toBe(1);
    expect(chips[0].textContent).toBe("PR #166");
  });

  it("renders a unit description in full, in dim text, with the full text also in a title attribute", () => {
    const long = "a very long description that should render in full, wrapping rather than clamping in the card body";
    const { container } = renderRail(
      emptySnapshot({ loops: [loop({ units: [{ key: "u1", status: "in-flight", description: long }] })] })
    );
    const card = container.querySelector('[data-testid="loop-card"]')!;
    const desc = card.querySelector(".hud-unit-desc");
    expect(desc?.textContent).toBe(long);
    expect(desc?.getAttribute("title")).toBe(long);
  });

  it("lists a stalled loop under stalled-list as one line and gives it NO card", () => {
    const { container } = renderRail(
      emptySnapshot({
        loops: [
          loop({ sessionId: "live", title: "live-loop", lastUpdatedMs: minutesAgo(5) }),
          loop({ sessionId: "stale", title: "stalled-loop", lastUpdatedMs: minutesAgo(90) }),
        ],
      })
    );
    expect(container.querySelectorAll('[data-testid="loop-card"]').length).toBe(1);
    const stalled = container.querySelector('[data-testid="stalled-list"]');
    expect(stalled).not.toBeNull();
    expect(stalled!.textContent).toContain("stalled-loop");
    // The stalled loop's title appears only in the stalled list, never as a card.
    const cardTitles = Array.from(container.querySelectorAll('[data-testid="loop-card"]')).map((c) => c.textContent);
    expect(cardTitles.some((t) => t?.includes("stalled-loop"))).toBe(false);
  });

  it("shows the empty state when both live and stalled lists are empty", () => {
    const { container } = renderRail(emptySnapshot({ loops: [] }));
    expect(container.querySelectorAll('[data-testid="loop-card"]').length).toBe(0);
    expect(container.textContent).toContain("no active loops");
  });

  it("shows the empty state when the only loops are complete", () => {
    const { container } = renderRail(
      emptySnapshot({ loops: [loop({ status: "complete", lastUpdatedMs: minutesAgo(2) })] })
    );
    expect(container.querySelectorAll('[data-testid="loop-card"]').length).toBe(0);
    expect(container.querySelector('[data-testid="stalled-list"]')).toBeNull();
    expect(container.textContent).toContain("no active loops");
  });

  it("treats a loop exactly at the live window boundary as live (a card, not stalled)", () => {
    const { container } = renderRail(
      emptySnapshot({ loops: [loop({ title: "edge", lastUpdatedMs: Date.now() - LOOP_LIVE_WINDOW_MS + 1000 })] })
    );
    expect(container.querySelectorAll('[data-testid="loop-card"]').length).toBe(1);
  });
});

describe("RailLeft — cost KPI tiles", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders costWeek and costMonth values and labels alongside the existing usage tiles", () => {
    const { container } = renderRail(
      emptySnapshot({
        health: [
          { key: "costWeek", value: "$3.75", note: "completed loops only" },
          { key: "costMonth", value: "$12.40", note: "completed loops only · prices as of 2026-07-01" },
        ],
      })
    );
    expect(container.textContent).toContain("Cost (Week)");
    expect(container.textContent).toContain("$3.75");
    expect(container.textContent).toContain("Cost (Month)");
    expect(container.textContent).toContain("$12.40");
    expect(container.textContent).toContain("completed loops only");
  });
});

describe("RailLeft — System Vitals loading vs unavailable", () => {
  afterEach(() => {
    cleanup();
  });

  it("shows a loading state, not 'unavailable', for every KPI tile before the first activity frame arrives (health: [])", () => {
    const { container } = renderRail(emptySnapshot({ health: [] }));
    expect(container.querySelectorAll(".hud-kpi-unavailable").length).toBe(0);
    expect(container.textContent).not.toContain("unavailable");
    expect(container.querySelectorAll(".hud-kpi-loading").length).toBe(6);
  });

  it("still shows 'unavailable' for a tile the collector genuinely could not populate, once health has loaded", () => {
    const { container } = renderRail(
      emptySnapshot({
        health: [
          { key: "usage5h", value: "1.2M tok" },
          { key: "usageWeek", value: "3M tok" },
          { key: "hooksFired", value: "5" },
          { key: "lintFindings", value: null, note: "unavailable: no wiki vault configured" },
          { key: "costWeek", value: null, note: "unavailable: no completed loops in this window" },
          { key: "costMonth", value: null, note: "unavailable: no completed loops in this window" },
        ],
      })
    );
    expect(container.querySelectorAll(".hud-kpi-loading").length).toBe(0);
    const unavailable = container.querySelectorAll(".hud-kpi-unavailable");
    expect(unavailable.length).toBe(3);
  });
});

describe("RailLeft — loop decisions (per card)", () => {
  afterEach(() => {
    cleanup();
  });

  it("renders a live loop's decisions as one-line .hud-decision-item entries in order", () => {
    const { container } = renderRail(
      emptySnapshot({ loops: [loop({ decisions: ["13: closed the gap", "6: kept the fallback"] })] })
    );
    const card = container.querySelector('[data-testid="loop-card"]')!;
    const items = card.querySelectorAll(".hud-decision-item");
    expect(items.length).toBe(2);
    expect(items[0].textContent).toBe("13: closed the gap");
    expect(items[1].textContent).toBe("6: kept the fallback");
  });

  it("renders duplicate decision strings as distinct entries without collapsing them", () => {
    const { container } = renderRail(
      emptySnapshot({ loops: [loop({ decisions: ["6: same text", "6: same text"] })] })
    );
    const items = container.querySelectorAll(".hud-decision-item");
    expect(items.length).toBe(2);
    expect(items[0].textContent).toBe("6: same text");
    expect(items[1].textContent).toBe("6: same text");
  });

  it("renders no decisions sub-list when a live loop's decisions array is empty", () => {
    const { container } = renderRail(emptySnapshot({ loops: [loop({ decisions: [] })] }));
    expect(container.querySelectorAll(".hud-decision-item").length).toBe(0);
    expect(container.textContent).toContain("wu1");
    expect(container.textContent).toContain("Loop Evals:");
  });
});

describe("RailLeft — ticking now demotes a boundary-crossing loop", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
  });

  it("moves a loop from card to stalled list as wall-clock advances, without new props", () => {
    const base = 10_000 * 60_000; // fixed epoch base for both fixture and useNow
    vi.useFakeTimers();
    vi.setSystemTime(base);

    // 59 minutes old at render — live, so it gets a card.
    const { container } = renderRail(
      emptySnapshot({ loops: [loop({ title: "boundary-loop", lastUpdatedMs: base - 59 * 60_000 })] })
    );
    expect(container.querySelectorAll('[data-testid="loop-card"]').length).toBe(1);
    expect(container.querySelector('[data-testid="stalled-list"]')).toBeNull();

    // Advance 2 minutes: the loop is now 61 min old. useNow's 30s interval has
    // fired, so the component re-renders with a fresh `now` and no new props.
    act(() => {
      vi.advanceTimersByTime(2 * 60_000);
    });

    expect(container.querySelectorAll('[data-testid="loop-card"]').length).toBe(0);
    const stalled = container.querySelector('[data-testid="stalled-list"]');
    expect(stalled).not.toBeNull();
    expect(stalled!.textContent).toContain("boundary-loop");
  });
});
