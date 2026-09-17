import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { mkdtempSync, rmSync, mkdirSync, writeFileSync, existsSync, utimesSync, statSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { sweepOnce, ORPHAN_THRESHOLD_MS } from "../src/sweep.ts";
import { readRuns } from "../src/runlog.ts";
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
    expect(runClaudeImpl).toHaveBeenCalledWith(
      expectedArgv,
      "/tmp",
      expect.objectContaining({ outputPath: expect.stringContaining(runsDir) })
    );
  });

  it("asserts real buildArgv output for a default (read-only) profile button", async () => {
    writeIntent("default-run", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    const runClaudeImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config, runsDir, vaultNotesDir, runClaudeImpl,
    });
    const expectedArgv = buildArgv(config.buttons[0], undefined);
    expect(runClaudeImpl).toHaveBeenCalledWith(
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
    const runClaudeImpl = vi.fn().mockResolvedValue({ exitCode: 0, stdout: "", stderr: "" });
    await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir, config: inputAllowedConfig, runsDir, vaultNotesDir, runClaudeImpl,
    });
    const expectedArgv = buildArgv(inputAllowedConfig.buttons[0], "some literal input");
    expect(runClaudeImpl).toHaveBeenCalledWith(
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

describe("sweepOnce gate date derivation (UTC/local skew)", () => {
  // The producer (the `claude -p` run) writes its artifact keyed to the
  // LOCAL calendar date. If sweepOnce derives the gate's {date} via
  // `new Date().toISOString()` — always UTC, regardless of process.env.TZ —
  // then at any instant where the local date is already ahead of the UTC
  // date, the gate looks for a date the producer never wrote and a correct
  // run is failed. Asia/Kolkata (UTC+5:30, no DST) makes this reproducible
  // with a single fixed instant: 2025-03-09T20:00:00Z is 2025-03-10 01:30
  // Kolkata-local — local has rolled over to the 10th while UTC is still
  // the 9th.
  //
  // The fixed instant is deliberately far in the past (not "today" in any
  // TZ this suite could run in) so a WALL-CLOCK-derived date can never
  // coincidentally equal the expected value here — a test that hardcodes a
  // date near the real current date would pass against the buggy
  // `new Date()` (wall clock) path purely by calendar coincidence, which is
  // exactly the tautology this test exists to rule out.
  //
  // process.env.TZ is deliberately NOT used to pin the expected "local"
  // value: it is process-global, mutating it only takes effect for Date
  // methods called AFTER the mutation, and this file's own describe-time
  // constants (or another suite file's ambient TZ state) run at a time this
  // block cannot control. Intl.DateTimeFormat's `timeZone` option computes a
  // specific zone's calendar date directly from the instant, independent of
  // process.env.TZ and independent of when this code runs relative to any
  // beforeEach — so it can safely live as a module-scope const.
  function dateInZone(date: Date, timeZone: string): string {
    return new Intl.DateTimeFormat("en-CA", {
      timeZone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(date); // en-CA formats as YYYY-MM-DD
  }

  const skewedInstant = new Date("2025-03-09T20:00:00Z");
  const localDate = dateInZone(skewedInstant, "Asia/Kolkata"); // "2025-03-10"
  const utcDate = skewedInstant.toISOString().slice(0, 10); // "2025-03-09" — always UTC

  const originalTZ = process.env.TZ;

  beforeEach(() => {
    // The FIX under test (localDateIso in sweep.ts) reads the OS/process
    // notion of "local" via getFullYear/getMonth/getDate, which follows
    // process.env.TZ — so the sweep still needs TZ set to Kolkata for its
    // own derivation to produce localDate. Only the TEST's *expected*
    // values (above) are independent of this; the production code under
    // test is not.
    process.env.TZ = "Asia/Kolkata";
  });

  afterEach(() => {
    if (originalTZ === undefined) delete process.env.TZ;
    else process.env.TZ = originalTZ;
  });

  it("resolves the gate's {date} to the producer's LOCAL calendar day, not UTC, at a local/UTC day-boundary skew", async () => {
    const artifactPath = join(root, "run-note.md");
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
            predicate: { kind: "contains", marker: "{date}" },
          },
          escalation: ["notification"],
        },
      ],
    };
    writeIntent("skew-run", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    const notifyImpl = vi.fn();
    const runClaudeImpl = vi.fn().mockImplementation(async () => {
      // Simulate the producer: it writes the artifact with the LOCAL date,
      // exactly like the real `claude -p` run does (verified: on-disk run
      // notes match their local mtime date).
      writeFileSync(artifactPath, `run note for ${localDate}`);
      return { exitCode: 0, stdout: "", stderr: "" };
    });

    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir,
      config: routineConfig, runsDir, vaultNotesDir, runClaudeImpl, notifyImpl,
      clock: () => skewedInstant,
    });

    // The gate must find the marker the producer actually wrote (the local
    // date). If sweepOnce instead derives {date} from the wall clock (bug
    // present), the marker it looks for is today's real UTC date — which
    // matches neither localDate nor utcDate above, since both are pinned to
    // 2025 — so the run fails for the WRONG reason (a false
    // artifact-gate-failed on a correct run).
    expect(result.succeeded).toBe(1);
    expect(result.failed).toBe(0);
    expect(notifyImpl).not.toHaveBeenCalled();
  });

  // Guards against over-correction (a gate that matches BOTH days), not against
  // the skew itself: the test above is the one that discriminates. This one
  // cannot fail against a UTC-deriving gate by construction — such a gate
  // resolves the wall clock's day, which matches neither pinned 2025 date, so
  // it fails to find the marker for the wrong reason and still satisfies the
  // assertions below.
  it("does NOT match the UTC-derived day when the producer wrote the local day (pins the failure direction)", async () => {
    const artifactPath = join(root, "run-note-utc-mismatch.md");
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
            predicate: { kind: "contains", marker: "{date}" },
          },
          escalation: ["notification"],
        },
      ],
    };
    writeIntent("skew-run-utc", { button: "wiki-lint", requestedAt: Date.now(), source: "cli" });
    const notifyImpl = vi.fn();
    const runClaudeImpl = vi.fn().mockImplementation(async () => {
      // The artifact contains ONLY the UTC-derived date string, never the
      // local one — if the gate (correctly) resolves {date} to localDate,
      // this marker must be absent and the run must fail.
      writeFileSync(artifactPath, `run note for ${utcDate}`);
      return { exitCode: 0, stdout: "", stderr: "" };
    });

    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir,
      config: routineConfig, runsDir, vaultNotesDir, runClaudeImpl, notifyImpl,
      clock: () => skewedInstant,
    });

    expect(result.succeeded).toBe(0);
    expect(result.failed).toBe(1);
    expect(notifyImpl).toHaveBeenCalledWith(expect.any(String), expect.stringContaining("artifact-gate-failed"));
  });
});
