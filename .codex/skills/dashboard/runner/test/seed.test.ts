import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { mkdtempSync, rmSync, mkdirSync, writeFileSync, readFileSync, readdirSync, existsSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { seedDueRoutines } from "../src/seed.ts";
import { appendRun, type RunRecord } from "../src/runlog.ts";
import type { DashboardConfig, RoutineDef } from "@coderails/dashboard-lib";

let root: string, queueDir: string, processingDir: string, runsDir: string;

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "seed-test-"));
  queueDir = join(root, "queue");
  processingDir = join(root, "processing");
  runsDir = join(root, "runs");
});

afterEach(() => {
  rmSync(root, { recursive: true, force: true });
});

const NIGHTLY: RoutineDef = {
  name: "wiki-lint-nightly",
  buttonRef: "wiki-lint",
  cadence: "nightly",
  expectedArtifact: { artifactPath: "{vault}/log.md", maxAgeSeconds: 129600, predicate: { kind: "exists" } },
  escalation: ["notification", "vault-note"],
};

const WEEKLY: RoutineDef = {
  name: "sync-docs-weekly",
  skillCommand: "/sync-docs",
  cadence: "weekly",
  expectedArtifact: { artifactPath: "/tmp/report.md", maxAgeSeconds: 691200, predicate: { kind: "exists" } },
  escalation: ["notification", "vault-note"],
};

function config(routines: RoutineDef[]): DashboardConfig {
  return {
    repos: [], wikiPaths: [],
    buttons: [
      { name: "wiki-lint", label: "WIKI LINT", command: "/coderails:wiki-lint", cwd: "/tmp", profile: "read-only" },
      { name: "sync-docs-weekly", label: "SYNC DOCS", command: "/sync-docs", cwd: "/tmp", profile: "read-only" },
    ],
    routines,
  };
}

function record(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    runId: "prior1",
    button: "wiki-lint",
    argv: [],
    cwd: "/tmp",
    profile: "read-only",
    startedAt: Date.now(),
    outputPath: "",
    ...overrides,
  };
}

function queuedButtonNames(dir: string): string[] {
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((f) => f.endsWith(".json"))
    .map((f) => JSON.parse(readFileSync(join(dir, f), "utf-8")).button as string);
}

