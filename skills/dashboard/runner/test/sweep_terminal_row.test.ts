import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { mkdtempSync, rmSync, mkdirSync, writeFileSync, existsSync, readFileSync, appendFileSync, chmodSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { sweepOnce } from "../src/sweep.ts";
import { ensureTerminalRow } from "../src/timeoutMarker.ts";
import type { DashboardConfig } from "@coderails/dashboard-lib";

let root: string, queueDir: string, processingDir: string, archiveDir: string, quarantineDir: string, runsDir: string;

beforeEach(() => {
  root = mkdtempSync(join(tmpdir(), "sweep-terminal-"));
  queueDir = join(root, "queue");
  processingDir = join(root, "processing");
  archiveDir = join(root, "archive");
  quarantineDir = join(root, "quarantine");
  runsDir = join(root, "runs");
  mkdirSync(queueDir, { recursive: true });
});
afterEach(() => {
  vi.useRealTimers();
  rmSync(root, { recursive: true, force: true });
});

const clock = () => new Date("2026-07-23T20:00:00Z");
const human = () => join(root, "run-2026-07-23.log");
const jsonl = () => join(root, "run-2026-07-23.jsonl");

function configFor(): DashboardConfig {
  return {
    repos: [],
    wikiPaths: [],
    buttons: [{ name: "docs-sync", label: "DS", command: "/coderails:docs-sync", cwd: "/tmp", profile: "read-only" }],
    routines: [
      {
        name: "docs-sync",
        skillCommand: "/coderails:docs-sync",
        cadence: "0 3 * * *",
        expectedArtifact: {
          artifactPath: join(root, "run-{date}.log"),
          maxAgeSeconds: 3600,
          predicate: { kind: "last-marker", success: "run=ok", failures: ["abort=", "refused="] },
        },
        escalation: ["notification"],
      },
    ],
  };
}

function row(runId: string, outcome: string, reason = ""): string {
  const fields = { v: 1, ts: new Date().toISOString(), run_id: runId, routine: "docs-sync", stage: "x", outcome, reason_code: reason };
  return JSON.stringify(fields) + "\n";
}

async function sweepWith(child: () => void, exitCode = 0) {
  writeFileSync(join(queueDir, "r.json"), JSON.stringify({ button: "docs-sync", requestedAt: Date.now(), source: "cli" }));
  const notifyImpl = vi.fn();
  const runClaudeImpl = vi.fn().mockImplementation(async () => {
    child();
    return { exitCode, stdout: "", stderr: "" };
  });
  const result = await sweepOnce({
    queueDir, processingDir, archiveDir, quarantineDir, config: configFor(), runsDir, runClaudeImpl, notifyImpl, clock,
  });
  return { result, notifyImpl };
}

const rowsOf = () => readFileSync(jsonl(), "utf-8").trim().split("\n").map((l) => JSON.parse(l));

describe("runner terminal-row check after a routine child exits", () => {
  it("cannot reuse an earlier success from the same timestamp second", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-07-23T20:00:00.750Z"));
    const previous = JSON.parse(row("previous", "run_ok"));
    previous.ts = "2026-07-23T20:00:00Z";
    writeFileSync(jsonl(), JSON.stringify(previous) + "\n");
    writeFileSync(human(), "2026-07-23T20:00:00Z run=ok\n");
    const { result } = await sweepWith(() => {});
    expect(result).toMatchObject({ succeeded: 0, failed: 1 });
    expect(rowsOf().map((r) => r.outcome)).toEqual(["run_ok", "run_abort"]);
    expect(rowsOf()[1].run_id).not.toBe("previous");
  });

  it("fails closed when the child leaves unreadable JSONL and an old green human log", async () => {
    writeFileSync(human(), "2026-07-23T20:00:00Z run=ok\n");
    const { result, notifyImpl } = await sweepWith(() => mkdirSync(jsonl()));
    expect(result).toMatchObject({ succeeded: 0, failed: 1 });
    expect(notifyImpl).toHaveBeenCalled();
  });

  it("fails closed when appending the fallback abort is refused", async () => {
    writeFileSync(human(), "2026-07-23T20:00:00Z run=ok\n");
    const { result, notifyImpl } = await sweepWith(() => {
      appendFileSync(jsonl(), row("current", "run_incomplete", "incomplete-run"));
      chmodSync(jsonl(), 0o444);
    });
    expect(result).toMatchObject({ succeeded: 0, failed: 1 });
    expect(notifyImpl).toHaveBeenCalled();
  });

  it("returns explicit failed evidence when reading the event log fails", () => {
    mkdirSync(jsonl());
    const result = ensureTerminalRow(configFor().routines![0], { date: "2026-07-23", runId: "runner", vault: "" }, Buffer.alloc(0));
    expect(result).toMatchObject({ passed: false });
  });

  it("accepts newly appended success after a prior success in the same second", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-07-23T20:00:00.750Z"));
    writeFileSync(jsonl(), row("previous", "run_ok"));
    writeFileSync(human(), "2026-07-23T20:00:00Z run=ok\n");
    const { result } = await sweepWith(() => {
      const terminal = JSON.parse(row("current", "run_ok"));
      terminal.ts = "2026-07-23T20:00:00Z";
      appendFileSync(jsonl(), row("current", "run_incomplete", "incomplete-run") + JSON.stringify(terminal) + "\n");
      appendFileSync(human(), "2026-07-23T20:00:00Z run=ok\n");
    });
    expect(result).toMatchObject({ succeeded: 1, failed: 0 });
    expect(rowsOf().map((r) => r.run_id)).toEqual(["previous", "current", "current"]);
  });

  it("refuses a replaced event-log prefix even when the replacement claims success", async () => {
    writeFileSync(jsonl(), row("previous", "run_ok"));
    writeFileSync(human(), "2026-07-23T20:00:00Z run=ok\n");
    const { result, notifyImpl } = await sweepWith(() => writeFileSync(jsonl(), row("replacement", "run_ok")));
    expect(result).toMatchObject({ succeeded: 0, failed: 1 });
    expect(notifyImpl).toHaveBeenCalledWith(expect.any(String), expect.stringContaining("routine_log_changed"));
  });

  it("records a current abort after an early nonzero child exit", async () => {
    writeFileSync(jsonl(), row("previous", "run_ok"));
    writeFileSync(human(), "2026-07-23T20:00:00Z run=ok\n");
    const { result } = await sweepWith(() => {
      appendFileSync(jsonl(), row("current", "run_incomplete", "incomplete-run"));
    }, 1);
    expect(result).toMatchObject({ succeeded: 0, failed: 1 });
    expect(rowsOf().at(-1)).toMatchObject({ run_id: "current", outcome: "run_abort" });
  });

  it.each(["run_abort", "run_refused"])("rejects a newly appended %s despite an old green human log", async (outcome) => {
    writeFileSync(human(), "2026-07-23T20:00:00Z run=ok\n");
    const { result } = await sweepWith(() => appendFileSync(jsonl(), row("current", outcome, "merge")));
    expect(result).toMatchObject({ succeeded: 0, failed: 1 });
    expect(rowsOf().map((r) => r.outcome)).toEqual([outcome]);
  });

  it("appends run_abort runner_exit_no_terminal when exit 0 left no JSONL at all", async () => {
    const { result, notifyImpl } = await sweepWith(() => {});
    expect(rowsOf().map((r) => [r.outcome, r.reason_code])).toEqual([["run_abort", "runner_exit_no_terminal"]]);
    expect(readFileSync(human(), "utf-8")).toContain("abort=runner_exit_no_terminal");
    expect(result.failed).toBe(1);
    expect(notifyImpl).toHaveBeenCalled();
  });

  it("appends it under the run id of a standing run_incomplete row", async () => {
    await sweepWith(() => appendFileSync(jsonl(), row("abc123", "run_incomplete", "incomplete-run")));
    const rows = rowsOf();
    expect(rows.map((r) => r.outcome)).toEqual(["run_incomplete", "run_abort"]);
    expect(rows[1].run_id).toBe("abc123");
  });

  it("writes nothing when the run already has a terminal row", async () => {
    const { result } = await sweepWith(() => {
      appendFileSync(jsonl(), row("abc123", "run_incomplete", "incomplete-run") + row("abc123", "run_ok"));
      appendFileSync(human(), "2026-07-23T20:00:00Z run=ok\n");
    });
    expect(rowsOf().map((r) => r.outcome)).toEqual(["run_incomplete", "run_ok"]);
    expect(result.succeeded).toBe(1);
    expect(existsSync(human())).toBe(true);
  });
});
