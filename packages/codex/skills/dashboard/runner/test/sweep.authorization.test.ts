import { queueDir, processingDir, archiveDir, quarantineDir, runsDir, vaultNotesDir, config, writeIntent } from "./sweep.fixture";
import { describe, it, expect, vi } from "vitest";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { sweepOnce } from "../src/sweep.ts";
import type { DashboardConfig } from "@coderails/dashboard-lib";

describe("sweepOnce inputAllowed authorization (queue path)", () => {
  it("quarantines an intent carrying input against an inputAllowed:false button, and never spawns", async () => {
    const noInputConfig: DashboardConfig = {
      ...config,
      buttons: [{ name: "wiki-lint", label: "WIKI LINT", command: "/coderails:wiki-lint", cwd: "/tmp", profile: "read-only" }],
    };
    writeIntent("unauthorized-input", { button: "wiki-lint", input: "arbitrary prompt", requestedAt: Date.now(), source: "cli" });
    const runCodexImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config: noInputConfig, runsDir, vaultNotesDir, runCodexImpl,
    });
    expect(result.quarantined).toBe(1);
    expect(existsSync(join(quarantineDir, "unauthorized-input.json"))).toBe(true);
    expect(runCodexImpl).not.toHaveBeenCalled();
  });

  it("still runs normally when input is carried against an inputAllowed:true button", async () => {
    const inputAllowedConfig: DashboardConfig = {
      ...config,
      buttons: [{ name: "with-input", label: "WITH INPUT", command: "/coderails:assumptions", cwd: "/tmp", profile: "read-only", inputAllowed: true }],
    };
    writeIntent("allowed-input", { button: "with-input", input: "hello", requestedAt: Date.now(), source: "cli" });
    const runCodexImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config: inputAllowedConfig, runsDir, vaultNotesDir, runCodexImpl,
    });
    expect(result.quarantined).toBe(0);
    expect(result.succeeded).toBe(1);
    expect(runCodexImpl).toHaveBeenCalled();
  });

  it("still runs normally when an intent with no input targets an inputAllowed:false button", async () => {
    const noInputConfig: DashboardConfig = {
      ...config,
      buttons: [{ name: "wiki-lint", label: "WIKI LINT", command: "/coderails:wiki-lint", cwd: "/tmp", profile: "read-only" }],
    };
    writeIntent("no-input", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    const runCodexImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config: noInputConfig, runsDir, vaultNotesDir, runCodexImpl,
    });
    expect(result.quarantined).toBe(0);
    expect(result.succeeded).toBe(1);
    expect(runCodexImpl).toHaveBeenCalled();
  });
});
