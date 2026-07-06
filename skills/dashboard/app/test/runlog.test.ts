import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, readFileSync, rmSync, existsSync, appendFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { appendRun, readRuns, mintToken, type RunRecord } from "../src/lib/runlog";

const tmpDirs: string[] = [];

function tmpRunsDir(): string {
  const dir = mkdtempSync(join(tmpdir(), "dashboard-runlog-test-"));
  tmpDirs.push(dir);
  return dir;
}

afterEach(() => {
  for (const dir of tmpDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

function record(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    runId: "run-1",
    button: "wiki-lint",
    argv: ["-p", "/coderails:wiki-lint"],
    cwd: "/Users/harrison/Github/coderails",
    profile: "standard",
    startedAt: 1000,
    outputPath: "/tmp/run-1.log",
    ...overrides,
  };
}

describe("appendRun / readRuns", () => {
  it("appends a RunRecord as one JSONL line under the given runs dir", () => {
    const dir = tmpRunsDir();
    appendRun(record(), { runsDir: dir });
    const path = join(dir, "runs.jsonl");
    expect(existsSync(path)).toBe(true);
    const lines = readFileSync(path, "utf-8").trim().split("\n");
    expect(lines.length).toBe(1);
    expect(JSON.parse(lines[0])).toMatchObject({ runId: "run-1", button: "wiki-lint" });
  });

  it("appends a second record on a new line without clobbering the first", () => {
    const dir = tmpRunsDir();
    appendRun(record({ runId: "run-1" }), { runsDir: dir });
    appendRun(record({ runId: "run-2" }), { runsDir: dir });
    const path = join(dir, "runs.jsonl");
    const lines = readFileSync(path, "utf-8").trim().split("\n");
    expect(lines.length).toBe(2);
  });

  it("creates the runs dir if it does not exist yet", () => {
    const dir = join(tmpRunsDir(), "nested", "runs");
    appendRun(record(), { runsDir: dir });
    expect(existsSync(join(dir, "runs.jsonl"))).toBe(true);
  });

  it("readRuns returns records newest-first", () => {
    const dir = tmpRunsDir();
    appendRun(record({ runId: "run-1", startedAt: 1000 }), { runsDir: dir });
    appendRun(record({ runId: "run-2", startedAt: 2000 }), { runsDir: dir });
    appendRun(record({ runId: "run-3", startedAt: 3000 }), { runsDir: dir });
    const runs = readRuns(10, { runsDir: dir });
    expect(runs.map((r) => r.runId)).toEqual(["run-3", "run-2", "run-1"]);
  });

  it("readRuns truncates to the given limit", () => {
    const dir = tmpRunsDir();
    appendRun(record({ runId: "run-1" }), { runsDir: dir });
    appendRun(record({ runId: "run-2" }), { runsDir: dir });
    appendRun(record({ runId: "run-3" }), { runsDir: dir });
    const runs = readRuns(2, { runsDir: dir });
    expect(runs.length).toBe(2);
  });

  it("readRuns returns an empty array when the runs file does not exist, without throwing", () => {
    const dir = tmpRunsDir();
    expect(() => readRuns(10, { runsDir: dir })).not.toThrow();
    expect(readRuns(10, { runsDir: dir })).toEqual([]);
  });

  it("readRuns skips a malformed JSON line rather than throwing", () => {
    const dir = tmpRunsDir();
    appendRun(record({ runId: "run-1" }), { runsDir: dir });
    const path = join(dir, "runs.jsonl");
    const { appendFileSync } = require("node:fs") as typeof import("node:fs");
    appendFileSync(path, "not valid json\n");
    appendRun(record({ runId: "run-2" }), { runsDir: dir });
    const runs = readRuns(10, { runsDir: dir });
    expect(runs.map((r) => r.runId).sort()).toEqual(["run-1", "run-2"]);
  });

  it("round-trips endedAt and exitCode written on finish", () => {
    const dir = tmpRunsDir();
    appendRun(record({ runId: "run-1", startedAt: 1000 }), { runsDir: dir });
    appendRun(record({ runId: "run-1", startedAt: 1000, endedAt: 1500, exitCode: 0 }), {
      runsDir: dir,
    });
    const runs = readRuns(10, { runsDir: dir });
    const finished = runs.find((r) => r.endedAt !== undefined);
    expect(finished?.exitCode).toBe(0);
    expect(finished?.endedAt).toBe(1500);
  });
});

describe("mintToken", () => {
  it("returns a non-empty string", () => {
    const token = mintToken();
    expect(typeof token).toBe("string");
    expect(token.length).toBeGreaterThan(0);
  });

  it("returns a different token on each call", () => {
    const a = mintToken();
    const b = mintToken();
    expect(a).not.toBe(b);
  });
});
