import { describe, it, expect, afterEach } from "vitest";
import {
  mkdtempSync,
  writeFileSync,
  readFileSync,
  existsSync,
  rmSync,
  chmodSync,
  mkdirSync,
} from "node:fs";
import { execFileSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHash } from "node:crypto";

const SCRIPT_PATH = join(__dirname, "..", "..", "scripts", "run-builder.sh");

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

function readState(buildDir: string): Record<string, unknown> {
  return JSON.parse(readFileSync(join(buildDir, "state.json"), "utf-8"));
}

function makeBuildDir(): string {
  const dir = tmpDir("dashboard-run-builder-");
  writeFileSync(
    join(dir, "state.json"),
    JSON.stringify({ schemaVersion: 1, hash: "unset", state: "claimed" })
  );
  return dir;
}

// Computes the same hash the wrapper computes: sha256(jq -S -c .toolInput).
function computeHash(toolInput: unknown): string {
  const canonical = JSON.stringify(sortKeysDeep(toolInput));
  return createHash("sha256").update(canonical).digest("hex");
}

// jq -S sorts object keys recursively; mirror that so our test oracle uses
// the same external tool contract the script relies on, not a private
// reimplementation of jq's canonicalization.
function sortKeysDeep(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeysDeep);
  if (value !== null && typeof value === "object") {
    const sorted: Record<string, unknown> = {};
    for (const key of Object.keys(value as Record<string, unknown>).sort()) {
      sorted[key] = sortKeysDeep((value as Record<string, unknown>)[key]);
    }
    return sorted;
  }
  return value;
}

function writeSnapshot(
  buildDir: string,
  overrides: Record<string, unknown> = {}
): { hash: string; toolInput: unknown } {
  const toolInput = overrides.toolInput ?? { proposed_name: "x" };
  const hash = (overrides.hash as string | undefined) ?? computeHash(toolInput);
  const snapshot = {
    hash,
    toolName: "workflow-audit:propose-skill",
    toolInput,
    createdAt: 1_720_000_000_000,
    status: "approved",
    ...overrides,
    // hash/toolInput above are the defaults; overrides can still replace them
    ...(overrides.hash !== undefined ? { hash: overrides.hash } : { hash }),
  };
  writeFileSync(join(buildDir, "snapshot.json"), JSON.stringify(snapshot));
  return { hash: snapshot.hash as string, toolInput: snapshot.toolInput };
}

function makeRepoFixture(): string {
  // The wrapper runs `git fetch origin` and `worktree add ... origin/main`,
  // matching real production topology (a real clone with an origin
  // remote) — so the fixture needs a bare "origin" repo, not just a lone
  // working copy with no remote.
  const bareDir = tmpDir("dashboard-run-builder-bare-");
  execFileSync("git", ["init", "-q", "--bare", bareDir]);

  const repoDir = tmpDir("dashboard-run-builder-repo-");
  execFileSync("git", ["init", "-q", repoDir]);
  execFileSync("git", ["-C", repoDir, "config", "user.email", "test@example.com"]);
  execFileSync("git", ["-C", repoDir, "config", "user.name", "Test"]);
  writeFileSync(join(repoDir, "package.json"), JSON.stringify({ name: "coderails" }));
  execFileSync("git", ["-C", repoDir, "add", "package.json"]);
  execFileSync("git", ["-C", repoDir, "commit", "-q", "-m", "init"]);
  execFileSync("git", ["-C", repoDir, "branch", "-M", "main"]);
  execFileSync("git", ["-C", repoDir, "remote", "add", "origin", bareDir]);
  execFileSync("git", ["-C", repoDir, "push", "-q", "origin", "main"]);
  return repoDir;
}

function makeStubClaudeBin(script: string): string {
  const binDir = tmpDir("dashboard-run-builder-stubbin-");
  const stubPath = join(binDir, "claude");
  writeFileSync(stubPath, `#!/bin/bash\n${script}\n`);
  chmodSync(stubPath, 0o755);
  return binDir;
}

function runWrapper(
  buildDir: string,
  env: Record<string, string> = {}
): { status: number } {
  try {
    execFileSync("bash", [SCRIPT_PATH, buildDir], {
      env: { ...process.env, ...env },
      // "ignore" (not "pipe"): the wrapper's own heartbeat/watchdog run as
      // detached background subshells that inherit stdio file descriptors.
      // With "pipe", Node's execFileSync waits for those inherited pipe FDs
      // to close (EOF), not just for this child to exit — since the
      // subshells only die from the wrapper's own kill in its EXIT trap,
      // that race can leave the pipe open well past the wrapper's real
      // completion. "ignore" avoids creating a pipe to wait on at all.
      stdio: "ignore",
    });
    return { status: 0 };
  } catch (err) {
    const e = err as { status: number | null };
    return { status: e.status ?? 1 };
  }
}

