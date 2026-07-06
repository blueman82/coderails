import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, utimesSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { collectMemoryTrail } from "../src/lib/collect/memoryTrail";

const tmpDirs: string[] = [];

function makeTmpDir(name: string): string {
  const dir = mkdtempSync(join(tmpdir(), `dashboard-trail-${name}-`));
  tmpDirs.push(dir);
  return dir;
}

// Creates <dir>/<name> with its mtime set to `now - ageMs`.
function writeFileWithAge(dir: string, name: string, ageMs: number, now: number): string {
  const path = join(dir, name);
  writeFileSync(path, "content");
  const mtime = new Date(now - ageMs);
  utimesSync(path, mtime, mtime);
  return path;
}

afterEach(() => {
  for (const dir of tmpDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("collectMemoryTrail", () => {
  const NOW = Date.parse("2026-07-06T12:00:00Z");

  it("lists files from a single dir newest-first", () => {
    const dir = makeTmpDir("single");
    const older = writeFileWithAge(dir, "older.md", 60_000, NOW);
    const newer = writeFileWithAge(dir, "newer.md", 0, NOW);
    const entries = collectMemoryTrail([dir], 10);
    expect(entries.map((e) => e.path)).toEqual([newer, older]);
  });

  it("merges multiple dirs, sorted newest-first across all of them", () => {
    const dirA = makeTmpDir("a");
    const dirB = makeTmpDir("b");
    const oldest = writeFileWithAge(dirA, "oldest.md", 120_000, NOW);
    const middle = writeFileWithAge(dirB, "middle.md", 60_000, NOW);
    const newest = writeFileWithAge(dirA, "newest.md", 0, NOW);
    const entries = collectMemoryTrail([dirA, dirB], 10);
    expect(entries.map((e) => e.path)).toEqual([newest, middle, oldest]);
  });

  it("respects the limit after merging and sorting", () => {
    const dir = makeTmpDir("limit");
    writeFileWithAge(dir, "a.md", 30_000, NOW);
    writeFileWithAge(dir, "b.md", 20_000, NOW);
    const newest = writeFileWithAge(dir, "c.md", 10_000, NOW);
    const entries = collectMemoryTrail([dir], 2);
    expect(entries).toHaveLength(2);
    expect(entries[0].path).toBe(newest);
  });

  it("contributes nothing for a nonexistent dir, and does not throw", () => {
    const missing = join(tmpdir(), "does-not-exist-memory-trail-dir");
    expect(() => collectMemoryTrail([missing], 10)).not.toThrow();
    expect(collectMemoryTrail([missing], 10)).toEqual([]);
  });

  it("mixes a nonexistent dir with a real one without throwing, contributing only the real files", () => {
    const dir = makeTmpDir("mixed");
    const real = writeFileWithAge(dir, "real.md", 0, NOW);
    const missing = join(tmpdir(), "does-not-exist-memory-trail-dir-2");
    const entries = collectMemoryTrail([missing, dir], 10);
    expect(entries.map((e) => e.path)).toEqual([real]);
  });

  it("sets mtime to the file's actual mtime in ms", () => {
    const dir = makeTmpDir("mtime");
    writeFileWithAge(dir, "f.md", 5_000, NOW);
    const entries = collectMemoryTrail([dir], 10);
    expect(entries[0].mtime).toBe(NOW - 5_000);
  });

  it("derives displayPath from the last two path segments", () => {
    const dir = makeTmpDir("display");
    const path = writeFileWithAge(dir, "note.md", 0, NOW);
    const entries = collectMemoryTrail([dir], 10);
    const parts = path.split("/");
    const expected = parts.slice(-2).join("/");
    expect(entries[0].displayPath).toBe(expected);
  });

  it("does not descend into subdirectories (flat listing of each dir)", () => {
    const dir = makeTmpDir("flat");
    mkdirSync(join(dir, "nested"));
    writeFileWithAge(join(dir, "nested"), "inner.md", 0, NOW);
    const top = writeFileWithAge(dir, "top.md", 0, NOW);
    const entries = collectMemoryTrail([dir], 10);
    expect(entries.map((e) => e.path)).toEqual([top]);
  });

  it("returns an empty array when given an empty dirs list", () => {
    expect(collectMemoryTrail([], 10)).toEqual([]);
  });
});
