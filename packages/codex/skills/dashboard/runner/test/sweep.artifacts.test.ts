import { root, queueDir, processingDir, archiveDir, quarantineDir, runsDir, vaultNotesDir, config, writeIntent } from "./sweep.fixture";
import { describe, it, expect, vi } from "vitest";
import { writeFileSync, existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { sweepOnce } from "../src/sweep.ts";
import type { DashboardConfig } from "@coderails/dashboard-lib";

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
    const runCodexImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir,
      config: routineConfig, runsDir, vaultNotesDir, runCodexImpl, notifyImpl,
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
    const runCodexImpl = vi.fn().mockImplementation(async () => {
      writeFileSync(artifactPath, "log content"); // simulate the skill writing its artifact
      return { exitCode: 0, stdout: "", stderr: "" };
    });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir,
      config: routineConfig, runsDir, vaultNotesDir, runCodexImpl, notifyImpl: vi.fn(),
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
    const runCodexImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir,
      config: routineConfig, runsDir, vaultNotesDir, runCodexImpl, notifyImpl,
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
    const runCodexImpl = vi.fn().mockResolvedValue({
      exitCode: 1,
      stdout: "",
      stderr: "",
      spawnFailure: "timeout",
      spawnFailureReason: "codex process exceeded timeout of 1800000ms and was killed",
    });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir,
      config: routineConfig, runsDir, vaultNotesDir, runCodexImpl, notifyImpl,
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
      config: routineConfig, runsDir, vaultNotesDir, runCodexImpl: vi.fn(), notifyImpl,
    });
    expect(result.failed).toBe(1);
    expect(notifyImpl).toHaveBeenCalledWith(expect.any(String), expect.stringContaining("skill-missing"));
  });
});
