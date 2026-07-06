import { describe, it, expect } from "vitest";
import { accentAt, hslToRgb, expectedDurationMs, progressFraction, ACCENT_IDLE } from "../src/lib/runHue";
import type { RunRecord } from "../src/lib/runlog";

describe("accentAt", () => {
  it("returns the idle rose at fraction 0", () => {
    expect(accentAt(0)).toEqual(ACCENT_IDLE);
  });

  it("returns the violet midpoint at fraction 0.5", () => {
    const mid = accentAt(0.5);
    expect(mid.h).toBeCloseTo(290);
    expect(mid.s).toBeCloseTo(55);
    expect(mid.l).toBeCloseTo(74);
  });

  it("returns the green endpoint at fraction 1", () => {
    const end = accentAt(1);
    expect(end.h).toBeCloseTo(140);
    expect(end.s).toBeCloseTo(45);
    expect(end.l).toBeCloseTo(68);
  });

  it("clamps fractions outside [0, 1]", () => {
    expect(accentAt(-1)).toEqual(accentAt(0));
    expect(accentAt(2)).toEqual(accentAt(1));
  });

  it("interpolates monotonically toward violet in the first segment", () => {
    const quarter = accentAt(0.25);
    expect(quarter.h).toBeGreaterThan(ACCENT_IDLE.h === 350 ? 289 : 0); // sanity: some movement occurred
    expect(quarter.h).toBeLessThan(350);
  });
});

describe("hslToRgb", () => {
  it("converts the idle rose to its known RGB (close to NetworkSphere.tsx's ROSE_HEX 0xd9909a)", () => {
    expect(hslToRgb(350, 45, 72)).toEqual({ r: 216, g: 151, b: 162 });
  });

  it("converts pure green (h=120)", () => {
    const rgb = hslToRgb(120, 100, 50);
    expect(rgb).toEqual({ r: 0, g: 255, b: 0 });
  });

  it("converts white (l=100 regardless of h/s)", () => {
    expect(hslToRgb(0, 0, 100)).toEqual({ r: 255, g: 255, b: 255 });
  });
});

function run(overrides: Partial<RunRecord>): RunRecord {
  return { runId: "r", button: "wiki-lint", argv: [], cwd: "/", profile: "read-only", startedAt: 0, outputPath: "/tmp/x", ...overrides };
}

describe("expectedDurationMs", () => {
  it("falls back to 30s when there is no completed history for the button", () => {
    expect(expectedDurationMs([], "wiki-lint")).toBe(30_000);
  });

  it("ignores runs still in flight (no endedAt)", () => {
    const runs = [run({ startedAt: 0 })]; // no endedAt
    expect(expectedDurationMs(runs, "wiki-lint")).toBe(30_000);
  });

  it("ignores runs for a different button", () => {
    const runs = [run({ button: "sync-docs", startedAt: 0, endedAt: 5_000 })];
    expect(expectedDurationMs(runs, "wiki-lint")).toBe(30_000);
  });

  it("takes the median of an odd number of durations", () => {
    const runs = [
      run({ startedAt: 0, endedAt: 10_000 }),
      run({ startedAt: 0, endedAt: 20_000 }),
      run({ startedAt: 0, endedAt: 30_000 }),
    ];
    expect(expectedDurationMs(runs, "wiki-lint")).toBe(20_000);
  });

  it("averages the middle two for an even number of durations", () => {
    const runs = [
      run({ startedAt: 0, endedAt: 10_000 }),
      run({ startedAt: 0, endedAt: 20_000 }),
    ];
    expect(expectedDurationMs(runs, "wiki-lint")).toBe(15_000);
  });

  it("only samples the last 5 (readRuns is newest-first)", () => {
    const durations = [1_000, 2_000, 3_000, 4_000, 5_000, 100_000]; // last one would skew the median if included
    const runs = durations.map((d) => run({ startedAt: 0, endedAt: d }));
    expect(expectedDurationMs(runs, "wiki-lint")).toBe(3_000);
  });
});

describe("progressFraction", () => {
  it("is 0 at zero elapsed", () => {
    expect(progressFraction(0, 30_000)).toBe(0);
  });

  it("is 0.5 at half the expected duration", () => {
    expect(progressFraction(15_000, 30_000)).toBe(0.5);
  });

  it("clamps to 1 once elapsed exceeds expected", () => {
    expect(progressFraction(60_000, 30_000)).toBe(1);
  });

  it("treats a non-positive expected duration as already complete", () => {
    expect(progressFraction(1_000, 0)).toBe(1);
  });
});
