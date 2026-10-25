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

async function sweepWith(child: (runId: string) => void, exitCode = 0, spawnFailure?: "timeout") {
  writeFileSync(join(queueDir, "r.json"), JSON.stringify({ button: "docs-sync", requestedAt: Date.now(), source: "cli" }));
  const notifyImpl = vi.fn();
  let ownId = "";
  const runCodexImpl = vi.fn().mockImplementation(async (_argv: string[], _cwd: string, opts: { routineRunId?: string }) => {
    ownId = opts.routineRunId ?? "";
    child(ownId);
    return { exitCode, stdout: "", stderr: "", spawnFailure };
  });
  const result = await sweepOnce({
    queueDir, processingDir, archiveDir, quarantineDir, config: configFor(), runsDir, runCodexImpl, notifyImpl, clock,
  });
  return { result, notifyImpl, ownId };
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
    const { result, notifyImpl } = await sweepWith((id) => {
      appendFileSync(jsonl(), row(id, "run_incomplete", "incomplete-run"));
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
    const { result, ownId } = await sweepWith((id) => {
      const terminal = JSON.parse(row(id, "run_ok"));
      terminal.ts = "2026-07-23T20:00:00Z";
      appendFileSync(jsonl(), row(id, "run_incomplete", "incomplete-run") + JSON.stringify(terminal) + "\n");
      appendFileSync(human(), "2026-07-23T20:00:00Z run=ok\n");
    });
    expect(result).toMatchObject({ succeeded: 1, failed: 0 });
    expect(rowsOf().map((r) => r.run_id)).toEqual(["previous", ownId, ownId]);
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
    const { result, ownId } = await sweepWith((id) => {
      appendFileSync(jsonl(), row(id, "run_incomplete", "incomplete-run"));
    }, 1);
    expect(result).toMatchObject({ succeeded: 0, failed: 1 });
    expect(rowsOf().at(-1)).toMatchObject({ run_id: ownId, outcome: "run_abort" });
  });

  it.each(["run_abort", "run_refused"])("rejects a newly appended %s despite an old green human log", async (outcome) => {
    writeFileSync(human(), "2026-07-23T20:00:00Z run=ok\n");
    const { result } = await sweepWith((id) => appendFileSync(jsonl(), row(id, outcome, "merge")));
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

  it("appends it under the runner's run id when its provisional row remains", async () => {
    const { ownId } = await sweepWith((id) => appendFileSync(jsonl(), row(id, "run_incomplete", "incomplete-run")));
    const rows = rowsOf();
    expect(rows.map((r) => r.outcome)).toEqual(["run_incomplete", "run_abort"]);
    expect(rows[1].run_id).toBe(ownId);
  });

  it("writes nothing when the run already has a terminal row", async () => {
    const { result } = await sweepWith((id) => {
      appendFileSync(jsonl(), row(id, "run_incomplete", "incomplete-run") + row(id, "run_ok"));
      appendFileSync(human(), "2026-07-23T20:00:00Z run=ok\n");
    });
    expect(rowsOf().map((r) => r.outcome)).toEqual(["run_incomplete", "run_ok"]);
    expect(result.succeeded).toBe(1);
    expect(existsSync(human())).toBe(true);
  });

  it("does not accept another child's success when this child writes no row", async () => {
    const { result, ownId } = await sweepWith(() => appendFileSync(jsonl(), row("bbbbbbbbbbbbbbbb", "run_ok")));
    expect(result).toMatchObject({ succeeded: 0, failed: 1 });
    expect(rowsOf().at(-1)).toMatchObject({ run_id: ownId, outcome: "run_abort" });
  });

  it("keeps a merged but unfinished run red without appending an abort", async () => {
    const { result, ownId } = await sweepWith((id) => {
      appendFileSync(jsonl(), row(id, "run_incomplete", "merged_incomplete"));
    });
    expect(result).toMatchObject({ succeeded: 0, failed: 1 });
    expect(rowsOf()).toHaveLength(1);
    expect(rowsOf()[0]).toMatchObject({ run_id: ownId, reason_code: "merged_incomplete" });
  });

  it("does not append a timeout abort after a confirmed merged-incomplete row", async () => {
    const { result } = await sweepWith((id) => {
      appendFileSync(jsonl(), row(id, "run_incomplete", "merged_incomplete"));
      appendFileSync(human(), "2026-07-23T20:00:00Z incomplete=merged\n");
    }, 1, "timeout");
    expect(result).toMatchObject({ succeeded: 0, failed: 1 });
    expect(rowsOf()).toHaveLength(1);
    expect(readFileSync(human(), "utf-8")).not.toContain("runner-timeout-kill");
  });

  it.each([undefined, "timeout"] as const)("keeps a persisted merge attempt red after log loss (%s)", async (failure) => {
    const { result, ownId } = await sweepWith((id) => {
      writeFileSync(join(root, "run-active.state.json"), JSON.stringify({
        v: 1, run_id: id, routine: "docs-sync",
        merge_attempt: { number: 7, url: "https://github.com/example/test/pull/7", headRefName: "docs/fix", headRefOid: "a".repeat(40) },
      }));
    }, failure ? 1 : 0, failure);
    expect(result).toMatchObject({ succeeded: 0, failed: 1 });
    expect(rowsOf().at(-1)).toMatchObject({ run_id: ownId, outcome: "run_incomplete", reason_code: "merge_state_unknown" });
    expect(readFileSync(human(), "utf-8")).not.toContain("abort=");
  });

  it.each(["unreadable", "changed"] as const)("does not mark a timeout abort when a merge attempt has a %s event log", async (logFailure) => {
    if (logFailure === "changed") writeFileSync(jsonl(), row("previous", "run_ok"));
    const { result } = await sweepWith((id) => {
      writeFileSync(join(root, "run-active.state.json"), JSON.stringify({
        run_id: id, routine: "docs-sync", merge_attempt: { number: 7 },
      }));
      if (logFailure === "unreadable") mkdirSync(jsonl());
      else writeFileSync(jsonl(), row("replacement", "run_ok"));
    }, 1, "timeout");
    expect(result).toMatchObject({ succeeded: 0, failed: 1 });
    expect(existsSync(human()) ? readFileSync(human(), "utf-8") : "").not.toContain("abort=");
  });

  it("does not mark a timeout abort when merge state is unreadable", async () => {
    const { result } = await sweepWith(() => mkdirSync(join(root, "run-active.state.json")), 1, "timeout");
    expect(result).toMatchObject({ succeeded: 0, failed: 1 });
    expect(existsSync(human()) ? readFileSync(human(), "utf-8") : "").not.toContain("abort=");
  });

  it("keeps the timeout abort marker when there is no merge attempt", async () => {
    const { result } = await sweepWith(() => mkdirSync(jsonl()), 1, "timeout");
    expect(result).toMatchObject({ succeeded: 0, failed: 1 });
    expect(readFileSync(human(), "utf-8")).toContain("abort=runner-timeout-kill");
  });
});
