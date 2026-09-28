import { queueDir, processingDir, archiveDir, quarantineDir, runsDir, vaultNotesDir, config, writeIntent } from "./sweep.fixture";
import { describe, it, expect, vi } from "vitest";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { sweepOnce } from "../src/sweep.ts";
import { readRuns } from "../src/runlog.ts";

describe("sweepOnce", () => {
  it("claims a well-formed intent by moving it from queue to processing, then to archive on success", async () => {
    writeIntent("run1", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    const runCodexImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir, runCodexImpl,
    });
    expect(result.claimed).toBe(1);
    expect(existsSync(join(queueDir, "run1.json"))).toBe(false);
    expect(existsSync(join(processingDir, "run1.json"))).toBe(false);
    expect(existsSync(join(archiveDir, "run1.json"))).toBe(true);
    // Pin the EXACT path, not merely one under runsDir: the invariant this
    // feature depends on is that the transcript lands where the ledger says
    // it does. stringContaining(runsDir) alone still passes when the
    // persisted filename is decoupled from startRecord.outputPath, which is
    // precisely the "RED routine with no findable transcript" failure the
    // feature exists to prevent.
    const ledgerRec = readRuns(10, { runsDir }).find((r) => r.outputPath);
    const ledgerPath = ledgerRec?.outputPath;
    expect(ledgerPath).toBe(join(runsDir, `${ledgerRec?.runId}.log`));
    expect(runCodexImpl).toHaveBeenCalledWith(
      [
        "--sandbox",
        "read-only",
        "This is an unattended, headless run with no human watching output in real time. Do not address a human or end your final text with a question. Write findings only to whatever report or artifact file the invoked skill specifies. $coderails-codex:wiki-lint",
      ],
      "/tmp",
      expect.objectContaining({ outputPath: ledgerPath })
    );
  });

  it("moves a malformed intent to quarantine and continues the sweep", async () => {
    writeIntent("bad1", { button: 42 }); // fails parseIntent
    writeIntent("run2", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    const runCodexImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir, runCodexImpl,
    });
    expect(result.quarantined).toBe(1);
    expect(existsSync(join(quarantineDir, "bad1.json"))).toBe(true);
    expect(existsSync(join(archiveDir, "run2.json"))).toBe(true);
  });

  it("quarantines an intent whose button name matches no ButtonDef", async () => {
    writeIntent("run3", { button: "does-not-exist", requestedAt: Date.now(), source: "cli" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir,
      runCodexImpl: vi.fn(),
    });
    expect(result.quarantined).toBe(1);
    expect(existsSync(join(quarantineDir, "run3.json"))).toBe(true);
  });

  it("records a JSONL run entry for a claimed intent", async () => {
    writeIntent("run4", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    const runCodexImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    await sweepOnce({ queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir, runCodexImpl });
    const { readRuns } = await import("../src/runlog.ts");
    const runs = readRuns(10, { runsDir });
    expect(runs).toHaveLength(1);
    expect(runs[0].button).toBe("wiki-lint");
    expect(runs[0].exitCode).toBe(0);
  });

  it("returns claimed: 0 when the queue is empty", async () => {
    const result = await sweepOnce({ queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir, runCodexImpl: vi.fn() });
    expect(result.claimed).toBe(0);
  });

  it("processes multiple queued intents in one sweep", async () => {
    writeIntent("run5", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    writeIntent("run6", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    const runCodexImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({ queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir, runCodexImpl });
    expect(result.claimed).toBe(2);
    expect(result.succeeded).toBe(2);
  });
});
