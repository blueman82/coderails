import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, rmSync, existsSync, readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  claimAndSpawnBuild,
  resolveDefaultWrapperPath,
  type SpawnFn,
} from "../src/lib/build/spawn";
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
    // Full shape required by src/lib/build/prompt.ts's buildPrompt, which
    // claimAndSpawnBuild now calls for real (Task 6 wired the real import in,
    // replacing the earlier placeholder prompt.md string this task shipped).
    toolInput: {
      cluster_ngram: ["marker-a", "marker-b"],
      count: 3,
      sessions: ["session-1"],
      task_summary: "a summary",
      proposed_name: "my-new-skill",
      proposed_description: "a description",
    },
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

describe("resolveDefaultWrapperPath", () => {
  // route.ts previously resolved the wrapper path via
  // join(process.cwd(), "..", "scripts", "run-builder.sh") — cwd-relative,
  // which breaks under a production Next.js server whose cwd is not
  // guaranteed to be the app root (the exact class of bug the
  // prod-prerender war story documents in project memory). This walks
  // upward from the module's own location (not cwd) looking for the known
  // sibling scripts/run-builder.sh, so it's stable regardless of the
  // server process's working directory.
  it("resolves an absolute path that exists on disk, independent of process.cwd()", () => {
    const originalCwd = process.cwd();
    try {
      process.chdir(tmpdir());
      const resolved = resolveDefaultWrapperPath();
      expect(resolved).not.toBeNull();
      if (resolved) {
        expect(existsSync(resolved)).toBe(true);
        expect(resolved.endsWith("run-builder.sh")).toBe(true);
      }
    } finally {
      process.chdir(originalCwd);
    }
  });

  it("returns null (not a wrong guess) when no scripts/run-builder.sh sibling can be found from the given start directory", () => {
    const isolatedDir = tmpDir("dashboard-resolve-wrapper-isolated-");
    // An isolated tmp dir has no ancestor containing scripts/run-builder.sh
    // within the search bound, so this must fail closed rather than
    // fabricate a nonexistent path.
    const resolved = resolveDefaultWrapperPath(isolatedDir);
    expect(resolved).toBeNull();
  });

  it("finds scripts/run-builder.sh by walking up from a nested start directory that has it as a sibling further up", () => {
    const fakeRepoRoot = tmpDir("dashboard-resolve-wrapper-fakeroot-");
    mkdirSync(join(fakeRepoRoot, "scripts"), { recursive: true });
    writeFileSync(join(fakeRepoRoot, "scripts", "run-builder.sh"), "#!/bin/bash\n");
    const nestedStart = join(fakeRepoRoot, "app", "src", "lib", "build");
    mkdirSync(nestedStart, { recursive: true });

    const resolved = resolveDefaultWrapperPath(nestedStart);
    expect(resolved).toBe(join(fakeRepoRoot, "scripts", "run-builder.sh"));
  });
});
