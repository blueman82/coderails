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
  // The wrapper also calls `claude --version` (Step 5, before the actual
  // build spawn) separately from the `-p` build invocation. The real CLI
  // returns immediately for --version; a test's script body (e.g. one that
  // sleeps to simulate a long build) must not apply to that unrelated call,
  // or timing-sensitive tests (watchdog timeout) would be thrown off by a
  // stub that treats every invocation identically regardless of args.
  writeFileSync(
    stubPath,
    `#!/bin/bash\ncase "$1" in\n  --version) echo "stub-claude 0.0.0"; exit 0 ;;\nesac\n${script}\n`
  );
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

  it("claude is spawned with --disallowedTools mechanically denying the merge skill and merge-adjacent bash commands, not just the prompt's own never-merge clause", () => {
    // The prompt template asks the builder never to merge, but a prompt
    // instruction is not an enforcement mechanism against a
    // compromised/confused session. --disallowedTools removes the tool
    // from what the session can invoke at all, verified separately (outside
    // this suite) to hold even alongside --dangerously-skip-permissions.
    // This test only asserts the wrapper actually passes those flags to the
    // real claude invocation, via the argv-capturing stub already used
    // elsewhere in this file.
    const buildDir = makeBuildDir();
    const locksDir = tmpDir("dashboard-run-builder-locks-");
    const repoDir = makeRepoFixture();
    const argvLog = join(buildDir, "argv.log");
    const binDir = makeStubClaudeBin(
      `printf '%s\\n' "$@" > "${argvLog}"; echo "https://github.com/blueman82/coderails/pull/1" > "${buildDir}/pr_url"; echo '{}' > "${buildDir}/result.json"; exit 0`
    );

    writeSnapshot(buildDir, { toolInput: { proposed_name: "disallow-flags-skill" } });

    runWrapper(buildDir, {
      CODERAILS_BUILDER_LOCKS_DIR: locksDir,
      CODERAILS_BUILDER_REPO_PATH: repoDir,
      BUILDER_WALL_CLOCK_SECS: "5",
      PATH: `${binDir}:${process.env.PATH}`,
    });

    const argv = readFileSync(argvLog, "utf-8");
    expect(argv).toContain("--disallowedTools");
    expect(argv).toContain("Skill(coderails:merge)");
    expect(argv).toContain("Bash(gh pr merge*)");
    expect(argv).toContain("Bash(*merge.sh*)");
    expect(argv).toContain("--dangerously-skip-permissions");
  });

  it("invalid proposed_name in the snapshot is rejected by the wrapper itself, not just trusted from spawn.ts's upstream check", () => {
    // spawn.ts validates proposed_name against ^[a-z0-9][a-z0-9-]{0,63}$
    // before ever writing snapshot.json, but the wrapper independently
    // re-asserts hash/status/toolName rather than trusting the snapshot
    // blindly — proposed_name gets the same treatment here rather than
    // being spliced unchecked into a branch name.
    const buildDir = makeBuildDir();
    const locksDir = tmpDir("dashboard-run-builder-locks-");
    const repoDir = makeRepoFixture();
    const binDir = makeStubClaudeBin(`exit 0`);

    writeSnapshot(buildDir, { toolInput: { proposed_name: "../escape" } });

    runWrapper(buildDir, {
      CODERAILS_BUILDER_LOCKS_DIR: locksDir,
      CODERAILS_BUILDER_REPO_PATH: repoDir,
      BUILDER_WALL_CLOCK_SECS: "5",
      PATH: `${binDir}:${process.env.PATH}`,
    });

    const state = readState(buildDir);
    expect(state.state).toBe("failed");
    expect(state.failureReason).toBe("invalid_proposed_name");
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

  it("watchdog wall-clock timeout terminates the run and lands a terminal failed:timeout state, not a stuck running state", () => {
    // This is the case the wrapper's on_exit trap exists to guarantee:
    // when the watchdog's SIGTERM fires mid-claude-run, the script must
    // still reach a terminal state.json rather than being left forever at
    // "running". A prior version of on_exit captured `$?` via
    // `local exit_code=$?`, which clobbers `$?` with `local`'s own exit
    // status before it's read — so on SIGTERM the guard never fired and
    // no terminal state was written at all. This test drives the real
    // watchdog path (a stub claude that sleeps somewhat longer than the
    // wall clock) rather than asserting on the trap's internals directly.
    //
    // Note: bash only handles a pending signal between commands, not while
    // blocked on a foreground child — so the wrapper doesn't react to
    // SIGTERM until the stub's own sleep finishes. The stub's sleep must
    // therefore be short (not 10x+ the wall clock) or this test would wait
    // out the full sleep duration before observing the timeout.
    const buildDir = makeBuildDir();
    const locksDir = tmpDir("dashboard-run-builder-locks-");
    const repoDir = makeRepoFixture();
    const binDir = makeStubClaudeBin(`sleep 3; exit 0`);

    writeSnapshot(buildDir, { toolInput: { proposed_name: "timeout-skill" } });

    runWrapper(buildDir, {
      CODERAILS_BUILDER_LOCKS_DIR: locksDir,
      CODERAILS_BUILDER_REPO_PATH: repoDir,
      BUILDER_WALL_CLOCK_SECS: "1",
      PATH: `${binDir}:${process.env.PATH}`,
    });

    const state = readState(buildDir);
    expect(state.state).toBe("failed");
    expect(state.failureReason).toBe("timeout");
  }, 15000);
});
