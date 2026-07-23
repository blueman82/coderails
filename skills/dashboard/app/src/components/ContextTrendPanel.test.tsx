// @vitest-environment jsdom
import { describe, it, expect, afterEach } from "vitest";
import { createElement } from "react";
import { render, cleanup } from "@testing-library/react";
import { DashboardContextTestProvider } from "../../test/testUtils/DashboardContextTestProvider";
import { ContextTrendPanel } from "./ContextTrendPanel";
import type { DashboardSnapshot } from "@/hooks/useDashboardState";
import type { ContextTrendSummary, TrendSession } from "@/lib/collect/contextTrend";

const CUTOVER = Date.parse("2026-07-17T20:22:00Z");
const WINDOW_START = Date.parse("2026-07-07T00:00:00Z");

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

function session(sessionId: string, startMs: number, turns: number, cacheRead: number): TrendSession {
  return { sessionId, startMs, turns, cacheRead };
}

// n sessions spread across `days` days from `fromMs`, single-turn so the
// per-turn value is the cacheRead itself.
function sessionSpread(prefix: string, n: number, fromMs: number, days: number, cacheRead: number): TrendSession[] {
  return Array.from({ length: n }, (_, i) =>
    session(`${prefix}-${i}`, fromMs + (i * days * 24 * 60 * 60_000) / Math.max(1, n), 1, cacheRead)
  );
}

function summary(overrides: Partial<ContextTrendSummary> = {}): ContextTrendSummary {
  const before = sessionSpread("b", 25, WINDOW_START, 10, 240_000);
  const after = sessionSpread("a", 3, CUTOVER + 60_000, 4, 180_000);
  return {
    windowStartMs: WINDOW_START,
    cutoverMs: CUTOVER,
    sessions: [...before, ...after],
    before: { n: 25, medianPerTurn: 240_000, q1PerTurn: 150_000, q3PerTurn: 320_000 },
    after: { n: 3, medianPerTurn: 180_000, q1PerTurn: 110_000, q3PerTurn: 240_000 },
    compactions: [
      { timestampMs: Date.parse("2026-07-08T07:35:00Z"), trigger: "manual" },
      { timestampMs: Date.parse("2026-07-14T18:26:00Z"), trigger: "manual" },
    ],
    ...overrides,
  };
}

// A non-empty health array means the activity slice has resolved, so a null
// contextTrend is a genuine collector failure rather than a not-yet-loaded
// state (the panel keys off snapshot.health the same way RailLeft does). Every
// test that renders a real summary is unaffected; only the null cases care.
const LOADED_HEALTH: DashboardSnapshot["health"] = [{ key: "hooksFired", value: "1" }];

function renderPanel(
  contextTrend: ContextTrendSummary | null,
  health: DashboardSnapshot["health"] = LOADED_HEALTH
) {
  return render(
    createElement(
      DashboardContextTestProvider,
      { snapshot: emptySnapshot({ contextTrend, health }) },
      createElement(ContextTrendPanel)
    )
  );
}

afterEach(() => {
  cleanup();
});

