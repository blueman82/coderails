import { describe, it, expect, vi } from "vitest";
import { run } from "../src/main.ts";
import type { SweepResult } from "../src/sweep.ts";
import type { DashboardConfig } from "@coderails/dashboard-lib";

const baseConfig: DashboardConfig = { repos: [], wikiPaths: [], memoryPaths: [], buttons: [] };

function sweepResult(overrides: Partial<SweepResult> = {}): SweepResult {
  return { claimed: 0, succeeded: 0, failed: 0, quarantined: 0, ...overrides };
}

describe("run (main.ts) exit code semantics (B5)", () => {
  it("returns 0 for a clean sweep with no failures", async () => {
    const code = await run({
      loadConfigImpl: () => baseConfig,
      sweepOnceImpl: vi.fn().mockResolvedValue(sweepResult({ claimed: 2, succeeded: 2 })),
      log: vi.fn(),
    });
    expect(code).toBe(0);
  });

  it("returns 1 when result.failed > 0", async () => {
    const code = await run({
      loadConfigImpl: () => baseConfig,
      sweepOnceImpl: vi.fn().mockResolvedValue(sweepResult({ claimed: 2, succeeded: 1, failed: 1 })),
      log: vi.fn(),
    });
    expect(code).toBe(1);
  });

  it("returns 2 when the sweeper itself crashes (sweepOnce throws), and attempts a last-resort notification", async () => {
    const notifyImpl = vi.fn();
    const code = await run({
      loadConfigImpl: () => baseConfig,
      sweepOnceImpl: vi.fn().mockRejectedValue(new Error("disk full")),
      notifyImpl,
      log: vi.fn(),
      logError: vi.fn(),
    });
    expect(code).toBe(2);
    expect(notifyImpl).toHaveBeenCalledWith(expect.stringContaining("crashed"), expect.stringContaining("disk full"));
  });

  it("returns 2 when loadConfig itself throws, before sweepOnce is ever called", async () => {
    const sweepOnceImpl = vi.fn();
    const code = await run({
      loadConfigImpl: () => {
        throw new Error("config parse error");
      },
      sweepOnceImpl,
      notifyImpl: vi.fn(),
      log: vi.fn(),
      logError: vi.fn(),
    });
    expect(code).toBe(2);
    expect(sweepOnceImpl).not.toHaveBeenCalled();
  });

  it("still returns 2 (does not throw out of run()) when the crash notification itself also throws", async () => {
    const code = await run({
      loadConfigImpl: () => baseConfig,
      sweepOnceImpl: vi.fn().mockRejectedValue(new Error("boom")),
      notifyImpl: vi.fn(() => {
        throw new Error("notification channel also down");
      }),
      log: vi.fn(),
      logError: vi.fn(),
    });
    expect(code).toBe(2);
  });

  it("passes vaultNotesDir derived from wikiPaths[0] when present", async () => {
    const sweepOnceImpl = vi.fn().mockResolvedValue(sweepResult());
    await run({
      loadConfigImpl: () => ({ ...baseConfig, wikiPaths: ["/my/vault"] }),
      sweepOnceImpl,
      log: vi.fn(),
    });
    expect(sweepOnceImpl).toHaveBeenCalledWith(
      expect.objectContaining({ vaultNotesDir: "/my/vault/dashboard-runs" })
    );
  });

  it("passes vaultNotesDir: undefined when wikiPaths is empty", async () => {
    const sweepOnceImpl = vi.fn().mockResolvedValue(sweepResult());
    await run({
      loadConfigImpl: () => ({ ...baseConfig, wikiPaths: [] }),
      sweepOnceImpl,
      log: vi.fn(),
    });
    expect(sweepOnceImpl).toHaveBeenCalledWith(expect.objectContaining({ vaultNotesDir: undefined }));
  });

  it("derives queue/processing/archive/quarantine/runs dirs from baseDir", async () => {
    const sweepOnceImpl = vi.fn().mockResolvedValue(sweepResult());
    await run({
      baseDir: "/custom/base",
      loadConfigImpl: () => baseConfig,
      sweepOnceImpl,
      log: vi.fn(),
    });
    expect(sweepOnceImpl).toHaveBeenCalledWith(
      expect.objectContaining({
        queueDir: "/custom/base/queue",
        processingDir: "/custom/base/processing",
        archiveDir: "/custom/base/archive",
        quarantineDir: "/custom/base/quarantine",
        runsDir: "/custom/base/runs",
      })
    );
  });

  it("logs the sweep summary line on a clean run", async () => {
    const log = vi.fn();
    await run({
      loadConfigImpl: () => baseConfig,
      sweepOnceImpl: vi.fn().mockResolvedValue(sweepResult({ claimed: 3, succeeded: 2, failed: 1, quarantined: 1 })),
      log,
    });
    expect(log).toHaveBeenCalledWith(expect.stringContaining("3 claimed"));
    expect(log).toHaveBeenCalledWith(expect.stringContaining("2 succeeded"));
    expect(log).toHaveBeenCalledWith(expect.stringContaining("1 failed"));
    expect(log).toHaveBeenCalledWith(expect.stringContaining("1 quarantined"));
  });
});
