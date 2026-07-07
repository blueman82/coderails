import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { mkdtempSync, rmSync, mkdirSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { sweepOnce } from "../src/sweep.ts";
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
  repos: [], wikiPaths: [], memoryPaths: [],
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
  it("marks a routine run as failed when it exits 0 but the expected artifact was never written (E4)", async () => {
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
