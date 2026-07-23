import { describe, it, expect } from "vitest";
import {
  mergeDashboardEvent,
  markReconnecting,
  initialDashboardState,
  isGateError,
  formatClockTime,
  formatRelativeAge,
  formatDuration,
  formatHHMM,
  runResultLabel,
  liveLoops,
  stalledLoops,
  LOOP_LIVE_WINDOW_MS,
  type DashboardState,
  type DashboardSnapshot,
} from "../src/hooks/useDashboardState";
import type { PrGate, PrGateError } from "../src/lib/collect/prGates";
import type { LoopInfo } from "../src/lib/collect/sessions";
import type { RunRecord } from "../src/lib/runlog";

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

describe("mergeDashboardEvent — snapshot", () => {
  it("replaces the whole snapshot and marks status online", () => {
    const snapshot = emptySnapshot({ runs: [{ runId: "r1" } as RunRecord] });
    const next = mergeDashboardEvent(initialDashboardState, { event: "snapshot", data: snapshot }, 1000);
    expect(next.snapshot).toBe(snapshot);
    expect(next.status).toBe("online");
    expect(next.lastUpdate).toBe(1000);
  });

  it("preserves the existing runOutput buffer — a later snapshot frame carries no output data and must not drop an in-progress run's accumulated live output", () => {
    const base: DashboardState = {
      snapshot: emptySnapshot(),
      status: "online",
      lastUpdate: 0,
      runOutput: { abc: "already streamed" },
    };
    const next = mergeDashboardEvent(base, { event: "snapshot", data: emptySnapshot() }, 1000);
    expect(next.runOutput).toEqual({ abc: "already streamed" });
  });
});

describe("mergeDashboardEvent — activity", () => {
  it("overlays sessions/loops/health onto the existing snapshot without touching gates/runs", () => {
    const base: DashboardState = {
      snapshot: emptySnapshot({ gates: [{ repo: "r", error: "boom" }], runs: [{ runId: "r1" } as RunRecord] }),
      status: "online",
      lastUpdate: 500,
      runOutput: {},
    };
    const activity = {
      sessions: [{ project: "p", lastActivity: 1, state: "active" as const }],
      loops: [],
      health: [{ key: "hooksFired" as const, value: "3" }],
      queue: [],
      builds: [{ schemaVersion: 1, hash: "a".repeat(64), state: "running" as const }],
    };
    const next = mergeDashboardEvent(base, { event: "activity", data: activity }, 2000);
    expect(next.snapshot.sessions).toEqual(activity.sessions);
    expect(next.snapshot.health).toEqual(activity.health);
    expect(next.snapshot.builds).toEqual(activity.builds);
    expect(next.snapshot.gates).toEqual(base.snapshot.gates);
    expect(next.snapshot.runs).toEqual(base.snapshot.runs);
    expect(next.lastUpdate).toBe(2000);
  });

  it("does NOT carry contextTrend — that slice arrives on its own frame", () => {
    // Regression guard for the decoupling: contextTrend must not ride the
    // activity frame, or the slow transcript-streaming collect would gate the
    // KPI tiles again (the ~10s cold-cache all-loading regression).
    const base: DashboardState = {
      snapshot: emptySnapshot({ contextTrend: undefined }),
      status: "online",
      lastUpdate: 500,
      runOutput: {},
    };
    const activity = { sessions: [], loops: [], health: [{ key: "hooksFired" as const, value: "3" }], queue: [], builds: [] };
    const next = mergeDashboardEvent(base, { event: "activity", data: activity }, 2000);
    // An activity frame arriving must leave contextTrend at its loading value,
    // NOT resolve it to null/data.
    expect(next.snapshot.contextTrend).toBeUndefined();
  });
});