describe("run-builder.sh: hash re-validation (steps 1-2)", () => {
  it("missing snapshot.json -> failed: unparseable_entry:snapshot.json", () => {
    const buildDir = makeBuildDir();
    const locksDir = tmpDir("dashboard-run-builder-locks-");

    runWrapper(buildDir, { CODERAILS_BUILDER_LOCKS_DIR: locksDir });

    const state = readState(buildDir);
    expect(state.state).toBe("failed");
    expect(state.failureReason).toBe("unparseable_entry:snapshot.json");
  });

  it("hash mismatch -> failed: hash_mismatch:<hash>, and the stub claude on PATH is never invoked", () => {
    const buildDir = makeBuildDir();
    const locksDir = tmpDir("dashboard-run-builder-locks-");
    const stubLog = join(buildDir, "stub-invocations.log");
    const binDir = makeStubClaudeBin(`echo "$@" >> "${stubLog}"; exit 0`);

    const wrongHash = "a".repeat(64);
    writeSnapshot(buildDir, { hash: wrongHash, toolInput: { proposed_name: "x" } });

    runWrapper(buildDir, {
      CODERAILS_BUILDER_LOCKS_DIR: locksDir,
      PATH: `${binDir}:${process.env.PATH}`,
    });

    const state = readState(buildDir);
    expect(state.state).toBe("failed");
    expect(state.failureReason).toBe(`hash_mismatch:${wrongHash}`);
    expect(existsSync(stubLog)).toBe(false);
  });

  it("matching hash passes re-validation and does not fail with a hash_mismatch reason", () => {
    const buildDir = makeBuildDir();
    const locksDir = tmpDir("dashboard-run-builder-locks-");
    const repoDir = makeRepoFixture();
    const binDir = makeStubClaudeBin(`exit 0`);

    writeSnapshot(buildDir, { toolInput: { proposed_name: "x" } });

    runWrapper(buildDir, {
      CODERAILS_BUILDER_LOCKS_DIR: locksDir,
      CODERAILS_BUILDER_REPO_PATH: repoDir,
      BUILDER_WALL_CLOCK_SECS: "5",
      PATH: `${binDir}:${process.env.PATH}`,
    });

    const state = readState(buildDir);
    if (typeof state.failureReason === "string") {
      expect(state.failureReason).not.toMatch(/^hash_mismatch:/);
    }
  });
});

