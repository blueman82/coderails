import { queueDir, processingDir, archiveDir, quarantineDir, runsDir, vaultNotesDir, config } from "./sweep.fixture";
import { describe, it, expect, vi } from "vitest";
import { mkdirSync, writeFileSync, existsSync, utimesSync } from "node:fs";
import { join } from "node:path";
import { sweepOnce, ORPHAN_THRESHOLD_MS } from "../src/sweep.ts";

describe("sweepOnce orphan recovery (B3)", () => {
  it("recovers a stale file left in processing/ into quarantine with a synthetic run record and escalation", async () => {
    mkdirSync(processingDir, { recursive: true });
    writeFileSync(join(processingDir, "stale-run.json"), JSON.stringify({ button: "wiki-lint" }));
    const staleTime = new Date(Date.now() - ORPHAN_THRESHOLD_MS - 60_000);
    utimesSync(join(processingDir, "stale-run.json"), staleTime, staleTime);

    const notifyImpl = vi.fn();
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir,
      runCodexImpl: vi.fn(), notifyImpl,
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
      runCodexImpl: vi.fn(),
    });

    expect(existsSync(join(processingDir, "fresh-run.json"))).toBe(true);
    expect(existsSync(join(quarantineDir, "fresh-run.json"))).toBe(false);
  });
});
