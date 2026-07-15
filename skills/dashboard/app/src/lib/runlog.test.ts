import { describe, it, expect } from "vitest";
import type { RunRecord } from "./runlog";
import { reconcileOrphanRuns } from "./runlog";

// Reconciler test fixtures below use `startedAt`/`bootTime` as small relative
// integers rather than real timestamps — the pure core only ever compares
// them numerically, so this keeps the matrix readable without epoch-ms noise.
function run(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    runId: "r1",
    button: "some-button",
    argv: [],
    cwd: "/tmp",
    profile: "default",
    startedAt: 100,
    outputPath: "/tmp/out.log",
    ...overrides,
  };
}

describe("reconcileOrphanRuns", () => {
  it("emits a synthetic finish for an orphan (started before boot, never finished)", () => {
    const records = [run({ runId: "orphan", startedAt: 100 })];
    const bootTime = 200;

    const finishes = reconcileOrphanRuns(records, bootTime);

    expect(finishes).toHaveLength(1);
    expect(finishes[0]).toMatchObject({
      runId: "orphan",
      startedAt: 100,
      exitCode: -1,
      reconciled: true,
    });
    expect(finishes[0].endedAt).toBeTypeOf("number");
  });

  it("spares an in-flight run started by this process (startedAt >= bootTime)", () => {
    const records = [run({ runId: "in-flight", startedAt: 250 })];
    const bootTime = 200;

    const finishes = reconcileOrphanRuns(records, bootTime);

    expect(finishes).toHaveLength(0);
  });

  it("spares a run started at exactly bootTime (guard is >=, not >)", () => {
    const records = [run({ runId: "boundary", startedAt: 200 })];
    const bootTime = 200;

    const finishes = reconcileOrphanRuns(records, bootTime);

    expect(finishes).toHaveLength(0);
  });

  it("leaves an already-settled run untouched", () => {
    const records = [
      run({ runId: "settled", startedAt: 100, endedAt: 150, exitCode: 0 }),
    ];
    const bootTime = 200;

    const finishes = reconcileOrphanRuns(records, bootTime);

    expect(finishes).toHaveLength(0);
  });

  it("reconciles an orphan even when it sits behind 20+ more-recent runs (full-ledger fold, not readRuns(20))", () => {
    const recentSettled = Array.from({ length: 25 }, (_, i) =>
      run({
        runId: `recent-${i}`,
        startedAt: 1000 + i,
        endedAt: 1000 + i + 10,
        exitCode: 0,
      }),
    );
    const oldOrphan = run({ runId: "old-orphan", startedAt: 50 });
    const records = [oldOrphan, ...recentSettled];
    const bootTime = 200;

    const finishes = reconcileOrphanRuns(records, bootTime);

    expect(finishes).toHaveLength(1);
    expect(finishes[0].runId).toBe("old-orphan");
  });

  it("folds a start+finish pair for the same runId (finish is newest) as settled/untouched", () => {
    const records = [
      run({ runId: "pair", startedAt: 100 }),
      run({ runId: "pair", startedAt: 100, endedAt: 120, exitCode: 0 }),
    ];
    const bootTime = 200;

    const finishes = reconcileOrphanRuns(records, bootTime);

    expect(finishes).toHaveLength(0);
  });

  it("spares a start-only line newer than boot even when many older runs precede it", () => {
    const olderSettled = Array.from({ length: 22 }, (_, i) =>
      run({
        runId: `older-${i}`,
        startedAt: i,
        endedAt: i + 5,
        exitCode: 0,
      }),
    );
    const records = [...olderSettled, run({ runId: "fresh-in-flight", startedAt: 300 })];
    const bootTime = 200;

    const finishes = reconcileOrphanRuns(records, bootTime);

    expect(finishes).toHaveLength(0);
  });
});