describe("mergeDashboardEvent — context-trend", () => {
  it("folds a context-trend frame into the snapshot without touching activity slices", () => {
    const base: DashboardState = {
      snapshot: emptySnapshot({
        contextTrend: undefined,
        health: [{ key: "hooksFired", value: "3" }],
        sessions: [{ project: "p", lastActivity: 1, state: "active" }],
      }),
      status: "online",
      lastUpdate: 500,
      runOutput: {},
    };
    const summary = {
      windowStartMs: 1,
      cutoverMs: 2,
      sessions: [],
      before: { n: 0, medianPerTurn: null, q1PerTurn: null, q3PerTurn: null },
      after: { n: 0, medianPerTurn: null, q1PerTurn: null, q3PerTurn: null },
      compactions: [],
    };
    const next = mergeDashboardEvent(base, { event: "context-trend", data: summary }, 2000);
    expect(next.snapshot.contextTrend).toEqual(summary);
    // Untouched: activity slices remain as they were.
    expect(next.snapshot.health).toEqual(base.snapshot.health);
    expect(next.snapshot.sessions).toEqual(base.snapshot.sessions);
    expect(next.lastUpdate).toBe(2000);
  });

  it("carries null (unreadable source) through as-is", () => {
    const base: DashboardState = {
      snapshot: emptySnapshot({ contextTrend: undefined }),
      status: "online",
      lastUpdate: 500,
      runOutput: {},
    };
    const next = mergeDashboardEvent(base, { event: "context-trend", data: null }, 2000);
    expect(next.snapshot.contextTrend).toBeNull();
  });
});

describe("mergeDashboardEvent — gates", () => {
  it("replaces only the gates slice", () => {
    const base: DashboardState = { snapshot: emptySnapshot({ sessions: [{ project: "p", lastActivity: 1, state: "idle" }] }), status: "online", lastUpdate: 0, runOutput: {} };
    const gates: (PrGate | PrGateError)[] = [{ repo: "r", error: "auth failed" }];
    const next = mergeDashboardEvent(base, { event: "gates", data: gates }, 3000);
    expect(next.snapshot.gates).toBe(gates);
    expect(next.snapshot.sessions).toEqual(base.snapshot.sessions);
  });
});

describe("mergeDashboardEvent — runs", () => {
  it("replaces only the runs slice", () => {
    const base: DashboardState = { snapshot: emptySnapshot(), status: "online", lastUpdate: 0, runOutput: {} };
    const runs: RunRecord[] = [{ runId: "abc", button: "wiki-lint", argv: [], cwd: "/", profile: "standard", startedAt: 1, outputPath: "/tmp/x" }];
    const next = mergeDashboardEvent(base, { event: "runs", data: runs }, 4000);
    expect(next.snapshot.runs).toBe(runs);
    expect(next.lastUpdate).toBe(4000);
  });

  it("prunes a runOutput entry for a runId absent from the incoming runs snapshot (rolled off the server-side cap)", () => {
    const base: DashboardState = {
      snapshot: emptySnapshot(),
      status: "online",
      lastUpdate: 0,
      runOutput: { rolledOff: "old output", stillPresent: "current output" },
    };
    const runs: RunRecord[] = [
      { runId: "stillPresent", button: "wiki-lint", argv: [], cwd: "/", profile: "standard", startedAt: 1, outputPath: "/tmp/x" },
    ];
    const next = mergeDashboardEvent(base, { event: "runs", data: runs }, 5000);
    expect(next.runOutput).toEqual({ stillPresent: "current output" });
  });

  it("keeps every runOutput entry whose runId is still present in the incoming runs snapshot", () => {
    const base: DashboardState = {
      snapshot: emptySnapshot(),
      status: "online",
      lastUpdate: 0,
      runOutput: { a: "a-out", b: "b-out" },
    };
    const runs: RunRecord[] = [
      { runId: "a", button: "wiki-lint", argv: [], cwd: "/", profile: "standard", startedAt: 1, outputPath: "/tmp/a" },
      { runId: "b", button: "wiki-lint", argv: [], cwd: "/", profile: "standard", startedAt: 2, outputPath: "/tmp/b" },
    ];
    const next = mergeDashboardEvent(base, { event: "runs", data: runs }, 6000);
    expect(next.runOutput).toEqual({ a: "a-out", b: "b-out" });
  });
});

