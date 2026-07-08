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

  it("returns null (not a wrong guess) when no scripts/run-builder.sh sibling can be found from the given start directory or cwd", () => {
    const isolatedDir = tmpDir("dashboard-resolve-wrapper-isolated-");
    const isolatedCwd = tmpDir("dashboard-resolve-wrapper-isolated-cwd-");
    // An isolated tmp dir has no ancestor containing scripts/run-builder.sh
    // within the search bound (for either the startDir walk or the cwd
    // fallback walk), so this must fail closed rather than fabricate a
    // nonexistent path.
    const originalCwd = process.cwd();
    try {
      process.chdir(isolatedCwd);
      const resolved = resolveDefaultWrapperPath(isolatedDir);
      expect(resolved).toBeNull();
    } finally {
      process.chdir(originalCwd);
    }
  });

  it("finds scripts/run-builder.sh by walking up from a nested start directory that has it as a sibling further up", () => {
    const fakeRepoRoot = tmpDir("dashboard-resolve-wrapper-fakeroot-");
    mkdirSync(join(fakeRepoRoot, "scripts"), { recursive: true });
    writeFileSync(
      join(fakeRepoRoot, "scripts", "run-builder.sh"),
      "#!/bin/bash\n# Owns the build lifecycle state machine for one approved\n"
    );
    const nestedStart = join(fakeRepoRoot, "app", "src", "lib", "build");
    mkdirSync(nestedStart, { recursive: true });

    const resolved = resolveDefaultWrapperPath(nestedStart);
    expect(resolved).toBe(join(fakeRepoRoot, "scripts", "run-builder.sh"));
  });

  it("rejects a scripts/run-builder.sh that exists but lacks the identity marker, continuing the walk-up rather than accepting a false-positive match (silent-failure-hunter finding: monorepo/nested-checkout collision)", () => {
    const outerRoot = tmpDir("dashboard-resolve-wrapper-outer-");
    // An unrelated file that happens to share the exact relative path
    // scripts/run-builder.sh but is NOT this repo's wrapper — e.g. a
    // nested checkout or monorepo sibling project with its own script of
    // the same name.
    mkdirSync(join(outerRoot, "unrelated-project", "scripts"), { recursive: true });
    writeFileSync(
      join(outerRoot, "unrelated-project", "scripts", "run-builder.sh"),
      "#!/bin/bash\necho 'this is an unrelated script, not the coderails builder wrapper'\n"
    );
    const nestedStart = join(outerRoot, "unrelated-project", "app", "src");
    mkdirSync(nestedStart, { recursive: true });
    const isolatedCwd = tmpDir("dashboard-resolve-wrapper-outer-cwd-");

    const originalCwd = process.cwd();
    try {
      process.chdir(isolatedCwd);
      const resolved = resolveDefaultWrapperPath(nestedStart);
      expect(resolved).toBeNull();
    } finally {
      process.chdir(originalCwd);
    }
  });

  // Production regression (L2-WU7, DEFECT A): under `next start`, the
  // bundler virtualises __dirname into a chunk path like
  // "[root-of-the-server]__foo.js" that doesn't exist on disk, so the
  // __dirname-anchored walk-up above finds nothing even though the real
  // scripts/run-builder.sh is right there on the deployed filesystem.
  // These tests exercise the fallback chain that makes resolution
  // production-safe: env override first, then the __dirname walk (already
  // covered above), then a process.cwd()-anchored walk as a last resort —
  // each candidate still gated by the same content-identity check, so a
  // lookalike script is rejected rather than silently accepted.
  describe("fallback chain (env override, then cwd-anchored walk)", () => {
    const ENV_VAR = "CODERAILS_BUILDER_WRAPPER";
    const originalEnvValue = process.env[ENV_VAR];

    afterEach(() => {
      if (originalEnvValue === undefined) {
        delete process.env[ENV_VAR];
      } else {
        process.env[ENV_VAR] = originalEnvValue;
      }
    });

    it("prefers CODERAILS_BUILDER_WRAPPER env override when it points at a file passing the identity check", () => {
      const envDir = tmpDir("dashboard-resolve-wrapper-env-");
      const envWrapper = join(envDir, "run-builder.sh");
      writeFileSync(
        envWrapper,
        "#!/bin/bash\n# Owns the build lifecycle state machine for one approved\n"
      );
      process.env[ENV_VAR] = envWrapper;

      // Even though a real, valid sibling wrapper is discoverable via the
      // __dirname walk (default startDir), the env override must win.
      const resolved = resolveDefaultWrapperPath();
      expect(resolved).toBe(envWrapper);
    });

    it("rejects a CODERAILS_BUILDER_WRAPPER override that fails the identity check, falling through to the next tier rather than trusting it blindly", () => {
      const envDir = tmpDir("dashboard-resolve-wrapper-env-bad-");
      const badWrapper = join(envDir, "run-builder.sh");
      writeFileSync(badWrapper, "#!/bin/bash\necho 'not the real wrapper'\n");
      process.env[ENV_VAR] = badWrapper;

      // No valid sibling exists from an isolated start dir OR an isolated
      // cwd, so the whole chain should fail closed (null), proving the bad
      // env value was rejected rather than accepted.
      const isolatedDir = tmpDir("dashboard-resolve-wrapper-env-bad-isolated-");
      const isolatedCwd = tmpDir("dashboard-resolve-wrapper-env-bad-cwd-");
      const originalCwd = process.cwd();
      try {
        process.chdir(isolatedCwd);
        const resolved = resolveDefaultWrapperPath(isolatedDir);
        expect(resolved).toBeNull();
      } finally {
        process.chdir(originalCwd);
      }
    });

    it("rejects a CODERAILS_BUILDER_WRAPPER override pointing at a nonexistent file, falling through", () => {
      process.env[ENV_VAR] = join(tmpdir(), "does-not-exist-run-builder.sh");
      const isolatedDir = tmpDir("dashboard-resolve-wrapper-env-missing-isolated-");
      const isolatedCwd = tmpDir("dashboard-resolve-wrapper-env-missing-cwd-");
      const originalCwd = process.cwd();
      try {
        process.chdir(isolatedCwd);
        const resolved = resolveDefaultWrapperPath(isolatedDir);
        expect(resolved).toBeNull();
      } finally {
        process.chdir(originalCwd);
      }
    });

    it("falls through to a process.cwd()-anchored walk when the __dirname-anchored walk finds nothing (simulated virtual __dirname, e.g. a bundler chunk path)", () => {
      delete process.env[ENV_VAR];
      const fakeRepoRoot = tmpDir("dashboard-resolve-wrapper-cwd-fallback-");
      mkdirSync(join(fakeRepoRoot, "scripts"), { recursive: true });
      writeFileSync(
        join(fakeRepoRoot, "scripts", "run-builder.sh"),
        "#!/bin/bash\n# Owns the build lifecycle state machine for one approved\n"
      );
      // A start dir that does NOT exist on disk at all — the closest
      // realistic stand-in for a bundler-virtualised __dirname value like
      // "[root-of-the-server]__foo.js", which also resolves to a path with
      // no real ancestors containing scripts/run-builder.sh.
      const virtualStartDir = join(fakeRepoRoot, "__virtual__", "chunk", "does", "not", "exist");

      const originalCwd = process.cwd();
      try {
        process.chdir(fakeRepoRoot);
        const resolved = resolveDefaultWrapperPath(virtualStartDir);
        expect(resolved).toBe(join(fakeRepoRoot, "scripts", "run-builder.sh"));
      } finally {
        process.chdir(originalCwd);
      }
    });

    it("still returns null when neither env, __dirname walk, nor cwd walk finds a valid wrapper", () => {
      delete process.env[ENV_VAR];
      const isolatedCwd = tmpDir("dashboard-resolve-wrapper-all-fail-cwd-");
      const isolatedStart = tmpDir("dashboard-resolve-wrapper-all-fail-start-");
      const originalCwd = process.cwd();
      try {
        process.chdir(isolatedCwd);
        const resolved = resolveDefaultWrapperPath(isolatedStart);
        expect(resolved).toBeNull();
      } finally {
        process.chdir(originalCwd);
      }
    });
  });
});
