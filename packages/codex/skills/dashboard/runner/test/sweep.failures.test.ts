import { root, queueDir, processingDir, archiveDir, quarantineDir, runsDir, vaultNotesDir, config, writeIntent } from "./sweep.fixture";
import { describe, it, expect, vi } from "vitest";
import { writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { sweepOnce } from "../src/sweep.ts";
import type { DashboardConfig } from "@coderails/dashboard-lib";

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
    const runCodexImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config: inputAllowedConfig, runsDir, vaultNotesDir, runCodexImpl, notifyImpl,
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
    const runCodexImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config,
      runsDir: brokenRunsDir, vaultNotesDir, runCodexImpl, notifyImpl: vi.fn(),
    });
    // Both intents were claimed and the sweep did not crash despite every
    // appendRun call throwing.
    expect(result.claimed).toBe(2);
  });
});
