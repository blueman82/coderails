import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { mkdtempSync, rmSync, mkdirSync, writeFileSync, existsSync, utimesSync, statSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { sweepOnce, ORPHAN_THRESHOLD_MS } from "../src/sweep.ts";
import { readRuns } from "../src/runlog.ts";
import { buildArgv } from "../../app/src/lib/argv.ts";
import type { DashboardConfig } from "@coderails/dashboard-lib";

let root: string, queueDir: string, processingDir: string, archiveDir: string, quarantineDir: string, runsDir: string, vaultNotesDir: string;

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "sweep-test-"));
  queueDir = join(root, "queue");
  processingDir = join(root, "processing");
  archiveDir = join(root, "archive");
  quarantineDir = join(root, "quarantine");
  runsDir = join(root, "runs");
  vaultNotesDir = join(root, "dashboard-runs");
  mkdirSync(queueDir, { recursive: true });
});
afterEach(() => {
  rmSync(root, { recursive: true, force: true });
});

const config: DashboardConfig = {
  repos: [], wikiPaths: [],
  buttons: [
    { name: "wiki-lint", label: "WIKI LINT", command: "/coderails:wiki-lint", cwd: "/tmp", profile: "read-only" },
  ],
};

function writeIntent(runId: string, body: unknown) {
  writeFileSync(join(queueDir, `${runId}.json`), JSON.stringify(body));
}
describe("sweepOnce with routine artifact gating", () => {
  it("marks a routine run as failed when it exits 0 but the expected artifact was never written", async () => {
    const routineConfig: DashboardConfig = {
      ...config,
      routines: [
        {
          name: "wiki-lint",
          skillCommand: "/coderails:wiki-lint",
          cadence: "0 3 * * *",
          expectedArtifact: {
            artifactPath: join(root, "never-written.md"),
            maxAgeSeconds: 3600,
            predicate: { kind: "exists" },
          },
          escalation: ["notification"],
        },
      ],
    };
    writeIntent("run7", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    const notifyImpl = vi.fn();
    const runClaudeImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir,
      config: routineConfig, runsDir, vaultNotesDir, runClaudeImpl, notifyImpl,
    });
    expect(result.failed).toBe(1);
    expect(result.succeeded).toBe(0);
    expect(notifyImpl).toHaveBeenCalled();
  });

  it("marks a routine run as succeeded when the expected artifact is present", async () => {
    const artifactPath = join(root, "log.md");
    const routineConfig: DashboardConfig = {
      ...config,
      routines: [
        {
          name: "wiki-lint",
          skillCommand: "/coderails:wiki-lint",
          cadence: "0 3 * * *",
          expectedArtifact: { artifactPath, maxAgeSeconds: 3600, predicate: { kind: "exists" } },
          escalation: ["notification"],
        },
      ],
    };
    writeIntent("run8", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    const runClaudeImpl = vi.fn().mockImplementation(async () => {
      writeFileSync(artifactPath, "log content"); // simulate the skill writing its artifact
      return { exitCode: 0, stdout: "", stderr: "" };
    });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir,
      config: routineConfig, runsDir, vaultNotesDir, runClaudeImpl, notifyImpl: vi.fn(),
    });
    expect(result.succeeded).toBe(1);
  });

  it("gates a buttonRef-named routine (routine.name !== button.name) through the artifact check, not just exit code (C4)", async () => {
    const artifactPath = join(root, "never-written-buttonref.md");
    const routineConfig: DashboardConfig = {
      ...config,
      routines: [
        {
          name: "wiki-lint-nightly", // deliberately differs from the buttonRef'd button's name
          buttonRef: "wiki-lint",
          cadence: "0 3 * * *",
          expectedArtifact: { artifactPath, maxAgeSeconds: 3600, predicate: { kind: "exists" } },
          escalation: ["notification"],
        },
      ],
    };
    writeIntent("run-buttonref", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    const notifyImpl = vi.fn();
    // Exits 0 without writing the expected artifact — a plain non-routine
    // button press would call this a success; the routine's artifact gate
    // must still catch it because the routine resolves via buttonRef.
    const runClaudeImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir,
      config: routineConfig, runsDir, vaultNotesDir, runClaudeImpl, notifyImpl,
    });
    expect(result.failed).toBe(1);
    expect(result.succeeded).toBe(0);
    expect(notifyImpl).toHaveBeenCalledWith(expect.any(String), expect.stringContaining("artifact-gate-failed"));
  });

  it("writes a failure terminal marker to the last-marker artifact when the routine is killed by the exec timeout (U1)", async () => {
    const artifactPath = join(root, "run-{date}.log");
    const fixedClock = () => new Date("2026-07-23T20:00:00Z");
    const routineConfig: DashboardConfig = {
      ...config,
      routines: [
        {
          name: "wiki-lint",
          skillCommand: "/coderails:wiki-lint",
          cadence: "0 3 * * *",
          expectedArtifact: {
            artifactPath,
            maxAgeSeconds: 3600,
            predicate: { kind: "last-marker", success: "run=ok", failures: ["abort=", "refused="] },
          },
          escalation: ["notification"],
        },
      ],
    };
    writeIntent("run-timeout", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    const notifyImpl = vi.fn();
    // Simulates exec.ts's timeout path: the child was SIGKILLed mid-run,
    // so it never reached its own terminal-marker-writing step — the run
    // log this artifactPath resolves to (see docs-sync SKILL.md) has stage
    // lines but no run=ok/abort=/refused= line.
    const runClaudeImpl = vi.fn().mockResolvedValue({
      exitCode: 1,
      stdout: "",
      stderr: "",
      spawnFailure: "timeout",
      spawnFailureReason: "claude process exceeded timeout of 1800000ms and was killed",
    });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir,
      config: routineConfig, runsDir, vaultNotesDir, runClaudeImpl, notifyImpl,
      clock: fixedClock,
    });
    expect(result.failed).toBe(1);
    const resolvedPath = join(root, "run-2026-07-23.log");
    expect(existsSync(resolvedPath)).toBe(true);
    const content = readFileSync(resolvedPath, "utf-8");
    expect(content).toContain("abort=runner-timeout-kill");
    // The runner's own marker must not fabricate a success line — the
    // routine's own last-marker gate still must read this run as failed.
    expect(content).not.toContain("run=ok");
    expect(notifyImpl).toHaveBeenCalledWith(expect.any(String), expect.stringContaining("exec-error"));
  });

  it("escalates with failure class skill-missing when a routine's foreignSkillPath does not exist", async () => {
    const routineConfig: DashboardConfig = {
      ...config,
      routines: [
        {
          name: "wiki-lint",
          skillCommand: "/coderails:wiki-lint",
          cadence: "0 3 * * *",
          foreignSkillPath: join(root, "does-not-exist", "SKILL.md"),
          expectedArtifact: { artifactPath: join(root, "log.md"), maxAgeSeconds: 3600, predicate: { kind: "exists" } },
          escalation: ["notification"],
        },
      ],
    };
    writeIntent("run9", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    const notifyImpl = vi.fn();
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir,
      config: routineConfig, runsDir, vaultNotesDir, runClaudeImpl: vi.fn(), notifyImpl,
    });
    expect(result.failed).toBe(1);
    expect(notifyImpl).toHaveBeenCalledWith(expect.any(String), expect.stringContaining("skill-missing"));
  });
});