describe("seedDueRoutines", () => {
  it("seeds an intent for a routine with no prior run at all (always due)", () => {
    const result = seedDueRoutines({ queueDir, processingDir, config: config([NIGHTLY]), runsDir });
    expect(result.seeded).toBe(1);
    expect(queuedButtonNames(queueDir)).toEqual(["wiki-lint"]);
  });

  it("writes an intent matching the lib's Intent shape, with source 'scheduler'", () => {
    seedDueRoutines({ queueDir, processingDir, config: config([NIGHTLY]), runsDir });
    const files = readdirSync(queueDir).filter((f) => f.endsWith(".json"));
    expect(files).toHaveLength(1);
    const intent = JSON.parse(readFileSync(join(queueDir, files[0]), "utf-8"));
    expect(intent.button).toBe("wiki-lint");
    expect(intent.source).toBe("scheduler");
    expect(typeof intent.requestedAt).toBe("number");
  });

  it("does not seed a nightly routine whose last run started under 20h ago", () => {
    appendRun(record({ button: "wiki-lint", startedAt: Date.now() - 60 * 60 * 1000 }), { runsDir }); // 1h ago
    const result = seedDueRoutines({ queueDir, processingDir, config: config([NIGHTLY]), runsDir });
    expect(result.seeded).toBe(0);
    expect(result.skippedNotDue).toBe(1);
  });

  it("seeds a nightly routine whose last run started 21h ago", () => {
    appendRun(record({ button: "wiki-lint", startedAt: Date.now() - 21 * 60 * 60 * 1000 }), { runsDir });
    const result = seedDueRoutines({ queueDir, processingDir, config: config([NIGHTLY]), runsDir });
    expect(result.seeded).toBe(1);
  });

  it("does not seed a weekly routine whose last run started 2 days ago", () => {
    appendRun(record({ button: "sync-docs-weekly", startedAt: Date.now() - 2 * 24 * 60 * 60 * 1000 }), { runsDir });
    const result = seedDueRoutines({ queueDir, processingDir, config: config([WEEKLY]), runsDir });
    expect(result.seeded).toBe(0);
    expect(result.skippedNotDue).toBe(1);
  });

  it("seeds a weekly routine whose last run started 7 days ago", () => {
    appendRun(record({ button: "sync-docs-weekly", startedAt: Date.now() - 7 * 24 * 60 * 60 * 1000 }), { runsDir });
    const result = seedDueRoutines({ queueDir, processingDir, config: config([WEEKLY]), runsDir });
    expect(result.seeded).toBe(1);
  });

  it("is idempotent: does not seed twice if an intent for the button is already queued", () => {
    mkdirSync(queueDir, { recursive: true });
    writeFileSync(join(queueDir, "existing.json"), JSON.stringify({ button: "wiki-lint", requestedAt: Date.now(), source: "scheduler" }));
    const result = seedDueRoutines({ queueDir, processingDir, config: config([NIGHTLY]), runsDir });
    expect(result.seeded).toBe(0);
    expect(result.skippedAlreadyQueued).toBe(1);
    expect(readdirSync(queueDir).filter((f) => f.endsWith(".json"))).toHaveLength(1);
  });

  it("is idempotent: does not seed if an intent for the button is already claimed (in processing/)", () => {
    mkdirSync(processingDir, { recursive: true });
    writeFileSync(join(processingDir, "claimed.json"), JSON.stringify({ button: "wiki-lint", requestedAt: Date.now(), source: "scheduler" }));
    const result = seedDueRoutines({ queueDir, processingDir, config: config([NIGHTLY]), runsDir });
    expect(result.seeded).toBe(0);
    expect(result.skippedAlreadyQueued).toBe(1);
  });

  it("escalates once and skips, without crashing, on an unrecognised cadence value", () => {
    const badRoutine: RoutineDef = { ...NIGHTLY, name: "bad-cadence", cadence: "0 3 * * *" };
    const notifyImpl = vi.fn();
    const result = seedDueRoutines({ queueDir, processingDir, config: config([badRoutine]), runsDir, notifyImpl });
    expect(result.errored).toBe(1);
    expect(result.seeded).toBe(0);
    expect(notifyImpl).toHaveBeenCalledWith(expect.any(String), expect.stringContaining("cadence"));
    expect(queuedButtonNames(queueDir)).toEqual([]);
  });

  it("escalates once and skips, without crashing, when a routine's button cannot be resolved", () => {
    const orphan: RoutineDef = { ...NIGHTLY, name: "orphan-routine", buttonRef: "does-not-exist" };
    const notifyImpl = vi.fn();
    const result = seedDueRoutines({ queueDir, processingDir, config: config([orphan]), runsDir, notifyImpl });
    expect(result.errored).toBe(1);
    expect(result.seeded).toBe(0);
    expect(notifyImpl).toHaveBeenCalledWith(expect.any(String), expect.stringContaining("orphan-routine"));
  });

  it("resolves a routine with no buttonRef by matching a ButtonDef whose name equals the routine's own name", () => {
    const selfNamed: RoutineDef = { ...WEEKLY }; // name "sync-docs-weekly" matches a ButtonDef of the same name
    const result = seedDueRoutines({ queueDir, processingDir, config: config([selfNamed]), runsDir });
    expect(result.seeded).toBe(1);
    expect(queuedButtonNames(queueDir)).toEqual(["sync-docs-weekly"]);
  });

  it("processes multiple routines independently: one due, one not due, one broken", () => {
    appendRun(record({ button: "sync-docs-weekly", startedAt: Date.now() - 60 * 60 * 1000 }), { runsDir }); // 1h ago, not due
    const badRoutine: RoutineDef = { ...NIGHTLY, name: "bad-one", buttonRef: "does-not-exist" };
    const result = seedDueRoutines({
      queueDir, processingDir,
      config: config([NIGHTLY, WEEKLY, badRoutine]), // NIGHTLY has no prior run -> due
      runsDir,
      notifyImpl: vi.fn(),
    });
    expect(result.seeded).toBe(1);
    expect(result.skippedNotDue).toBe(1);
    expect(result.errored).toBe(1);
  });

  it("creates the queue directory with 0o700 mode if it does not exist", () => {
    const result = seedDueRoutines({ queueDir, processingDir, config: config([NIGHTLY]), runsDir });
    expect(result.seeded).toBe(1);
    expect(existsSync(queueDir)).toBe(true);
    expect(statSync(queueDir).mode & 0o777).toBe(0o700);
  });

  it("returns all-zero result when the config has no routines", () => {
    const result = seedDueRoutines({ queueDir, processingDir, config: config([]), runsDir });
    expect(result).toEqual({ seeded: 0, skippedNotDue: 0, skippedAlreadyQueued: 0, errored: 0 });
  });
});

