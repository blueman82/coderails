// @vitest-environment jsdom
import { describe, it, expect, vi, afterEach } from "vitest";
import { createElement } from "react";
import { render, cleanup, fireEvent, act } from "@testing-library/react";
import { DashboardContextTestProvider } from "../../test/testUtils/DashboardContextTestProvider";
import { RailRight, type DeckButtonDef } from "./RailRight";
import type { DashboardSnapshot } from "@/hooks/useDashboardState";
import type { RunRecord } from "@/lib/runlog";

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

const ASK_BUTTONS: DeckButtonDef[] = [{ name: "ask", label: "Ask", profile: "read-only", inputAllowed: true }];

function findButton(container: HTMLElement, label: string): HTMLButtonElement {
  const btn = Array.from(container.querySelectorAll("button.hud-cmd")).find((b) => b.textContent?.includes(label.toUpperCase()) || b.textContent?.includes(label));
  if (!btn) throw new Error(`button not found for label: ${label}`);
  return btn as HTMLButtonElement;
}

function findInput(container: HTMLElement): HTMLInputElement {
  const input = container.querySelector("input.hud-cmd-input");
  if (!input) throw new Error("ask input not found");
  return input as HTMLInputElement;
}

function mockOkFetch() {
  global.fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({}), { status: 200 })) as unknown as typeof fetch;
}

describe("RailRight — button-state differentiation", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  // A run only produces a completed/failed flash for a button this component itself dispatched
  // (the `queued` flag, set by handleClick's POST, is what the SSE effect's `!stillRelevant`
  // branch keys the outcome-derivation on) — so every scenario below clicks the button first to
  // put it in the same `queued: true` state a real user click would produce, then drives the
  // `runs` prop from active to ended via rerender to simulate the SSE frame confirming it.

  it("applies .completed to a button whose run transitions to endedAt with a PASS outcome", async () => {
    mockOkFetch();
    const { container, rerender } = render(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [] }) },
        createElement(RailRight, { token: "t", buttons: BUTTONS })
      )
    );
    await act(async () => {
      fireEvent.click(findButton(container, "Wiki Lint"));
      await Promise.resolve();
    });

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

  it("applies .failed to a button whose run transitions to endedAt with a FAIL outcome", async () => {
    mockOkFetch();
    const { container, rerender } = render(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [] }) },
        createElement(RailRight, { token: "t", buttons: BUTTONS })
      )
    );
    await act(async () => {
      fireEvent.click(findButton(container, "Wiki Lint"));
      await Promise.resolve();
    });

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

  it("clears the completed/failed class after ~1.5s and returns to plain hud-cmd", async () => {
    mockOkFetch();
    vi.useFakeTimers();
    const { container, rerender } = render(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [] }) },
        createElement(RailRight, { token: "t", buttons: BUTTONS })
      )
    );
    await act(async () => {
      fireEvent.click(findButton(container, "Wiki Lint"));
      await Promise.resolve();
    });

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

    act(() => {
      vi.advanceTimersByTime(1600);
    });

    btn = findButton(container, "Wiki Lint");
    expect(btn.className).not.toContain("completed");
    expect(btn.className).not.toContain("failed");
    expect(btn.className).toBe("hud-cmd");
  });

  it("does not let a stale clear-timeout from a prior run wipe a newer run's state (no cross-contamination)", async () => {
    mockOkFetch();
    vi.useFakeTimers();
    const { container, rerender } = render(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [] }) },
        createElement(RailRight, { token: "t", buttons: BUTTONS })
      )
    );

    // First run: click, then finish as a PASS.
    await act(async () => {
      fireEvent.click(findButton(container, "Wiki Lint"));
      await Promise.resolve();
    });
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
    // SAME button (a fresh click, since the button is idle again with lastOutcome pending clear)
    // and finish it with a different (failed) outcome before the first timer elapses.
    act(() => {
      vi.advanceTimersByTime(500);
    });

    await act(async () => {
      fireEvent.click(findButton(container, "Wiki Lint"));
      await Promise.resolve();
    });
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
    act(() => {
      vi.advanceTimersByTime(1200);
    });
    expect(findButton(container, "Wiki Lint").className).toContain("failed");

    // The second (real) timer, started at the second completion, fires ~1500ms after that point.
    act(() => {
      vi.advanceTimersByTime(400);
    });
    const finalBtn = findButton(container, "Wiki Lint");
    expect(finalBtn.className).not.toContain("failed");
    expect(finalBtn.className).not.toContain("completed");
  });

  it("cleans up pending clear-timeouts on unmount without throwing or updating state after unmount", async () => {
    mockOkFetch();
    vi.useFakeTimers();
    const clearTimeoutSpy = vi.spyOn(global, "clearTimeout");
    const { container, rerender, unmount } = render(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [] }) },
        createElement(RailRight, { token: "t", buttons: BUTTONS })
      )
    );
    await act(async () => {
      fireEvent.click(findButton(container, "Wiki Lint"));
      await Promise.resolve();
    });

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
    expect(clearTimeoutSpy).toHaveBeenCalled();

    // Advancing timers post-unmount must not throw (no update-after-unmount / stale closure crash).
    expect(() => {
      act(() => {
        vi.advanceTimersByTime(2000);
      });
    }).not.toThrow();
  });
});

describe("RailRight — ask input Enter-to-submit", () => {
  afterEach(() => {
    cleanup();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("submits the run when Enter is pressed in the ask input, without Shift", async () => {
    mockOkFetch();
    const { container } = render(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [] }) },
        createElement(RailRight, { token: "t", buttons: ASK_BUTTONS })
      )
    );

    const input = findInput(container);
    fireEvent.change(input, { target: { value: "what is the status" } });
    await act(async () => {
      fireEvent.keyDown(input, { key: "Enter" });
      await Promise.resolve();
    });

    expect(global.fetch).toHaveBeenCalledWith(
      "/api/run",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ token: "t", button: "ask", input: "what is the status" }),
      })
    );
  });

  it("does not submit when Shift+Enter is pressed in the ask input", async () => {
    mockOkFetch();
    const { container } = render(
      createElement(
        DashboardContextTestProvider,
        { snapshot: emptySnapshot({ runs: [] }) },
        createElement(RailRight, { token: "t", buttons: ASK_BUTTONS })
      )
    );

    const input = findInput(container);
    fireEvent.change(input, { target: { value: "what is the status" } });
    await act(async () => {
      fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
      await Promise.resolve();
    });

    expect(global.fetch).not.toHaveBeenCalled();
  });
});
