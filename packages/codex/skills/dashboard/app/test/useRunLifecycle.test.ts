import { describe, it, expect } from "vitest";
import { deriveActiveRuns, furthestProgressFraction } from "../src/hooks/useRunLifecycle";
import type { RunRecord } from "../src/lib/runlog";

function run(overrides: Partial<RunRecord>): RunRecord {
  return { runId: "r", button: "wiki-lint", argv: [], cwd: "/", profile: "read-only", startedAt: 0, outputPath: "/tmp/x", ...overrides };
}

describe("deriveActiveRuns", () => {
  it("returns an empty list when every run has finished", () => {
    const runs = [run({ runId: "a", endedAt: 1000 })];
    expect(deriveActiveRuns(runs)).toEqual([]);
  });

  it("includes a run with no endedAt as active", () => {
    const runs = [run({ runId: "a", startedAt: 500 })];
    const active = deriveActiveRuns(runs);
    expect(active).toHaveLength(1);
    expect(active[0].runId).toBe("a");
    expect(active[0].startedAt).toBe(500);
  });

  it("computes expectedMs per-button from that button's completed history", () => {
    const runs = [
      run({ runId: "done1", button: "wiki-lint", startedAt: 0, endedAt: 10_000 }),
      run({ runId: "live", button: "wiki-lint", startedAt: 5000 }), // still running
    ];
    const active = deriveActiveRuns(runs);
    expect(active[0].expectedMs).toBe(10_000);
  });

  it("supports multiple concurrent active runs across different buttons", () => {
    const runs = [run({ runId: "a", button: "wiki-lint" }), run({ runId: "b", button: "sync-docs" })];
    const active = deriveActiveRuns(runs);
    expect(active.map((a) => a.runId).sort()).toEqual(["a", "b"]);
  });
});

describe("furthestProgressFraction", () => {
  it("is 0 with no active runs", () => {
    expect(furthestProgressFraction([], 1000)).toBe(0);
  });

  it("takes the MAX fraction across concurrent runs, not the average", () => {
    const active = [
      { runId: "slow", button: "a", startedAt: 0, expectedMs: 100_000 }, // 10% at t=10000
      { runId: "fast", button: "b", startedAt: 9_000, expectedMs: 1_000 }, // 100% at t=10000
    ];
    expect(furthestProgressFraction(active, 10_000)).toBe(1);
  });

  it("clamps an overrunning run's contribution to 1", () => {
    const active = [{ runId: "over", button: "a", startedAt: 0, expectedMs: 1_000 }];
    expect(furthestProgressFraction(active, 999_000)).toBe(1);
  });
});
