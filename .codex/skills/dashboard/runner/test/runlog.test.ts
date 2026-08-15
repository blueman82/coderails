import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdtempSync, rmSync, readFileSync, appendFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { appendRun, readRuns, type RunRecord } from "../src/runlog.ts";

let dir: string;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "runlog-test-"));
});

afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

function record(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    runId: "abc123",
    button: "wiki-lint",
    argv: ["-p", "/coderails:wiki-lint"],
    cwd: "/Users/harrison/Github/coderails",
    profile: "read-only",
    startedAt: 1000,
    outputPath: "/tmp/abc123.log",
    ...overrides,
  };
}

describe("appendRun / readRuns (imported from merged app/src/lib/runlog)", () => {
  it("appends a JSONL line readable back as a RunRecord", () => {
    appendRun(record(), { runsDir: dir });
    const runs = readRuns(10, { runsDir: dir });
    expect(runs).toHaveLength(1);
    expect(runs[0]).toEqual(record());
  });

  it("creates the runs directory if it does not exist", () => {
    const nested = join(dir, "nested", "runs");
    appendRun(record(), { runsDir: nested });
    expect(readRuns(10, { runsDir: nested })).toHaveLength(1);
  });

  it("folds a run's start and finish lines into one record, keeping the finish line", () => {
    appendRun(record({ startedAt: 1000 }), { runsDir: dir });
    appendRun(record({ startedAt: 1000, endedAt: 2000, exitCode: 0 }), { runsDir: dir });
    const runs = readRuns(10, { runsDir: dir });
    expect(runs).toHaveLength(1);
    expect(runs[0].endedAt).toBe(2000);
    expect(runs[0].exitCode).toBe(0);
  });

  it("sorts newest-first by startedAt", () => {
    appendRun(record({ runId: "old", startedAt: 1000 }), { runsDir: dir });
    appendRun(record({ runId: "new", startedAt: 2000 }), { runsDir: dir });
    const runs = readRuns(10, { runsDir: dir });
    expect(runs.map((r) => r.runId)).toEqual(["new", "old"]);
  });

  it("truncates to the given limit", () => {
    appendRun(record({ runId: "a", startedAt: 1 }), { runsDir: dir });
    appendRun(record({ runId: "b", startedAt: 2 }), { runsDir: dir });
    appendRun(record({ runId: "c", startedAt: 3 }), { runsDir: dir });
    expect(readRuns(2, { runsDir: dir })).toHaveLength(2);
  });

  it("returns an empty array when the runs file does not exist", () => {
    expect(readRuns(10, { runsDir: dir })).toEqual([]);
  });

  it("skips a malformed line rather than throwing", () => {
    appendRun(record({ runId: "good" }), { runsDir: dir });
    const path = join(dir, "runs.jsonl");
    const existing = readFileSync(path, "utf-8");
    // Append one malformed line directly (bypassing appendRun's JSON.stringify).
    appendFileSync(path, "not valid json\n");
    expect(existing).toBeTruthy();
    const runs = readRuns(10, { runsDir: dir });
    expect(runs).toHaveLength(1);
    expect(runs[0].runId).toBe("good");
  });
});