describe("sweepOnce per-intent failure boundary (B1)", () => {
  it("quarantines a poison intent whose input makes buildArgv throw, escalates runner-error, and continues to the next queued intent", async () => {
    // inputAllowed: true — this test exercises the buildArgv-throws path
    // specifically, which requires clearing the newer inputAllowed
    // authorization check (above) to reach buildArgv at all.
    const inputAllowedConfig: DashboardConfig = {
      ...config,
      buttons: [{ name: "wiki-lint", label: "WIKI LINT", command: "/coderails:wiki-lint", cwd: "/tmp", profile: "read-only", inputAllowed: true }],
    };
    writeIntent("poison", { button: "wiki-lint", input: "-x", requestedAt: Date.now(), source: "cli" });
    writeIntent("healthy", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    const notifyImpl = vi.fn();
    const runClaudeImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config: inputAllowedConfig, runsDir, vaultNotesDir, runClaudeImpl, notifyImpl,
    });
    expect(existsSync(join(quarantineDir, "poison.json"))).toBe(true);
    expect(result.failed).toBeGreaterThanOrEqual(1);
    expect(notifyImpl).toHaveBeenCalledWith(expect.any(String), expect.stringContaining("runner-error"));
    // The second, healthy intent must still be processed — the loop didn't die.
    expect(existsSync(join(archiveDir, "healthy.json"))).toBe(true);
    expect(result.succeeded).toBe(1);
  });

  it("continues the sweep when appendRun is forced to throw mid-intent", async () => {
    writeIntent("run-a", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    writeIntent("run-b", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    // runsDir is a file, not a directory: appendRun's mkdirSync(dir, {recursive:true}) throws EEXIST.
    const brokenRunsDir = join(root, "runs-is-a-file");
    writeFileSync(brokenRunsDir, "not a directory");
    const runClaudeImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config,
      runsDir: brokenRunsDir, vaultNotesDir, runClaudeImpl, notifyImpl: vi.fn(),
    });
    // Both intents were claimed and the sweep did not crash despite every
    // appendRun call throwing.
    expect(result.claimed).toBe(2);
  });
});

