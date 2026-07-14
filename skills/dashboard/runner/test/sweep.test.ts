import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { mkdtempSync, rmSync, mkdirSync, writeFileSync, existsSync, utimesSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { sweepOnce, ORPHAN_THRESHOLD_MS } from "../src/sweep.ts";
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

describe("sweepOnce", () => {
  it("claims a well-formed intent by moving it from queue to processing, then to archive on success", async () => {
    writeIntent("run1", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    const runClaudeImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir, runClaudeImpl,
    });
    expect(result.claimed).toBe(1);
    expect(existsSync(join(queueDir, "run1.json"))).toBe(false);
    expect(existsSync(join(processingDir, "run1.json"))).toBe(false);
    expect(existsSync(join(archiveDir, "run1.json"))).toBe(true);
    expect(runClaudeImpl).toHaveBeenCalledWith(["-p", "/coderails:wiki-lint", "--allowedTools", "Read", "Grep", "Glob"], "/tmp");
  });

  it("moves a malformed intent to quarantine and continues the sweep", async () => {
    writeIntent("bad1", { button: 42 }); // fails parseIntent
    writeIntent("run2", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    const runClaudeImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir, runClaudeImpl,
    });
    expect(result.quarantined).toBe(1);
    expect(existsSync(join(quarantineDir, "bad1.json"))).toBe(true);
    expect(existsSync(join(archiveDir, "run2.json"))).toBe(true);
  });

  it("quarantines an intent whose button name matches no ButtonDef", async () => {
    writeIntent("run3", { button: "does-not-exist", requestedAt: Date.now(), source: "cli" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir,
      runClaudeImpl: vi.fn(),
    });
    expect(result.quarantined).toBe(1);
    expect(existsSync(join(quarantineDir, "run3.json"))).toBe(true);
  });

  it("records a JSONL run entry for a claimed intent", async () => {
    writeIntent("run4", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    const runClaudeImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    await sweepOnce({ queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir, runClaudeImpl });
    const { readRuns } = await import("../src/runlog.ts");
    const runs = readRuns(10, { runsDir });
    expect(runs).toHaveLength(1);
    expect(runs[0].button).toBe("wiki-lint");
    expect(runs[0].exitCode).toBe(0);
  });

  it("returns claimed: 0 when the queue is empty", async () => {
    const result = await sweepOnce({ queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir, runClaudeImpl: vi.fn() });
    expect(result.claimed).toBe(0);
  });

  it("processes multiple queued intents in one sweep", async () => {
    writeIntent("run5", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    writeIntent("run6", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    const runClaudeImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({ queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir, runClaudeImpl });
    expect(result.claimed).toBe(2);
    expect(result.succeeded).toBe(2);
  });
});

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
    writeIntent("poison", { button: "wiki-lint", input: "-x", requestedAt: Date.now(), source: "cli" });
    writeIntent("healthy", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    const notifyImpl = vi.fn();
    const runClaudeImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir, runClaudeImpl, notifyImpl,
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
    // runsDir is a file, not a directory: appendRun's mkdirSync(dir, {recursive:true}) throws ENOTDIR.
    const brokenRunsDir = join(root, "runs-is-a-file");
    writeFileSync(brokenRunsDir, "not a directory");
    const runClaudeImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config,
      runsDir: brokenRunsDir, vaultNotesDir, runClaudeImpl,
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

describe("sweepOnce coverage gaps (I2)", () => {
  it("does not crash and skips a file whose claim rename is pre-empted by a racing sweeper (renameSync throws on the second sweeper's attempt)", async () => {
    writeIntent("racer", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    writeIntent("run-after-race", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });

    // Two sweepOnce calls sharing the same queue/processing dirs is a real
    // instance of the exact race sweepOnce's claim-rename comment
    // describes (dashboard-lib README's "Lifecycle" contract): whichever
    // sweeper's renameSync loses the race gets a real ENOENT from the
    // actual filesystem, not a mock. Running them genuinely concurrently
    // (Promise.all) exercises sweepOnce's own catch-and-continue on that
    // exact error rather than a hand-rolled substitute.
    const [resultA, resultB] = await Promise.all([
      sweepOnce({
        queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir,
        runClaudeImpl: vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" }),
      }),
      sweepOnce({
        queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir,
        runClaudeImpl: vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" }),
      }),
    ]);

    // Across both concurrent sweeps, each of the two intents was claimed
    // by exactly one of them — the race didn't crash either sweep, drop an
    // intent, or double-process one.
    expect(resultA.claimed + resultB.claimed).toBe(2);
    expect(resultA.succeeded + resultB.succeeded).toBe(2);
    expect(existsSync(join(archiveDir, "racer.json"))).toBe(true);
    expect(existsSync(join(archiveDir, "run-after-race.json"))).toBe(true);
  });

  it("asserts real buildArgv output is what a bypass-profile button produces end to end", async () => {
    const bypassConfig: DashboardConfig = {
      ...config,
      buttons: [{ name: "bypass-btn", label: "BYPASS", command: "/coderails:merge", cwd: "/tmp", profile: "bypass" }],
    };
    writeIntent("bypass-run", { button: "bypass-btn", requestedAt: Date.now(), source: "cli" });
    const runClaudeImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config: bypassConfig, runsDir, vaultNotesDir, runClaudeImpl,
    });
    const expectedArgv = buildArgv(bypassConfig.buttons[0], undefined);
    expect(runClaudeImpl).toHaveBeenCalledWith(expectedArgv, "/tmp");
  });

  it("asserts real buildArgv output for a default (read-only) profile button", async () => {
    writeIntent("default-run", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    const runClaudeImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir, runClaudeImpl,
    });
    const expectedArgv = buildArgv(config.buttons[0], undefined);
    expect(runClaudeImpl).toHaveBeenCalledWith(expectedArgv, "/tmp");
  });

  it("asserts real buildArgv output for an input-bearing button", async () => {
    writeIntent("input-run", { button: "wiki-lint", input: "some literal input", requestedAt: Date.now(), source: "cli" });
    const runClaudeImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir, runClaudeImpl,
    });
    const expectedArgv = buildArgv(config.buttons[0], "some literal input");
    expect(runClaudeImpl).toHaveBeenCalledWith(expectedArgv, "/tmp");
  });

  it("rejects a {vault}-relative artifact path whose resolved location escapes to a sibling directory sharing the vault root as a string prefix (sibling-prefix traversal)", async () => {
    const vaultRoot = join(root, "vault");
    const evilSibling = join(root, "vault-evil");
    mkdirSync(vaultRoot, { recursive: true });
    mkdirSync(evilSibling, { recursive: true });
    writeFileSync(join(evilSibling, "f.md"), "leaked");

    const routineConfig: DashboardConfig = {
      ...config,
      wikiPaths: [vaultRoot],
      routines: [
        {
          name: "wiki-lint",
          skillCommand: "/coderails:wiki-lint",
          cadence: "0 3 * * *",
          // Uses the {vault} token (so escapesRoot's containment check
          // actually runs) with a "../" segment that resolves into a
          // sibling directory whose name merely starts with the vault
          // root's own path as a string prefix — the case a naive
          // `resolvedPath.startsWith(root)` (without the trailing sep)
          // would wrongly accept.
          expectedArtifact: { artifactPath: "{vault}/../vault-evil/f.md", maxAgeSeconds: 3600, predicate: { kind: "exists" } },
          escalation: ["notification"],
        },
      ],
    };
    writeIntent("sibling-run", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    const notifyImpl = vi.fn();
    const runClaudeImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir,
      config: routineConfig, runsDir, vaultNotesDir, runClaudeImpl, notifyImpl,
    });
    expect(result.failed).toBe(1);
    expect(notifyImpl).toHaveBeenCalledWith(expect.any(String), expect.stringContaining("artifact-gate-failed"));
  });

  it("passes an artifact exactly at the maxAgeSeconds boundary", async () => {
    const artifactPath = join(root, "boundary.md");
    writeFileSync(artifactPath, "content");
    const maxAgeSeconds = 3600;
    // Set mtime such that (Date.now() - mtimeMs)/1000 is comfortably under
    // maxAgeSeconds — a boundary check on the "fresh" side, since exact
    // floating-point equality at the threshold is inherently racy against
    // wall-clock time elapsed during the test itself.
    const freshTime = new Date(Date.now() - (maxAgeSeconds - 5) * 1000);
    utimesSync(artifactPath, freshTime, freshTime);
    const stat = statSync(artifactPath);
    expect((Date.now() - stat.mtimeMs) / 1000).toBeLessThan(maxAgeSeconds);

    const routineConfig: DashboardConfig = {
      ...config,
      routines: [
        {
          name: "wiki-lint",
          skillCommand: "/coderails:wiki-lint",
          cadence: "0 3 * * *",
          expectedArtifact: { artifactPath, maxAgeSeconds, predicate: { kind: "exists" } },
          escalation: ["notification"],
        },
      ],
    };
    writeIntent("boundary-run", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    const runClaudeImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir,
      config: routineConfig, runsDir, vaultNotesDir, runClaudeImpl, notifyImpl: vi.fn(),
    });
    expect(result.succeeded).toBe(1);
  });

  it("returns claimed: 0 and does not throw when queueDir is missing entirely", async () => {
    rmSync(queueDir, { recursive: true, force: true });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir, runClaudeImpl: vi.fn(),
    });
    expect(result.claimed).toBe(0);
  });

  it("counts a quarantined malformed intent toward result.claimed", async () => {
    writeIntent("bad-claimed", { button: 42 });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir, runClaudeImpl: vi.fn(),
    });
    expect(result.claimed).toBe(1);
    expect(result.quarantined).toBe(1);
  });
});