describe("run-builder.sh: full state machine (steps 3-7)", () => {
  it("full happy path: stub claude writes pr_url and exits 0 -> state.json reaches pr_open with the stub's PR URL", () => {
    const buildDir = makeBuildDir();
    const locksDir = tmpDir("dashboard-run-builder-locks-");
    const repoDir = makeRepoFixture();
    const prUrl = "https://github.com/blueman82/coderails/pull/999";
    const binDir = makeStubClaudeBin(
      `echo "${prUrl}" > "${buildDir}/pr_url"; echo '{"type":"result"}' > "${buildDir}/result.json"; exit 0`
    );

    writeSnapshot(buildDir, { toolInput: { proposed_name: "happy-path-skill" } });

    const result = runWrapper(buildDir, {
      CODERAILS_BUILDER_LOCKS_DIR: locksDir,
      CODERAILS_BUILDER_REPO_PATH: repoDir,
      BUILDER_WALL_CLOCK_SECS: "5",
      PATH: `${binDir}:${process.env.PATH}`,
    });

    const state = readState(buildDir);
    expect(state.state).toBe("pr_open");
    expect(state.prUrl).toBe(prUrl);
    expect(result.status).toBe(0);
  });

  it("stub claude exits nonzero with no pr_url -> failed: nonzero_exit, with stderrTail populated", () => {
    const buildDir = makeBuildDir();
    const locksDir = tmpDir("dashboard-run-builder-locks-");
    const repoDir = makeRepoFixture();
    const binDir = makeStubClaudeBin(`echo "boom, something broke" 1>&2; exit 1`);

    writeSnapshot(buildDir, { toolInput: { proposed_name: "sad-path-skill" } });

    runWrapper(buildDir, {
      CODERAILS_BUILDER_LOCKS_DIR: locksDir,
      CODERAILS_BUILDER_REPO_PATH: repoDir,
      BUILDER_WALL_CLOCK_SECS: "5",
      PATH: `${binDir}:${process.env.PATH}`,
    });

    const state = readState(buildDir);
    expect(state.state).toBe("failed");
    expect(state.failureReason).toBe("nonzero_exit");
    expect(state.stderrTail).toContain("boom, something broke");
  });

  it("budget-breach fixture: stub claude writes result.json with subtype error_max_budget_usd, no pr_url, exits nonzero -> failed: budget_exceeded", () => {
    const buildDir = makeBuildDir();
    const locksDir = tmpDir("dashboard-run-builder-locks-");
    const repoDir = makeRepoFixture();
    const binDir = makeStubClaudeBin(
      `echo '{"type":"result","subtype":"error_max_budget_usd","is_error":true,"result":null}' > "${buildDir}/result.json"; exit 1`
    );

    writeSnapshot(buildDir, { toolInput: { proposed_name: "budget-skill" } });

    runWrapper(buildDir, {
      CODERAILS_BUILDER_LOCKS_DIR: locksDir,
      CODERAILS_BUILDER_REPO_PATH: repoDir,
      BUILDER_WALL_CLOCK_SECS: "5",
      PATH: `${binDir}:${process.env.PATH}`,
    });

    const state = readState(buildDir);
    expect(state.state).toBe("failed");
    expect(state.failureReason).toBe("budget_exceeded");
  });

  it("lock contention: a second instance queues while the first holds the lock, then both reach pr_open", async () => {
    const locksDir = tmpDir("dashboard-run-builder-locks-shared-");
    const repoDirA = makeRepoFixture();
    const repoDirB = makeRepoFixture();

    const buildDirA = makeBuildDir();
    const buildDirB = makeBuildDir();

    const prUrlA = "https://github.com/blueman82/coderails/pull/1";
    const prUrlB = "https://github.com/blueman82/coderails/pull/2";

    const binDirA = makeStubClaudeBin(
      `sleep 2; echo "${prUrlA}" > "${buildDirA}/pr_url"; echo '{}' > "${buildDirA}/result.json"; exit 0`
    );
    const binDirB = makeStubClaudeBin(
      `echo "${prUrlB}" > "${buildDirB}/pr_url"; echo '{}' > "${buildDirB}/result.json"; exit 0`
    );

    writeSnapshot(buildDirA, { toolInput: { proposed_name: "lock-a-skill" } });
    writeSnapshot(buildDirB, { toolInput: { proposed_name: "lock-b-skill" } });

    const { spawn } = await import("node:child_process");
    const childA = spawn("bash", [SCRIPT_PATH, buildDirA], {
      env: {
        ...process.env,
        CODERAILS_BUILDER_LOCKS_DIR: locksDir,
        CODERAILS_BUILDER_REPO_PATH: repoDirA,
        BUILDER_WALL_CLOCK_SECS: "10",
        PATH: `${binDirA}:${process.env.PATH}`,
      },
      stdio: "ignore",
    });

    // Give A a moment to acquire the lock first.
    await new Promise((resolve) => setTimeout(resolve, 300));

    const childB = spawn("bash", [SCRIPT_PATH, buildDirB], {
      env: {
        ...process.env,
        CODERAILS_BUILDER_LOCKS_DIR: locksDir,
        CODERAILS_BUILDER_REPO_PATH: repoDirB,
        BUILDER_POLL_INTERVAL_SECS: "1",
        BUILDER_WALL_CLOCK_SECS: "10",
        PATH: `${binDirB}:${process.env.PATH}`,
      },
      stdio: "ignore",
    });

    // Poll for B showing "queued" while A is still running.
    let sawQueued = false;
    for (let i = 0; i < 20; i++) {
      await new Promise((resolve) => setTimeout(resolve, 150));
      if (existsSync(join(buildDirB, "state.json"))) {
        const s = readState(buildDirB);
        if (s.state === "queued") {
          sawQueued = true;
          break;
        }
      }
    }
    expect(sawQueued).toBe(true);

    await new Promise<void>((resolve) => childA.on("exit", () => resolve()));
    await new Promise<void>((resolve) => childB.on("exit", () => resolve()));

    expect(readState(buildDirA).state).toBe("pr_open");
    expect(readState(buildDirB).state).toBe("pr_open");
  }, 20000);

  it("stale lock (dead pid) is discarded, not honored", () => {
    const locksDir = tmpDir("dashboard-run-builder-locks-stale-");
    mkdirSync(locksDir, { recursive: true });
    writeFileSync(join(locksDir, "builder.lock"), "999999");

    const buildDir = makeBuildDir();
    const repoDir = makeRepoFixture();
    const prUrl = "https://github.com/blueman82/coderails/pull/3";
    const binDir = makeStubClaudeBin(
      `echo "${prUrl}" > "${buildDir}/pr_url"; echo '{}' > "${buildDir}/result.json"; exit 0`
    );

    writeSnapshot(buildDir, { toolInput: { proposed_name: "stale-lock-skill" } });

    runWrapper(buildDir, {
      CODERAILS_BUILDER_LOCKS_DIR: locksDir,
      CODERAILS_BUILDER_REPO_PATH: repoDir,
      BUILDER_WALL_CLOCK_SECS: "5",
      PATH: `${binDir}:${process.env.PATH}`,
    });

    const state = readState(buildDir);
    expect(state.state).toBe("pr_open");
  });
});
