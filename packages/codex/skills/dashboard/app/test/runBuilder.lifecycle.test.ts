import { SCRIPT_PATH, tmpDir, readState, makeBuildDir, computeHash, writeSnapshot, makeRepoFixture, makeStubCodexBin, runWrapper } from "./runBuilder.fixture";
import { describe, it, expect } from "vitest";
import { writeFileSync, readFileSync, existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";

describe("run_builder.py: full state machine (steps 3-7)", () => {
  it("full happy path: stub codex exits 0 -> state.json reaches ready_for_review with the worktree path", () => {
    const buildDir = makeBuildDir();
    const locksDir = tmpDir("dashboard-run-builder-locks-");
    const repoDir = makeRepoFixture();
    const binDir = makeStubCodexBin({ outputs: { [join(buildDir, "result.json")]: "{\"type\":\"result\"}\n" } });

    writeSnapshot(buildDir, { toolInput: { proposed_name: "happy-path-skill" } });

    const result = runWrapper(buildDir, {
      CODERAILS_BUILDER_LOCKS_DIR: locksDir,
      CODERAILS_BUILDER_REPO_PATH: repoDir,
      BUILDER_WALL_CLOCK_SECS: "5",
      PATH: `${binDir}:${process.env.PATH}`,
    });

    const state = readState(buildDir);
    expect(state.state).toBe("ready_for_review");
    expect(state.worktreePath).toBe(
      join(repoDir, ".codex", "worktrees", `skill-build-${computeHash({ proposed_name: "happy-path-skill" }).slice(0, 8)}`)
    );
    expect(result.status).toBe(0);
  });

  it("uses current Codex JSON and the workspace-write sandbox with a protected positional prompt", () => {
    const buildDir = makeBuildDir();
    const locksDir = tmpDir("dashboard-run-builder-locks-");
    const repoDir = makeRepoFixture();
    const argvLog = join(buildDir, "argv.log");
    const binDir = makeStubCodexBin(
      { argvLog, argvLines: true, outputs: { [join(buildDir, "result.json")]: "{}\n" } }
    );

    writeSnapshot(buildDir, { toolInput: { proposed_name: "disallow-flags-skill" } });

    runWrapper(buildDir, {
      CODERAILS_BUILDER_LOCKS_DIR: locksDir,
      CODERAILS_BUILDER_REPO_PATH: repoDir,
      BUILDER_WALL_CLOCK_SECS: "5",
      PATH: `${binDir}:${process.env.PATH}`,
    });

    const argv = readFileSync(argvLog, "utf-8");
    const argvLines = argv.trimEnd().split("\n");
    expect(argvLines[0]).toBe("exec");
    expect(argvLines.filter((arg) => arg === "exec")).toHaveLength(1);
    expect(argv).toContain("--sandbox\nworkspace-write");
    expect(argv).toContain("sandbox_workspace_write.network_access=false");
    expect(argv).toContain("--json");
    expect(argv).toContain("--\n");
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
    const binDir = makeStubCodexBin({});

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

  it("stub codex exits nonzero -> failed: nonzero_exit, with stderrTail populated", () => {
    const buildDir = makeBuildDir();
    const locksDir = tmpDir("dashboard-run-builder-locks-");
    const repoDir = makeRepoFixture();
    const binDir = makeStubCodexBin({ stderr: "boom, something broke", exitCode: 1 });

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

  it("unrecognized-flag fixture: stub codex writes 'unknown option' to stderr and exits nonzero -> failed: codex_cli_flag_rejected, distinguishable from a routine build failure", () => {
    // Verified empirically against the real codex CLI: an unrecognized
    // flag on some future or older
    // CLI version) produces exactly this stderr shape and a nonzero exit
    // before any session starts. Distinguishing this from a routine
    // "nonzero_exit" build failure matters because it signals the
    // mechanical merge-containment layer failed to even start.
    const buildDir = makeBuildDir();
    const locksDir = tmpDir("dashboard-run-builder-locks-");
    const repoDir = makeRepoFixture();
    const binDir = makeStubCodexBin({ stderr: "error: unknown option '--unknown-dashboard-flag'", exitCode: 1 });

    writeSnapshot(buildDir, { toolInput: { proposed_name: "flag-rejected-skill" } });

    runWrapper(buildDir, {
      CODERAILS_BUILDER_LOCKS_DIR: locksDir,
      CODERAILS_BUILDER_REPO_PATH: repoDir,
      BUILDER_WALL_CLOCK_SECS: "5",
      PATH: `${binDir}:${process.env.PATH}`,
    });

    const state = readState(buildDir);
    expect(state.state).toBe("failed");
    expect(state.failureReason).toBe("codex_cli_flag_rejected");
  });

  it("current Codex budget failure has no stable JSON code and remains a nonzero exit", () => {
    const buildDir = makeBuildDir();
    const locksDir = tmpDir("dashboard-run-builder-locks-");
    const repoDir = makeRepoFixture();
    const binDir = makeStubCodexBin(
      { exitCode: 1, outputs: { [join(buildDir, "result.json")]: "{\"type\":\"error\",\"message\":\"shared rollout token budget exhausted\"}\n{\"type\":\"turn.failed\",\"error\":{\"message\":\"shared rollout token budget exhausted\"}}\n" } }
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
    expect(state.failureReason).toBe("nonzero_exit");
  });

  it("lock contention: a second instance queues while the first holds the lock, then both reach ready_for_review", async () => {
    const locksDir = tmpDir("dashboard-run-builder-locks-shared-");
    const repoDirA = makeRepoFixture();
    const repoDirB = makeRepoFixture();

    const buildDirA = makeBuildDir();
    const buildDirB = makeBuildDir();

    const binDirA = makeStubCodexBin(
      { sleepSeconds: 2, outputs: { [join(buildDirA, "result.json")]: "{}\n" } }
    );
    const binDirB = makeStubCodexBin(
      { outputs: { [join(buildDirB, "result.json")]: "{}\n" } }
    );

    writeSnapshot(buildDirA, { toolInput: { proposed_name: "lock-a-skill" } });
    writeSnapshot(buildDirB, { toolInput: { proposed_name: "lock-b-skill" } });

    const { spawn } = await import("node:child_process");
    const childA = spawn("python3", [SCRIPT_PATH, buildDirA], {
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

    const childB = spawn("python3", [SCRIPT_PATH, buildDirB], {
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

    expect(readState(buildDirA).state).toBe("ready_for_review");
    expect(readState(buildDirB).state).toBe("ready_for_review");
  }, 20000);

  it("stale lock (dead pid) is discarded, not honored", () => {
    const locksDir = tmpDir("dashboard-run-builder-locks-stale-");
    mkdirSync(locksDir, { recursive: true });
    writeFileSync(join(locksDir, "builder.lock"), "999999");

    const buildDir = makeBuildDir();
    const repoDir = makeRepoFixture();
    const binDir = makeStubCodexBin({ outputs: { [join(buildDir, "result.json")]: "{}\n" } });

    writeSnapshot(buildDir, { toolInput: { proposed_name: "stale-lock-skill" } });

    runWrapper(buildDir, {
      CODERAILS_BUILDER_LOCKS_DIR: locksDir,
      CODERAILS_BUILDER_REPO_PATH: repoDir,
      BUILDER_WALL_CLOCK_SECS: "5",
      PATH: `${binDir}:${process.env.PATH}`,
    });

    const state = readState(buildDir);
    expect(state.state).toBe("ready_for_review");
  });

  it("watchdog wall-clock timeout terminates the run and lands a terminal failed:timeout state, not a stuck running state", () => {
    // This is the case the wrapper's on_exit trap exists to guarantee:
    // when the watchdog's SIGTERM fires mid-codex-run, the script must
    // still reach a terminal state.json rather than being left forever at
    // "running". A prior version of on_exit captured `$?` via
    // `local exit_code=$?`, which clobbers `$?` with `local`'s own exit
    // status before it's read — so on SIGTERM the guard never fired and
    // no terminal state was written at all. This test drives the real
    // watchdog path (a stub codex that sleeps somewhat longer than the
    // wall clock) rather than asserting on the trap's internals directly.
    //
    // The native child sleeps beyond the watchdog bound so timeout must settle state.
    const buildDir = makeBuildDir();
    const locksDir = tmpDir("dashboard-run-builder-locks-");
    const repoDir = makeRepoFixture();
    const binDir = makeStubCodexBin({ sleepSeconds: 3 });

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
