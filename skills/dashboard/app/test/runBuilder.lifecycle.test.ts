import { SCRIPT_PATH, tmpDir, readState, makeBuildDir, writeSnapshot, makeRepoFixture, makeStubClaudeBin, runWrapper } from "./runBuilder.fixture";
import { describe, it, expect } from "vitest";
import { writeFileSync, readFileSync, existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";

describe("run_builder.py: full state machine (steps 3-7)", () => {
  it("full happy path: stub claude writes pr_url and exits 0 -> state.json reaches pr_open with the stub's PR URL", () => {
    const buildDir = makeBuildDir();
    const locksDir = tmpDir("dashboard-run-builder-locks-");
    const repoDir = makeRepoFixture();
    const prUrl = "https://github.com/blueman82/coderails/pull/999";
    const binDir = makeStubClaudeBin(
      { outputs: { [join(buildDir, "pr_url")]: prUrl + "\n", [join(buildDir, "result.json")]: "{\"type\":\"result\"}\n" } }
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
      { argvLog, argvLines: true, outputs: { [join(buildDir, "pr_url")]: "https://github.com/blueman82/coderails/pull/1\n", [join(buildDir, "result.json")]: "{}\n" } }
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
    expect(argv).toContain("Bash(*merge.py*)");
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
    const binDir = makeStubClaudeBin({});

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
    const binDir = makeStubClaudeBin({ stderr: "boom, something broke", exitCode: 1 });

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

  it("unrecognized-flag fixture: stub claude writes 'unknown option' to stderr and exits nonzero -> failed: claude_cli_flag_rejected, distinguishable from a routine build failure", () => {
    // Verified empirically against the real claude CLI: an unrecognized
    // flag (e.g. an incompatible --disallowedTools on some future/older
    // CLI version) produces exactly this stderr shape and a nonzero exit
    // before any session starts. Distinguishing this from a routine
    // "nonzero_exit" build failure matters because it signals the
    // mechanical merge-containment layer failed to even start.
    const buildDir = makeBuildDir();
    const locksDir = tmpDir("dashboard-run-builder-locks-");
    const repoDir = makeRepoFixture();
    const binDir = makeStubClaudeBin({ stderr: "error: unknown option '--disallowedTools'", exitCode: 1 });

    writeSnapshot(buildDir, { toolInput: { proposed_name: "flag-rejected-skill" } });

    runWrapper(buildDir, {
      CODERAILS_BUILDER_LOCKS_DIR: locksDir,
      CODERAILS_BUILDER_REPO_PATH: repoDir,
      BUILDER_WALL_CLOCK_SECS: "5",
      PATH: `${binDir}:${process.env.PATH}`,
    });

    const state = readState(buildDir);
    expect(state.state).toBe("failed");
    expect(state.failureReason).toBe("claude_cli_flag_rejected");
  });

  it("budget-breach fixture: stub claude writes result.json with subtype error_max_budget_usd, no pr_url, exits nonzero -> failed: budget_exceeded", () => {
    const buildDir = makeBuildDir();
    const locksDir = tmpDir("dashboard-run-builder-locks-");
    const repoDir = makeRepoFixture();
    const binDir = makeStubClaudeBin(
      { exitCode: 1, outputs: { [join(buildDir, "result.json")]: "{\"type\":\"result\",\"subtype\":\"error_max_budget_usd\",\"is_error\":true,\"result\":null}\n" } }
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
      { sleepSeconds: 2, outputs: { [join(buildDirA, "pr_url")]: prUrlA + "\n", [join(buildDirA, "result.json")]: "{}\n" } }
    );
    const binDirB = makeStubClaudeBin(
      { outputs: { [join(buildDirB, "pr_url")]: prUrlB + "\n", [join(buildDirB, "result.json")]: "{}\n" } }
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
      { outputs: { [join(buildDir, "pr_url")]: prUrl + "\n", [join(buildDir, "result.json")]: "{}\n" } }
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
    // The native child sleeps beyond the watchdog bound so timeout must settle state.
    const buildDir = makeBuildDir();
    const locksDir = tmpDir("dashboard-run-builder-locks-");
    const repoDir = makeRepoFixture();
    const binDir = makeStubClaudeBin({ sleepSeconds: 3 });

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
