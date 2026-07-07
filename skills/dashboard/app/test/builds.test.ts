import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { collectBuilds } from "../src/lib/collect/builds";

const tmpDirs: string[] = [];

function makeTmpDir(name: string): string {
  const dir = mkdtempSync(join(tmpdir(), `dashboard-builds-${name}-`));
  tmpDirs.push(dir);
  return dir;
}

function writeBuild(buildsDir: string, hash: string, overrides: Record<string, unknown> = {}): string {
  const dir = join(buildsDir, hash);
  mkdirSync(dir, { recursive: true });
  const state = { schemaVersion: 1, hash, state: "running", ...overrides };
  writeFileSync(join(dir, "state.json"), JSON.stringify(state));
  return dir;
}

afterEach(() => {
  for (const dir of tmpDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("collectBuilds", () => {
  it("parses a builds dir of <hash>/state.json files into BuildEntry[]", () => {
    const dir = makeTmpDir("basic");
    const hash = "a".repeat(64);
    writeBuild(dir, hash, { state: "running" });
    const entries = collectBuilds(dir);
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({ schemaVersion: 1, hash, state: "running" });
  });

  it("contributes nothing for a nonexistent dir, and does not throw", () => {
    const missing = join(tmpdir(), "does-not-exist-builds-dir");
    expect(() => collectBuilds(missing)).not.toThrow();
    expect(collectBuilds(missing)).toEqual([]);
  });

  it("rejects an unrecognized state rather than defaulting", () => {
    const dir = makeTmpDir("bogus-state");
    writeBuild(dir, "b".repeat(64), { state: "bogus" });
    expect(collectBuilds(dir)).toEqual([]);
  });

  it("rejects a state.json with the state field absent entirely, not just an unrecognized value", () => {
    const dir = makeTmpDir("missing-state");
    writeBuild(dir, "9".repeat(64), { state: undefined });
    expect(collectBuilds(dir)).toEqual([]);
  });

  it("skips a malformed state.json rather than throwing, alongside a sibling well-formed entry", () => {
    const dir = makeTmpDir("malformed");
    const badDir = join(dir, "c".repeat(64));
    mkdirSync(badDir, { recursive: true });
    writeFileSync(join(badDir, "state.json"), "{ not valid json");
    const goodHash = "d".repeat(64);
    writeBuild(dir, goodHash, { state: "claimed" });

    expect(() => collectBuilds(dir)).not.toThrow();
    const entries = collectBuilds(dir);
    expect(entries).toHaveLength(1);
    expect(entries[0].hash).toBe(goodHash);
  });

  it("includes heartbeatAt (the heartbeat file's mtime) when a heartbeat file exists", () => {
    const dir = makeTmpDir("heartbeat");
    const hash = "e".repeat(64);
    const buildDir = writeBuild(dir, hash, { state: "running" });
    const before = Date.now();
    writeFileSync(join(buildDir, "heartbeat"), "");
    const after = Date.now();

    const entries = collectBuilds(dir);
    expect(entries).toHaveLength(1);
    expect(entries[0].heartbeatAt).toBeGreaterThanOrEqual(before - 1000);
    expect(entries[0].heartbeatAt).toBeLessThanOrEqual(after + 1000);
  });

  it("omits heartbeatAt when no heartbeat file exists (state: claimed, pre-running)", () => {
    const dir = makeTmpDir("no-heartbeat");
    writeBuild(dir, "f".repeat(64), { state: "claimed" });

    const entries = collectBuilds(dir);
    expect(entries).toHaveLength(1);
    expect(entries[0].heartbeatAt).toBeUndefined();
  });

  it("carries prUrl and failureReason through when present", () => {
    const dir = makeTmpDir("carry-fields");
    const prHash = "1".repeat(64);
    writeBuild(dir, prHash, { state: "pr_open", prUrl: "https://github.com/blueman82/coderails/pull/999" });
    const failHash = "2".repeat(64);
    writeBuild(dir, failHash, { state: "failed", failureReason: "hash_mismatch:abc" });

    const entries = collectBuilds(dir);
    const pr = entries.find((e) => e.hash === prHash);
    const failed = entries.find((e) => e.hash === failHash);
    expect(pr?.prUrl).toBe("https://github.com/blueman82/coderails/pull/999");
    expect(failed?.failureReason).toBe("hash_mismatch:abc");
  });
});
