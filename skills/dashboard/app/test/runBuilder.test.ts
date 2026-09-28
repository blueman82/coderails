import { tmpDir, readState, makeBuildDir, writeSnapshot, makeRepoFixture, makeStubClaudeBin, runWrapper } from "./runBuilder.fixture";
import { describe, it, expect } from "vitest";
import { writeFileSync, existsSync, mkdirSync, symlinkSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { join } from "node:path";

describe("run_builder.py: hash re-validation (steps 1-2)", () => {
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
    const binDir = makeStubClaudeBin({ argvLog: stubLog });

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

  it("repo without .claude-plugin/plugin.json -> failed: bad_repo_path:no_identity_file, and the stub claude is never invoked", () => {
    const buildDir = makeBuildDir();
    const locksDir = tmpDir("dashboard-run-builder-locks-");
    const stubLog = join(buildDir, "stub-invocations.log");
    const binDir = makeStubClaudeBin({ argvLog: stubLog });

    // A real git repo that is NOT coderails: has .git but no identity file.
    const repoDir = tmpDir("dashboard-run-builder-notcoderails-");
    execFileSync("git", ["init", "-q", repoDir]);

    writeSnapshot(buildDir, { toolInput: { proposed_name: "x" } });

    runWrapper(buildDir, {
      CODERAILS_BUILDER_LOCKS_DIR: locksDir,
      CODERAILS_BUILDER_REPO_PATH: repoDir,
      PATH: `${binDir}:${process.env.PATH}`,
    });

    const state = readState(buildDir);
    expect(state.state).toBe("failed");
    expect(state.failureReason).toBe("bad_repo_path:no_identity_file");
    expect(existsSync(stubLog)).toBe(false);
  });

  it("symlinked plugin.json pointing at a genuine coderails identity -> failed: bad_repo_path:no_identity_file", () => {
    const buildDir = makeBuildDir();
    const locksDir = tmpDir("dashboard-run-builder-locks-");
    const stubLog = join(buildDir, "stub-invocations.log");
    const binDir = makeStubClaudeBin({ argvLog: stubLog });

    // A foreign repo whose plugin.json is a symlink to a real coderails
    // identity file must NOT borrow that identity. The guard confirms the
    // path is the real checkout, so a symlinked identity file is rejected.
    const genuineDir = tmpDir("dashboard-run-builder-genuine-");
    writeFileSync(join(genuineDir, "plugin.json"), JSON.stringify({ name: "coderails" }));

    const repoDir = tmpDir("dashboard-run-builder-symlink-");
    execFileSync("git", ["init", "-q", repoDir]);
    mkdirSync(join(repoDir, ".claude-plugin"));
    symlinkSync(join(genuineDir, "plugin.json"), join(repoDir, ".claude-plugin", "plugin.json"));

    writeSnapshot(buildDir, { toolInput: { proposed_name: "x" } });

    runWrapper(buildDir, {
      CODERAILS_BUILDER_LOCKS_DIR: locksDir,
      CODERAILS_BUILDER_REPO_PATH: repoDir,
      PATH: `${binDir}:${process.env.PATH}`,
    });

    const state = readState(buildDir);
    expect(state.state).toBe("failed");
    expect(state.failureReason).toBe("bad_repo_path:no_identity_file");
    expect(existsSync(stubLog)).toBe(false);
  });

  it("plugin.json that merely MENTIONS coderails without being it -> failed: bad_repo_path:wrong_identity", () => {
    const buildDir = makeBuildDir();
    const locksDir = tmpDir("dashboard-run-builder-locks-");
    const stubLog = join(buildDir, "stub-invocations.log");
    const binDir = makeStubClaudeBin({ argvLog: stubLog });

    // The identity check must compare the name FIELD exactly — a substring
    // match would let a companion plugin that lists coderails as a keyword
    // run the bypass-permissions builder in the wrong repo.
    const repoDir = tmpDir("dashboard-run-builder-lookalike-");
    execFileSync("git", ["init", "-q", repoDir]);
    mkdirSync(join(repoDir, ".claude-plugin"));
    writeFileSync(
      join(repoDir, ".claude-plugin", "plugin.json"),
      JSON.stringify({ name: "other-plugin", keywords: ["coderails", "companion"] }),
    );

    writeSnapshot(buildDir, { toolInput: { proposed_name: "x" } });

    runWrapper(buildDir, {
      CODERAILS_BUILDER_LOCKS_DIR: locksDir,
      CODERAILS_BUILDER_REPO_PATH: repoDir,
      PATH: `${binDir}:${process.env.PATH}`,
    });

    const state = readState(buildDir);
    expect(state.state).toBe("failed");
    expect(state.failureReason).toBe("bad_repo_path:wrong_identity");
    expect(existsSync(stubLog)).toBe(false);
  });

  it("matching hash passes re-validation and does not fail with a hash_mismatch reason", () => {
    const buildDir = makeBuildDir();
    const locksDir = tmpDir("dashboard-run-builder-locks-");
    const repoDir = makeRepoFixture();
    const binDir = makeStubClaudeBin({});

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