describe("seedDueRoutines due-ness boundaries (I1)", () => {
  it("does not seed a nightly routine exactly one second under the 20h threshold", () => {
    const now = Date.now();
    appendRun(record({ button: "wiki-lint", startedAt: now - (20 * 60 * 60 * 1000 - 1000) }), { runsDir });
    const result = seedDueRoutines({ queueDir, processingDir, config: config([NIGHTLY]), runsDir, nowImpl: () => now });
    expect(result.seeded).toBe(0);
    expect(result.skippedNotDue).toBe(1);
  });

  it("seeds a nightly routine exactly at the 20h threshold", () => {
    const now = Date.now();
    appendRun(record({ button: "wiki-lint", startedAt: now - 20 * 60 * 60 * 1000 }), { runsDir });
    const result = seedDueRoutines({ queueDir, processingDir, config: config([NIGHTLY]), runsDir, nowImpl: () => now });
    expect(result.seeded).toBe(1);
  });

  it("does not seed a weekly routine exactly one second under the 6.5-day threshold", () => {
    const now = Date.now();
    appendRun(record({ button: "sync-docs-weekly", startedAt: now - (6.5 * 24 * 60 * 60 * 1000 - 1000) }), { runsDir });
    const result = seedDueRoutines({ queueDir, processingDir, config: config([WEEKLY]), runsDir, nowImpl: () => now });
    expect(result.seeded).toBe(0);
    expect(result.skippedNotDue).toBe(1);
  });

  it("seeds a weekly routine exactly at the 6.5-day threshold", () => {
    const now = Date.now();
    appendRun(record({ button: "sync-docs-weekly", startedAt: now - 6.5 * 24 * 60 * 60 * 1000 }), { runsDir });
    const result = seedDueRoutines({ queueDir, processingDir, config: config([WEEKLY]), runsDir, nowImpl: () => now });
    expect(result.seeded).toBe(1);
  });
});

describe("seedDueRoutines clock skew (I2)", () => {
  it("seeds a routine whose last run's startedAt is in the future (clock skew) instead of wedging it forever", () => {
    const now = Date.now();
    // A future startedAt can happen from clock skew across machines/VMs, or
    // a corrected system clock jumping backward after a run was recorded.
    // A naive `elapsed >= threshold` check computes a large negative number
    // here, which is never >= a positive threshold — the routine would
    // never be considered due again without manual intervention.
    appendRun(record({ button: "wiki-lint", startedAt: now + 60 * 60 * 1000 }), { runsDir }); // 1h in the future
    const result = seedDueRoutines({ queueDir, processingDir, config: config([NIGHTLY]), runsDir, nowImpl: () => now });
    expect(result.seeded).toBe(1);
  });
});

describe("seedDueRoutines runlog scoping (I3)", () => {
  it("treats a routine as never-run (due) when runs.jsonl only contains other buttons' records", () => {
    const now = Date.now();
    appendRun(record({ button: "sync-docs-weekly", startedAt: now - 60 * 1000 }), { runsDir }); // recent, but a different button
    const result = seedDueRoutines({ queueDir, processingDir, config: config([NIGHTLY]), runsDir, nowImpl: () => now });
    expect(result.seeded).toBe(1);
    expect(queuedButtonNames(queueDir)).toEqual(["wiki-lint"]);
  });
});

describe("seedDueRoutines escalation vault-note wiring (I7)", () => {
  it("writes a vault note when a seed-time escalation fires and vaultNotesDir is set", () => {
    const vaultNotesDir = join(root, "dashboard-runs");
    const badRoutine: RoutineDef = { ...NIGHTLY, name: "bad-cadence-vault", cadence: "0 3 * * *" };
    const result = seedDueRoutines({
      queueDir, processingDir, config: config([badRoutine]), runsDir, vaultNotesDir, notifyImpl: vi.fn(),
    });
    expect(result.errored).toBe(1);
    const notePath = join(vaultNotesDir, "bad-cadence-vault.md");
    expect(existsSync(notePath)).toBe(true);
    const note = readFileSync(notePath, "utf-8");
    expect(note).toContain("status: red");
    expect(note).toContain("runner-error");
  });
});
