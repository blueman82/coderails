import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, readFileSync, rmSync, existsSync, appendFileSync, mkdirSync, writeFileSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { appendRun, readRuns, mintToken, getRunToken, type RunRecord } from "../src/lib/runlog";

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

describe("getRunToken", () => {
  // getRunToken is file-backed (not a plain module-scope variable) because Next.js's app router
  // compiles Route Handlers and Server Components as separate module graphs/bundler layers — a
  // shared in-memory singleton ends up as two independently-initialized copies, one per layer
  // (confirmed empirically: the token embedded in the rendered page never matched what POST
  // /api/run compared against). These tests exercise the file-backed behaviour directly, each
  // with its own tmp dir so getRunToken's internal cachedToken (scoped to THIS test's module
  // instance) doesn't leak a token minted by an earlier test into a later one's fresh directory —
  // every call here passes an explicit `dir` distinct across it and its dependents, so the
  // in-process cache never masks a real cross-directory read.
  it("mints and persists a token to <dir>/run-token on first call", () => {
    const dir = tmpRunsDir();
    const token = getRunToken(dir);
    expect(typeof token).toBe("string");
    expect(token.length).toBeGreaterThan(0);
    expect(readFileSync(join(dir, "run-token"), "utf-8").trim()).toBe(token);
  });

  it("returns the token already on disk rather than minting a new one", () => {
    const dir = tmpRunsDir();
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "run-token"), "existing-token-value");
    expect(getRunToken(dir)).toBe("existing-token-value");
  });

  it("creates the token dir if it does not exist yet", () => {
    const dir = join(tmpRunsDir(), "nested", "token-dir");
    const token = getRunToken(dir);
    expect(existsSync(join(dir, "run-token"))).toBe(true);
    expect(readFileSync(join(dir, "run-token"), "utf-8").trim()).toBe(token);
  });

  it("creates the token file mode 0600 — not world/group readable (it's a credential)", () => {
    const dir = tmpRunsDir();
    getRunToken(dir);
    const mode = statSync(join(dir, "run-token")).mode & 0o777;
    expect(mode).toBe(0o600);
  });

  it("tightens an existing token file's mode to 0600 on read, if it was created looser", () => {
    const dir = tmpRunsDir();
    mkdirSync(dir, { recursive: true });
    const path = join(dir, "run-token");
    writeFileSync(path, "existing-token-value", { mode: 0o644 });
    expect(statSync(path).mode & 0o777).toBe(0o644);

    getRunToken(dir);

    expect(statSync(path).mode & 0o777).toBe(0o600);
  });
});
