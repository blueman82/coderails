// @vitest-environment jsdom
import { describe, it, expect, afterEach } from "vitest";
import { renderHook, act, cleanup } from "@testing-library/react";
import { useDashboardState, type EventSourceLike } from "../src/hooks/useDashboardState";
import type { ContextTrendSummary } from "../src/lib/collect/contextTrend";

// A fake EventSource that records the listeners the hook registers per event
// name, so a test can fire a named frame through the SAME addEventListener path
// production uses. This exercises the SSE_EVENT_NAMES registration loop — the
// bug it guards against: an event name present in the DashboardEvent union and
// handled by mergeDashboardEvent, but MISSING from SSE_EVENT_NAMES, so the
// browser EventSource silently drops the frame (unit tests that call
// mergeDashboardEvent directly never notice — only the wiring does).
class FakeSource implements EventSourceLike {
  listeners = new Map<string, (ev: MessageEvent) => void>();
  onerror: (() => void) | null = null;
  addEventListener(type: string, listener: (ev: MessageEvent) => void): void {
    this.listeners.set(type, listener);
  }
  close(): void {}
  fire(type: string, data: unknown): void {
    const l = this.listeners.get(type);
    if (l) l({ data: JSON.stringify(data) } as MessageEvent);
  }
}

afterEach(() => cleanup());

const summary: ContextTrendSummary = {
  windowStartMs: 1,
  cutoverMs: 2,
  sessions: [],
  before: { n: 0, medianPerTurn: null, q1PerTurn: null, q3PerTurn: null },
  after: { n: 0, medianPerTurn: null, q1PerTurn: null, q3PerTurn: null },
  compactions: [],
};

describe("useDashboardState — SSE event wiring", () => {
  it("dispatches a 'context-trend' frame into the snapshot (regression: event name must be registered)", () => {
    const src = new FakeSource();
    const { result } = renderHook(() => useDashboardState({ createSource: () => src }));

    // A context-trend listener must have been registered — if the event name is
    // missing from SSE_EVENT_NAMES, no listener exists and fire() is a no-op.
    expect(src.listeners.has("context-trend")).toBe(true);

    act(() => src.fire("context-trend", summary));
    expect(result.current.snapshot.contextTrend).toEqual(summary);
  });

  it("registers a listener for every event the client is meant to receive", () => {
    const src = new FakeSource();
    renderHook(() => useDashboardState({ createSource: () => src }));
    for (const name of ["snapshot", "activity", "context-trend", "gates", "runs", "run-output"]) {
      expect(src.listeners.has(name)).toBe(true);
    }
  });
});
