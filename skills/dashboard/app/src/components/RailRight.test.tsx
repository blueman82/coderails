// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { createElement } from "react";
import { render, cleanup } from "@testing-library/react";
import { DashboardContextTestProvider } from "../../test/testUtils/DashboardContextTestProvider";
import { RailRight, type DeckButtonDef } from "./RailRight";
import type { DashboardSnapshot } from "@/hooks/useDashboardState";
import type { RunRecord } from "@/lib/runlog";

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
    runId: "r1",
    button: "wiki-lint",
    argv: [],
    cwd: "/",
    profile: "read-only",
    startedAt: 1000,
    outputPath: "/tmp/x.log",
    ...overrides,
  };
}

const BUTTONS: DeckButtonDef[] = [{ name: "wiki-lint", label: "Wiki Lint", profile: "read-only", inputAllowed: false }];

function findButton(container: HTMLElement, label: string): HTMLButtonElement {
  const btn = Array.from(container.querySelectorAll("button.hud-cmd")).find((b) => b.textContent?.includes(label.toUpperCase()) || b.textContent?.includes(label));
  if (!btn) throw new Error(`button not found for label: ${label}`);
  return btn as HTMLButtonElement;
}

describe("RailRight — button-state differentiation", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("applies .completed to a button whose run transitions to endedAt with a PASS outcome", () => {
    const active = run({ runId: "r1", startedAt: 1000 });
    const { container, rerender } = render(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [active] }) },
        createElement(RailRight, { token: "t", buttons: BUTTONS })
      )
    );
    const finished = run({ runId: "r1", startedAt: 1000, endedAt: 2000, exitCode: 0 });
    rerender(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [finished] }) },
        createElement(RailRight, { token: "t", buttons: BUTTONS })
      )
    );
    const btn = findButton(container, "Wiki Lint");
    expect(btn.className).toContain("completed");
  });

  it("applies .failed to a button whose run transitions to endedAt with a FAIL outcome", () => {
    const active = run({ runId: "r2", startedAt: 1000 });
    const { container, rerender } = render(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [active] }) },
        createElement(RailRight, { token: "t", buttons: BUTTONS })
      )
    );
    const finished = run({ runId: "r2", startedAt: 1000, endedAt: 2000, exitCode: 1 });
    rerender(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [finished] }) },
        createElement(RailRight, { token: "t", buttons: BUTTONS })
      )
    );
    const btn = findButton(container, "Wiki Lint");
    expect(btn.className).toContain("failed");
  });

  it("clears the completed/failed class after ~1.5s and returns to plain hud-cmd", () => {
    vi.useFakeTimers();
    const active = run({ runId: "r3", startedAt: 1000 });
    const { container, rerender } = render(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [active] }) },
        createElement(RailRight, { token: "t", buttons: BUTTONS })
      )
    );
    const finished = run({ runId: "r3", startedAt: 1000, endedAt: 2000, exitCode: 0 });
    rerender(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [finished] }) },
        createElement(RailRight, { token: "t", buttons: BUTTONS })
      )
    );

    let btn = findButton(container, "Wiki Lint");
    expect(btn.className).toContain("completed");

    vi.advanceTimersByTime(1600);

    btn = findButton(container, "Wiki Lint");
    expect(btn.className).not.toContain("completed");
    expect(btn.className).not.toContain("failed");
    expect(btn.className).toBe("hud-cmd");
  });

  it("does not let a stale clear-timeout from a prior run wipe a newer run's state (no cross-contamination)", () => {
    vi.useFakeTimers();
    const firstActive = run({ runId: "r4a", startedAt: 1000 });
    const { container, rerender } = render(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [firstActive] }) },
        createElement(RailRight, { token: "t", buttons: BUTTONS })
      )
    );
    const firstFinished = run({ runId: "r4a", startedAt: 1000, endedAt: 2000, exitCode: 0 });
    rerender(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [firstFinished] }) },
        createElement(RailRight, { token: "t", buttons: BUTTONS })
      )
    );
    expect(findButton(container, "Wiki Lint").className).toContain("completed");

    // Advance partway through the first timer (not yet fired), then start a second run for the
    // SAME button and finish it with a different (failed) outcome before the first timer elapses.
    vi.advanceTimersByTime(500);

    const secondActive = run({ runId: "r4b", startedAt: 2600 });
    rerender(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [firstFinished, secondActive] }) },
        createElement(RailRight, { token: "t", buttons: BUTTONS })
      )
    );
    const secondFinished = run({ runId: "r4b", startedAt: 2600, endedAt: 3000, exitCode: 1 });
    rerender(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [firstFinished, secondFinished] }) },
        createElement(RailRight, { token: "t", buttons: BUTTONS })
      )
    );
    expect(findButton(container, "Wiki Lint").className).toContain("failed");

    // Advance past when the FIRST (stale) timer would have fired (total elapsed from first
    // completion: 500 + 1200 = 1700ms > 1500ms). If the stale timer weren't cleared, it would
    // incorrectly clear lastOutcome now, wiping the second run's still-fresh "failed" state.
    vi.advanceTimersByTime(1200);
    expect(findButton(container, "Wiki Lint").className).toContain("failed");

    // The second (real) timer, started at the second completion, fires ~1500ms after that point.
    vi.advanceTimersByTime(400);
    const finalBtn = findButton(container, "Wiki Lint");
    expect(finalBtn.className).not.toContain("failed");
    expect(finalBtn.className).not.toContain("completed");
  });

  it("cleans up pending clear-timeouts on unmount without throwing or updating state after unmount", () => {
    vi.useFakeTimers();
    const setTimeoutSpy = vi.spyOn(global, "clearTimeout");
    const active = run({ runId: "r5", startedAt: 1000 });
    const { container, rerender, unmount } = render(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [active] }) },
        createElement(RailRight, { token: "t", buttons: BUTTONS })
      )
    );
    const finished = run({ runId: "r5", startedAt: 1000, endedAt: 2000, exitCode: 0 });
    rerender(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [finished] }) },
        createElement(RailRight, { token: "t", buttons: BUTTONS })
      )
    );
    expect(findButton(container, "Wiki Lint").className).toContain("completed");

    expect(() => unmount()).not.toThrow();
    expect(setTimeoutSpy).toHaveBeenCalled();

    // Advancing timers post-unmount must not throw (no update-after-unmount / stale closure crash).
    expect(() => vi.advanceTimersByTime(2000)).not.toThrow();
  });
});