describe("ContextTrendPanel — honesty requirements", () => {
  it("never renders a headline percentage or a savings claim", () => {
    const { container } = renderPanel(summary());
    expect(container.textContent).not.toContain("%");
    expect(container.textContent?.toLowerCase()).not.toContain("saved");
    expect(container.textContent?.toLowerCase()).not.toContain("saving of");
  });

  it("shows n for both sides of the cutover", () => {
    const { container } = renderPanel(summary());
    expect(container.textContent).toContain("n=25");
    expect(container.textContent).toContain("n=3");
  });

  it("says on the panel that a small after side is too few to call, in the caveat style", () => {
    const { container } = renderPanel(summary());
    const caveats = Array.from(container.querySelectorAll(".hud-trend-caveat")).map((c) => c.textContent ?? "");
    expect(caveats.some((t) => t.includes("n=3") && t.includes("too few"))).toBe(true);
  });

  it("does not caveat the after side once it has enough sessions to read", () => {
    const after = sessionSpread("a", 25, CUTOVER + 60_000, 4, 180_000);
    const { container } = renderPanel(
      summary({
        sessions: [...sessionSpread("b", 25, WINDOW_START, 10, 240_000), ...after],
        after: { n: 25, medianPerTurn: 180_000, q1PerTurn: 110_000, q3PerTurn: 240_000 },
      })
    );
    const caveats = Array.from(container.querySelectorAll(".hud-trend-caveat")).map((c) => c.textContent ?? "");
    expect(caveats.some((t) => t.includes("too few"))).toBe(false);
    // The median for a readable side is drawn as signal, not caveat.
    expect(container.querySelector('[data-testid="trend-median-after"]')?.getAttribute("data-thin")).toBeNull();
  });

  it("marks a small side's median as thin (caveat treatment) while still drawing every dot", () => {
    const { container } = renderPanel(summary());
    expect(container.querySelector('[data-testid="trend-median-after"]')?.getAttribute("data-thin")).toBe("true");
    expect(container.querySelectorAll('[data-testid="trend-dot"]').length).toBe(28);
  });

  it("surfaces the compaction-inertness caveat when zero compactions postdate the cutover", () => {
    const { container } = renderPanel(summary());
    const caveats = Array.from(container.querySelectorAll(".hud-trend-caveat")).map((c) => c.textContent ?? "");
    expect(caveats.some((t) => t.includes("fired 0 times since the cutover") && t.includes("07-14"))).toBe(true);
  });

  it("drops the inertness caveat and shows a plain count once compaction fires after the cutover", () => {
    const { container } = renderPanel(
      summary({
        compactions: [
          { timestampMs: Date.parse("2026-07-14T18:26:00Z"), trigger: "manual" },
          { timestampMs: Date.parse("2026-07-19T10:00:00Z"), trigger: "manual" },
        ],
      })
    );
    const caveats = Array.from(container.querySelectorAll(".hud-trend-caveat")).map((c) => c.textContent ?? "");
    expect(caveats.some((t) => t.includes("fired 0 times"))).toBe(false);
    expect(container.textContent).toContain("compactions since cutover");
  });
});

describe("ContextTrendPanel — chart structure", () => {
  it("renders one dot per session, identically colored on both sides of the cutover", () => {
    const { container } = renderPanel(summary());
    const dots = Array.from(container.querySelectorAll('[data-testid="trend-dot"]'));
    expect(dots.length).toBe(28);
    expect(new Set(dots.map((d) => d.getAttribute("fill"))).size).toBe(1);
  });

  it("draws the cutover as a single annotation line", () => {
    const { container } = renderPanel(summary());
    expect(container.querySelectorAll('[data-testid="trend-cutover"]').length).toBe(1);
    expect(container.textContent).toContain("CUTOVER 07-17");
  });

  it("renders a compaction tick per event and the zero-since-cutover track label", () => {
    const { container } = renderPanel(summary());
    const track = container.querySelector('[data-testid="trend-compactions"]')!;
    expect(track.querySelectorAll("path").length).toBe(2);
    expect(track.textContent).toContain("0 SINCE CUTOVER");
  });

  it("shows per-side median and IQR in the stat rows so no value is hover-gated", () => {
    const { container } = renderPanel(summary());
    expect(container.textContent).toContain("med 240K/turn");
    expect(container.textContent).toContain("iqr 150K–320K");
    expect(container.textContent).toContain("med 180K/turn");
  });
});

describe("ContextTrendPanel — degraded states", () => {
  it("renders unavailable when the collector had no source", () => {
    const { container } = renderPanel(null);
    expect(container.textContent).toContain("unavailable: no local usage source");
    expect(container.querySelectorAll('[data-testid="trend-dot"]').length).toBe(0);
  });

  it("renders an empty state when the window holds no cohort sessions", () => {
    const { container } = renderPanel(
      summary({
        sessions: [],
        before: { n: 0, medianPerTurn: null, q1PerTurn: null, q3PerTurn: null },
        after: { n: 0, medianPerTurn: null, q1PerTurn: null, q3PerTurn: null },
      })
    );
    expect(container.textContent).toContain("no agentic-loop sessions since 07-07");
  });

  it("labels an empty side 'no sessions' rather than inventing stats", () => {
    const { container } = renderPanel(
      summary({
        sessions: sessionSpread("b", 25, WINDOW_START, 10, 240_000),
        after: { n: 0, medianPerTurn: null, q1PerTurn: null, q3PerTurn: null },
      })
    );
    expect(container.textContent).toContain("no sessions");
    expect(container.querySelector('[data-testid="trend-median-after"]')).toBeNull();
  });
});