describe("sweepOnce orphan recovery (B3)", () => {
  it("recovers a stale file left in processing/ into quarantine with a synthetic run record and escalation", async () => {
    mkdirSync(processingDir, { recursive: true });
    writeFileSync(join(processingDir, "stale-run.json"), JSON.stringify({ button: "wiki-lint" }));
    const staleTime = new Date(Date.now() - ORPHAN_THRESHOLD_MS - 60_000);
    utimesSync(join(processingDir, "stale-run.json"), staleTime, staleTime);

    const notifyImpl = vi.fn();
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir,
      runClaudeImpl: vi.fn(), notifyImpl,
    });

    expect(existsSync(join(processingDir, "stale-run.json"))).toBe(false);
    expect(existsSync(join(quarantineDir, "stale-run.json"))).toBe(true);
    expect(notifyImpl).toHaveBeenCalledWith(expect.any(String), expect.stringContaining("runner-error"));
    void result;
  });

  it("leaves a fresh file in processing/ untouched (may belong to a concurrently-running sweep)", async () => {
    mkdirSync(processingDir, { recursive: true });
    writeFileSync(join(processingDir, "fresh-run.json"), JSON.stringify({ button: "wiki-lint" }));

    await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir,
      runClaudeImpl: vi.fn(),
    });

    expect(existsSync(join(processingDir, "fresh-run.json"))).toBe(true);
    expect(existsSync(join(quarantineDir, "fresh-run.json"))).toBe(false);
  });
});

describe("sweepOnce inputAllowed authorization (queue path)", () => {
  it("quarantines an intent carrying input against an inputAllowed:false button, and never spawns", async () => {
    const noInputConfig: DashboardConfig = {
      ...config,
      buttons: [{ name: "wiki-lint", label: "WIKI LINT", command: "/coderails:wiki-lint", cwd: "/tmp", profile: "read-only" }],
    };
    writeIntent("unauthorized-input", { button: "wiki-lint", input: "arbitrary prompt", requestedAt: Date.now(), source: "cli" });
    const runClaudeImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config: noInputConfig, runsDir, vaultNotesDir, runClaudeImpl,
    });
    expect(result.quarantined).toBe(1);
    expect(existsSync(join(quarantineDir, "unauthorized-input.json"))).toBe(true);
    expect(runClaudeImpl).not.toHaveBeenCalled();
  });

  it("still runs normally when input is carried against an inputAllowed:true button", async () => {
    const inputAllowedConfig: DashboardConfig = {
      ...config,
      buttons: [{ name: "with-input", label: "WITH INPUT", command: "/coderails:assumptions", cwd: "/tmp", profile: "read-only", inputAllowed: true }],
    };
    writeIntent("allowed-input", { button: "with-input", input: "hello", requestedAt: Date.now(), source: "cli" });
    const runClaudeImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config: inputAllowedConfig, runsDir, vaultNotesDir, runClaudeImpl,
    });
    expect(result.quarantined).toBe(0);
    expect(result.succeeded).toBe(1);
    expect(runClaudeImpl).toHaveBeenCalled();
  });

  it("still runs normally when an intent with no input targets an inputAllowed:false button", async () => {
    const noInputConfig: DashboardConfig = {
      ...config,
      buttons: [{ name: "wiki-lint", label: "WIKI LINT", command: "/coderails:wiki-lint", cwd: "/tmp", profile: "read-only" }],
    };
    writeIntent("no-input", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    const runClaudeImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config: noInputConfig, runsDir, vaultNotesDir, runClaudeImpl,
    });
    expect(result.quarantined).toBe(0);
    expect(result.succeeded).toBe(1);
    expect(runClaudeImpl).toHaveBeenCalled();
  });
});
