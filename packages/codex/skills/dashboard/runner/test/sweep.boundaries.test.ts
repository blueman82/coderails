import { root, queueDir, processingDir, archiveDir, quarantineDir, runsDir, vaultNotesDir, config, writeIntent } from "./sweep.fixture";
import { describe, it, expect, vi } from "vitest";
import { rmSync, mkdirSync, writeFileSync, existsSync, utimesSync, statSync } from "node:fs";
import { join } from "node:path";
import { sweepOnce } from "../src/sweep.ts";
import { buildArgv } from "../../app/src/lib/argv.ts";
import type { DashboardConfig } from "@coderails/dashboard-lib";

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
        runCodexImpl: vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" }),
      }),
      sweepOnce({
        queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir,
        runCodexImpl: vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" }),
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

  it("asserts real buildArgv output is what a workspace-write auto-profile button produces end to end", async () => {
    const autoConfig: DashboardConfig = {
      ...config,
      buttons: [{ name: "auto-btn", label: "AUTO", command: "$coderails-codex:docs-sync", cwd: "/tmp", profile: "auto" }],
    };
    writeIntent("auto-run", { button: "auto-btn", requestedAt: Date.now(), source: "cli" });
    const runCodexImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config: autoConfig, runsDir, vaultNotesDir, runCodexImpl,
    });
    const expectedArgv = buildArgv(autoConfig.buttons[0], undefined);
    expect(runCodexImpl).toHaveBeenCalledWith(
      expectedArgv,
      "/tmp",
      expect.objectContaining({ outputPath: expect.stringContaining(runsDir) })
    );
  });

  it("asserts real buildArgv output for a default (read-only) profile button", async () => {
    writeIntent("default-run", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    const runCodexImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir, runCodexImpl,
    });
    const expectedArgv = buildArgv(config.buttons[0], undefined);
    expect(runCodexImpl).toHaveBeenCalledWith(
      expectedArgv,
      "/tmp",
      expect.objectContaining({ outputPath: expect.stringContaining(runsDir) })
    );
  });

  it("asserts real buildArgv output for an input-bearing button", async () => {
    // inputAllowed: true — required for input to reach buildArgv at all
    // (the inputAllowed authorization check above).
    const inputAllowedConfig: DashboardConfig = {
      ...config,
      buttons: [{ name: "wiki-lint", label: "WIKI LINT", command: "/coderails:wiki-lint", cwd: "/tmp", profile: "read-only", inputAllowed: true }],
    };
    writeIntent("input-run", { button: "wiki-lint", input: "some literal input", requestedAt: Date.now(), source: "cli" });
    const runCodexImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config: inputAllowedConfig, runsDir, vaultNotesDir, runCodexImpl,
    });
    const expectedArgv = buildArgv(inputAllowedConfig.buttons[0], "some literal input");
    expect(runCodexImpl).toHaveBeenCalledWith(
      expectedArgv,
      "/tmp",
      expect.objectContaining({ outputPath: expect.stringContaining(runsDir) })
    );
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
    const runCodexImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir,
      config: routineConfig, runsDir, vaultNotesDir, runCodexImpl, notifyImpl,
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
    const runCodexImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir,
      config: routineConfig, runsDir, vaultNotesDir, runCodexImpl, notifyImpl: vi.fn(),
    });
    expect(result.succeeded).toBe(1);
  });

  it("returns claimed: 0 and does not throw when queueDir is missing entirely", async () => {
    rmSync(queueDir, { recursive: true, force: true });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir, runCodexImpl: vi.fn(),
    });
    expect(result.claimed).toBe(0);
  });

  it("counts a quarantined malformed intent toward result.claimed", async () => {
    writeIntent("bad-claimed", { button: 42 });
    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir, runCodexImpl: vi.fn(),
    });
    expect(result.claimed).toBe(1);
    expect(result.quarantined).toBe(1);
  });
});