describe("mergeDashboardEvent — run-output", () => {
  it("appends the first chunk for a runId into an empty runOutput map", () => {
    const base: DashboardState = { snapshot: emptySnapshot(), status: "online", lastUpdate: 0, runOutput: {} };
    const next = mergeDashboardEvent(base, { event: "run-output", data: { runId: "abc", chunk: "hello " } }, 100);
    expect(next.runOutput).toEqual({ abc: "hello " });
    expect(next.lastUpdate).toBe(100);
  });

  it("concatenates subsequent chunks for the same runId in arrival order", () => {
    const base: DashboardState = {
      snapshot: emptySnapshot(),
      status: "online",
      lastUpdate: 0,
      runOutput: { abc: "hello " },
    };
    const next = mergeDashboardEvent(base, { event: "run-output", data: { runId: "abc", chunk: "world" } }, 200);
    expect(next.runOutput).toEqual({ abc: "hello world" });
  });

  it("keeps separate runIds' buffers independent", () => {
    const base: DashboardState = {
      snapshot: emptySnapshot(),
      status: "online",
      lastUpdate: 0,
      runOutput: { abc: "foo" },
    };
    const next = mergeDashboardEvent(base, { event: "run-output", data: { runId: "def", chunk: "bar" } }, 300);
    expect(next.runOutput).toEqual({ abc: "foo", def: "bar" });
  });

  it("does not touch the rest of the snapshot", () => {
    const base: DashboardState = {
      snapshot: emptySnapshot({ runs: [{ runId: "r1" } as RunRecord] }),
      status: "online",
      lastUpdate: 0,
      runOutput: {},
    };
    const next = mergeDashboardEvent(base, { event: "run-output", data: { runId: "abc", chunk: "x" } }, 400);
    expect(next.snapshot).toBe(base.snapshot);
  });
});

describe("markReconnecting", () => {
  it("flips status to reconnecting while preserving the last-good snapshot", () => {
    const base: DashboardState = { snapshot: emptySnapshot({ runs: [{ runId: "r1" } as RunRecord] }), status: "online", lastUpdate: 10, runOutput: {} };
    const next = markReconnecting(base);
    expect(next.status).toBe("reconnecting");
    expect(next.snapshot).toBe(base.snapshot);
    expect(next.lastUpdate).toBe(base.lastUpdate);
  });

  it("is idempotent — reconnecting twice returns an equivalent state", () => {
    const base: DashboardState = { snapshot: emptySnapshot(), status: "reconnecting", lastUpdate: 5, runOutput: {} };
    const next = markReconnecting(base);
    expect(next).toBe(base);
  });
});

describe("isGateError", () => {
  it("distinguishes PrGateError (has .error) from PrGate (no .error)", () => {
    const gate: PrGate = { repo: "r", number: 1, title: "t", headSha: "abc", review: "missing", evals: "missing", state: "blocked" };
    const gateError: PrGateError = { repo: "r", error: "gh auth failed" };
    expect(isGateError(gate)).toBe(false);
    expect(isGateError(gateError)).toBe(true);
  });
});

describe("formatClockTime", () => {
  it("zero-pads HH:MM:SS", () => {
    expect(formatClockTime(new Date(2026, 0, 1, 9, 5, 3))).toBe("09:05:03");
  });
});

describe("formatRelativeAge", () => {
  it("floors sub-minute deltas to 'just now'", () => {
    expect(formatRelativeAge(1_000, 1_500)).toBe("just now");
  });
  it("renders minutes under an hour", () => {
    expect(formatRelativeAge(0, 5 * 60_000)).toBe("5m");
  });
  it("renders hours under a day", () => {
    expect(formatRelativeAge(0, 3 * 3_600_000)).toBe("3h");
  });
  it("renders days at/after 24h", () => {
    expect(formatRelativeAge(0, 2 * 86_400_000)).toBe("2d");
  });
  it("floors a future mtime (clock skew) to 'just now' rather than a negative value", () => {
    expect(formatRelativeAge(10_000, 0)).toBe("just now");
  });
});

