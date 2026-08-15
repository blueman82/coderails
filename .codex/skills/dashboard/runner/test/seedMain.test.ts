import { describe, it, expect, vi } from "vitest";
import { run } from "../src/seedMain.ts";
import type { SeedResult } from "../src/seed.ts";
import type { DashboardConfig } from "@coderails/dashboard-lib";

const baseConfig: DashboardConfig = { repos: [], wikiPaths: [], buttons: [] };

function seedResult(overrides: Partial<SeedResult> = {}): SeedResult {
  return { seeded: 0, skippedNotDue: 0, skippedAlreadyQueued: 0, errored: 0, ...overrides };
}

describe("run (seedMain.ts) exit code semantics", () => {
  it("returns 0 for a clean seed pass with nothing due", async () => {
    const code = await run({
      loadConfigImpl: () => baseConfig,
      seedDueRoutinesImpl: vi.fn().mockReturnValue(seedResult()),
      log: vi.fn(),
    });
    expect(code).toBe(0);
  });

  it("returns 0 even when some routines seeded and some errored (seeding never blocks the sweep step)", async () => {
    const code = await run({
      loadConfigImpl: () => baseConfig,
      seedDueRoutinesImpl: vi.fn().mockReturnValue(seedResult({ seeded: 1, errored: 1 })),
      log: vi.fn(),
    });
    expect(code).toBe(0);
  });

  it("returns 2 when the seed step itself crashes, and attempts a last-resort notification", async () => {
    const notifyImpl = vi.fn();
    const code = await run({
      loadConfigImpl: () => baseConfig,
      seedDueRoutinesImpl: vi.fn().mockImplementation(() => {
        throw new Error("disk full");
      }),
      notifyImpl,
      log: vi.fn(),
      logError: vi.fn(),
    });
    expect(code).toBe(2);
    expect(notifyImpl).toHaveBeenCalledWith(expect.stringContaining("crashed"), expect.stringContaining("disk full"));
  });

  it("returns 2 when loadConfig itself throws, before seedDueRoutines is ever called", async () => {
    const seedDueRoutinesImpl = vi.fn();
    const code = await run({
      loadConfigImpl: () => {
        throw new Error("config parse error");
      },
      seedDueRoutinesImpl,
      notifyImpl: vi.fn(),
      log: vi.fn(),
      logError: vi.fn(),
    });
    expect(code).toBe(2);
    expect(seedDueRoutinesImpl).not.toHaveBeenCalled();
  });

  it("passes vaultNotesDir derived from wikiPaths[0] when present", async () => {
    const seedDueRoutinesImpl = vi.fn().mockReturnValue(seedResult());
    await run({
      loadConfigImpl: () => ({ ...baseConfig, wikiPaths: ["/my/vault"] }),
      seedDueRoutinesImpl,
      log: vi.fn(),
    });
    expect(seedDueRoutinesImpl).toHaveBeenCalledWith(
      expect.objectContaining({ vaultNotesDir: "/my/vault/dashboard-runs" })
    );
  });

  it("derives queue/processing/runs dirs from baseDir", async () => {
    const seedDueRoutinesImpl = vi.fn().mockReturnValue(seedResult());
    await run({
      baseDir: "/custom/base",
      loadConfigImpl: () => baseConfig,
      seedDueRoutinesImpl,
      log: vi.fn(),
    });
    expect(seedDueRoutinesImpl).toHaveBeenCalledWith(
      expect.objectContaining({
        queueDir: "/custom/base/queue",
        processingDir: "/custom/base/processing",
        runsDir: "/custom/base/runs",
      })
    );
  });

  it("logs the seed summary line", async () => {
    const log = vi.fn();
    await run({
      loadConfigImpl: () => baseConfig,
      seedDueRoutinesImpl: vi.fn().mockReturnValue(
        seedResult({ seeded: 2, skippedNotDue: 1, skippedAlreadyQueued: 1, errored: 1 })
      ),
      log,
    });
    expect(log).toHaveBeenCalledWith(expect.stringContaining("2 seeded"));
    expect(log).toHaveBeenCalledWith(expect.stringContaining("1 not due"));
    expect(log).toHaveBeenCalledWith(expect.stringContaining("1 already queued"));
    expect(log).toHaveBeenCalledWith(expect.stringContaining("1 errored"));
  });
});
