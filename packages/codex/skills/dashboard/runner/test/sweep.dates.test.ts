import { root, queueDir, processingDir, archiveDir, quarantineDir, runsDir, vaultNotesDir, config, writeIntent } from "./sweep.fixture";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { sweepOnce } from "../src/sweep.ts";
import type { DashboardConfig } from "@coderails/dashboard-lib";

describe("sweepOnce gate date derivation (UTC/local skew)", () => {
  // The producer (the `codex exec` run) writes its artifact keyed to the
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
    const runCodexImpl = vi.fn().mockImplementation(async () => {
      // Simulate the producer: it writes the artifact with the LOCAL date,
      // exactly like the real `codex exec` run does (verified: on-disk run
      // notes match their local mtime date).
      writeFileSync(artifactPath, `run note for ${localDate}`);
      return { exitCode: 0, stdout: "", stderr: "" };
    });

    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir,
      config: routineConfig, runsDir, vaultNotesDir, runCodexImpl, notifyImpl,
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
    const runCodexImpl = vi.fn().mockImplementation(async () => {
      // The artifact contains ONLY the UTC-derived date string, never the
      // local one — if the gate (correctly) resolves {date} to localDate,
      // this marker must be absent and the run must fail.
      writeFileSync(artifactPath, `run note for ${utcDate}`);
      return { exitCode: 0, stdout: "", stderr: "" };
    });

    const result = await sweepOnce({
      queueDir, processingDir, archiveDir, quarantineDir,
      config: routineConfig, runsDir, vaultNotesDir, runCodexImpl, notifyImpl,
      clock: () => skewedInstant,
    });

    expect(result.succeeded).toBe(0);
    expect(result.failed).toBe(1);
    expect(notifyImpl).toHaveBeenCalledWith(expect.any(String), expect.stringContaining("artifact-gate-failed"));
  });
});