describe("formatDuration", () => {
  it("renders sub-minute durations as NS", () => {
    expect(formatDuration(0, 42_000)).toBe("42S");
  });
  it("renders multi-minute durations as NMNS", () => {
    expect(formatDuration(0, (3 * 60 + 10) * 1000)).toBe("3M10S");
  });
});

describe("formatHHMM", () => {
  it("zero-pads HH:MM", () => {
    expect(formatHHMM(new Date(2026, 0, 1, 7, 0).getTime())).toBe("07:00");
  });
});

describe("liveLoops / stalledLoops", () => {
  const NOW = 10_000 * 60_000; // arbitrary fixed "now" in ms

  function loop(overrides: Partial<LoopInfo>): LoopInfo {
    return {
      slug: "s",
      title: "s",
      sessionId: "id",
      status: "in-progress",
      workUnitsDone: 0,
      workUnitsTotal: 0,
      evalsFrozen: false,
      lastUpdatedMs: NOW,
      units: [],
      decisions: [],
      ...overrides,
    };
  }

  it("classifies a loop updated 59 minutes ago as live", () => {
    const recent = loop({ sessionId: "recent", lastUpdatedMs: NOW - 59 * 60_000 });
    expect(liveLoops([recent], NOW)).toEqual([recent]);
    expect(stalledLoops([recent], NOW)).toEqual([]);
  });

  it("classifies a loop updated 61 minutes ago as stalled, not live", () => {
    const old = loop({ sessionId: "old", lastUpdatedMs: NOW - 61 * 60_000 });
    expect(liveLoops([old], NOW)).toEqual([]);
    expect(stalledLoops([old], NOW)).toEqual([old]);
  });

  it("treats exactly LOOP_LIVE_WINDOW_MS as still live (inclusive boundary)", () => {
    const edge = loop({ sessionId: "edge", lastUpdatedMs: NOW - LOOP_LIVE_WINDOW_MS });
    expect(liveLoops([edge], NOW)).toEqual([edge]);
    expect(stalledLoops([edge], NOW)).toEqual([]);
  });

  it("excludes complete loops from both live and stalled lists", () => {
    const doneRecent = loop({ sessionId: "done-recent", status: "complete", lastUpdatedMs: NOW - 5 * 60_000 });
    const doneOld = loop({ sessionId: "done-old", status: "complete", lastUpdatedMs: NOW - 120 * 60_000 });
    expect(liveLoops([doneRecent, doneOld], NOW)).toEqual([]);
    expect(stalledLoops([doneRecent, doneOld], NOW)).toEqual([]);
  });

  it("sorts live loops by lastUpdatedMs descending (most recent first)", () => {
    const older = loop({ sessionId: "older", lastUpdatedMs: NOW - 30 * 60_000 });
    const newer = loop({ sessionId: "newer", lastUpdatedMs: NOW - 2 * 60_000 });
    expect(liveLoops([older, newer], NOW)).toEqual([newer, older]);
  });

  it("sorts stalled loops by lastUpdatedMs descending (most recent first)", () => {
    const oldest = loop({ sessionId: "oldest", lastUpdatedMs: NOW - 300 * 60_000 });
    const lessOld = loop({ sessionId: "less-old", lastUpdatedMs: NOW - 90 * 60_000 });
    expect(stalledLoops([oldest, lessOld], NOW)).toEqual([lessOld, oldest]);
  });

  it("returns empty lists for an empty input", () => {
    expect(liveLoops([], NOW)).toEqual([]);
    expect(stalledLoops([], NOW)).toEqual([]);
  });
});

describe("runResultLabel", () => {
  const base = { runId: "r", button: "b", argv: [], cwd: "/", profile: "standard" as const, startedAt: 0, outputPath: "/tmp/x" };
  it("PASS on exit code 0", () => {
    expect(runResultLabel({ ...base, exitCode: 0 })).toBe("PASS");
  });
  it("FAIL on nonzero exit code", () => {
    expect(runResultLabel({ ...base, exitCode: 1 })).toBe("FAIL");
  });
  it("RUNNING when exitCode is absent", () => {
    expect(runResultLabel({ ...base })).toBe("RUNNING");
  });
});
