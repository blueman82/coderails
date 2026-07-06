import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { collectQueue } from "../src/lib/collect/queue";

const tmpDirs: string[] = [];

function makeTmpDir(name: string): string {
  const dir = mkdtempSync(join(tmpdir(), `dashboard-queue-${name}-`));
  tmpDirs.push(dir);
  return dir;
}

function writeEntry(dir: string, hash: string, overrides: Record<string, unknown> = {}): string {
  const path = join(dir, `${hash}.json`);
  const entry = {
    hash,
    toolName: "mcp__claude_ai_Slack__slack_send_message",
    toolInput: { channel: "#general", text: "hello" },
    createdAt: Date.now(),
    status: "pending",
    ...overrides,
  };
  writeFileSync(path, JSON.stringify(entry));
  return path;
}

afterEach(() => {
  for (const dir of tmpDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("collectQueue", () => {
  it("parses a queue dir of <hash>.json files into QueueEntry[] matching the frozen shape", () => {
    const dir = makeTmpDir("basic");
    writeEntry(dir, "aaa111");
    const entries = collectQueue(dir);
    expect(entries).toHaveLength(1);
    expect(entries[0]).toEqual({
      hash: "aaa111",
      toolName: "mcp__claude_ai_Slack__slack_send_message",
      toolInput: { channel: "#general", text: "hello" },
      createdAt: expect.any(Number),
      status: "pending",
    });
  });

  it("contributes nothing for a nonexistent dir, and does not throw", () => {
    const missing = join(tmpdir(), "does-not-exist-queue-dir");
    expect(() => collectQueue(missing)).not.toThrow();
    expect(collectQueue(missing)).toEqual([]);
  });

  it("skips a file with invalid JSON rather than throwing", () => {
    const dir = makeTmpDir("badjson");
    writeFileSync(join(dir, "bad111.json"), "{ not valid json");
    writeEntry(dir, "good111");
    expect(() => collectQueue(dir)).not.toThrow();
    const entries = collectQueue(dir);
    expect(entries.map((e) => e.hash)).toEqual(["good111"]);
  });

  it("skips a file missing the required status field", () => {
    const dir = makeTmpDir("missing-status");
    const path = join(dir, "nostat111.json");
    writeFileSync(
      path,
      JSON.stringify({
        hash: "nostat111",
        toolName: "mcp__claude_ai_Slack__slack_send_message",
        toolInput: {},
        createdAt: Date.now(),
        // status deliberately omitted
      })
    );
    writeEntry(dir, "good222");
    const entries = collectQueue(dir);
    expect(entries.map((e) => e.hash)).toEqual(["good222"]);
  });

  it("skips a file whose status is not one of pending/approved/denied (does not default to approved)", () => {
    const dir = makeTmpDir("bad-status");
    writeEntry(dir, "weird111", { status: "expired" });
    writeEntry(dir, "good333");
    const entries = collectQueue(dir);
    expect(entries.map((e) => e.hash)).toEqual(["good333"]);
  });

  it("skips a file with a renamed field (e.g. tool_name snake_case) rather than normalising it", () => {
    const dir = makeTmpDir("renamed-field");
    const path = join(dir, "renamed111.json");
    writeFileSync(
      path,
      JSON.stringify({
        hash: "renamed111",
        tool_name: "mcp__claude_ai_Slack__slack_send_message",
        toolInput: {},
        createdAt: Date.now(),
        status: "pending",
      })
    );
    writeEntry(dir, "good444");
    const entries = collectQueue(dir);
    expect(entries.map((e) => e.hash)).toEqual(["good444"]);
  });

  it("a deliberately-broken collector that lets readdirSync's ENOENT propagate would fail the nonexistent-dir control", () => {
    // Negative control for E2: prove the "does not throw" assertion is meaningful by
    // demonstrating the naive implementation (no try/catch) does throw on a missing dir.
    expect(() => {
      // eslint-disable-next-line @typescript-eslint/no-var-requires -- intentional raw call to prove the failure mode
      require("node:fs").readdirSync(join(tmpdir(), "does-not-exist-queue-dir-2"));
    }).toThrow();
  });

  it("leaves an undecided entry's status as pending — never defaults to approved", () => {
    const dir = makeTmpDir("undecided");
    writeEntry(dir, "undecided111", { status: "pending" });
    const entries = collectQueue(dir);
    expect(entries[0].status).toBe("pending");
  });

  it("returns entries sorted newest-first by createdAt", () => {
    const dir = makeTmpDir("sorted");
    const now = Date.now();
    writeEntry(dir, "older", { createdAt: now - 60_000 });
    writeEntry(dir, "newer", { createdAt: now });
    const entries = collectQueue(dir);
    expect(entries.map((e) => e.hash)).toEqual(["newer", "older"]);
  });

  it("respects a limit param after sorting", () => {
    const dir = makeTmpDir("limit");
    const now = Date.now();
    writeEntry(dir, "a", { createdAt: now - 30_000 });
    writeEntry(dir, "b", { createdAt: now - 20_000 });
    writeEntry(dir, "c", { createdAt: now - 10_000 });
    const entries = collectQueue(dir, 2);
    expect(entries).toHaveLength(2);
    expect(entries[0].hash).toBe("c");
  });
});
