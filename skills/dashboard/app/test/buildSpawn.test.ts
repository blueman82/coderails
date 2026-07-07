import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, rmSync, existsSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { claimAndSpawnBuild, type SpawnFn } from "../src/lib/build/spawn";
import type { QueueEntrySnapshot } from "../src/lib/collect/queueActions";

const tmpDirs: string[] = [];

function tmpDir(prefix: string): string {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  tmpDirs.push(dir);
  return dir;
}

afterEach(() => {
  for (const dir of tmpDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

const HASH_A = "a".repeat(64);

function makeEntry(overrides: Partial<QueueEntrySnapshot> = {}): QueueEntrySnapshot {
  return {
    hash: HASH_A,
    toolName: "workflow-audit:propose-skill",
    toolInput: { proposed_name: "my-new-skill" },
    createdAt: 1_720_000_000_000,
    status: "approved",
    ...overrides,
  };
}

function makeFakeSpawn() {
  const calls: { command: string; args: readonly string[]; options: unknown }[] = [];
  const fn: SpawnFn = (command, args, options) => {
    calls.push({ command, args, options });
    return { unref: () => {} };
  };
  return { fn, calls };
}

describe("claimAndSpawnBuild", () => {
  it("invalid proposed_name returns {claimed:false, error:'invalid_name'} and creates no directory", () => {
    const buildsDir = tmpDir("dashboard-build-spawn-invalid-");
    const entry = makeEntry({ toolInput: { proposed_name: "Has Spaces" } });
    const { fn } = makeFakeSpawn();
    const result = claimAndSpawnBuild(entry, { buildsDir, wrapperPath: "/bin/true", spawnImpl: fn });
    expect(result).toEqual({ claimed: false, error: "invalid_name" });
    expect(existsSync(join(buildsDir, entry.hash))).toBe(false);
  });

  it("valid claim creates buildDir with snapshot.json (byte-identical to entry), state.json (state:'claimed'), and prompt.md, and calls spawnImpl with [wrapperPath, buildDir] and CODERAILS_BUILDER=1 env", () => {
    const buildsDir = tmpDir("dashboard-build-spawn-valid-");
    const entry = makeEntry();
    const wrapperPath = "/path/to/run-builder.sh";
    const { fn, calls } = makeFakeSpawn();

    const result = claimAndSpawnBuild(entry, { buildsDir, wrapperPath, spawnImpl: fn });

    expect(result.claimed).toBe(true);
    const buildDir = join(buildsDir, entry.hash);
    expect(JSON.parse(readFileSync(join(buildDir, "snapshot.json"), "utf-8"))).toEqual(entry);
    const state = JSON.parse(readFileSync(join(buildDir, "state.json"), "utf-8"));
    expect(state.state).toBe("claimed");
    expect(existsSync(join(buildDir, "prompt.md"))).toBe(true);

    expect(calls).toHaveLength(1);
    expect(calls[0].command).toBe("bash");
    expect(calls[0].args).toEqual([wrapperPath, buildDir]);
    expect(calls[0].options).toMatchObject({
      detached: true,
      env: expect.objectContaining({ CODERAILS_BUILDER: "1" }),
    });
  });

  it("two concurrent claims for the same hash: first succeeds, second returns alreadyClaimed and does not call spawnImpl a second time", () => {
    const buildsDir = tmpDir("dashboard-build-spawn-race-");
    const entry = makeEntry();
    const { fn, calls } = makeFakeSpawn();

    const first = claimAndSpawnBuild(entry, { buildsDir, wrapperPath: "/bin/true", spawnImpl: fn });
    const second = claimAndSpawnBuild(entry, { buildsDir, wrapperPath: "/bin/true", spawnImpl: fn });

    expect(first.claimed).toBe(true);
    expect(second).toEqual({ claimed: false, alreadyClaimed: true });
    expect(calls).toHaveLength(1);
  });

  it("runId is the first 8 hex chars of entry.hash", () => {
    const buildsDir = tmpDir("dashboard-build-spawn-runid-");
    const entry = makeEntry();
    const { fn } = makeFakeSpawn();
    const result = claimAndSpawnBuild(entry, { buildsDir, wrapperPath: "/bin/true", spawnImpl: fn });
    expect(result.claimed).toBe(true);
    if (result.claimed) {
      expect(result.runId).toBe(entry.hash.slice(0, 8));
    }
  });
});
