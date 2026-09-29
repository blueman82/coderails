import { afterEach, describe, expect, it, vi } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const command = vi.hoisted(() => vi.fn());
vi.mock("node:child_process", () => {
  Object.assign(command, {
    [Symbol.for("nodejs.util.promisify.custom")]: (...args: unknown[]) => new Promise((resolve, reject) => {
      command(...args, (error: Error | null, stdout: string, stderr: string) => {
        if (error) reject(error);
        else resolve({ stdout, stderr });
      });
    }),
  });
  return { execFile: command };
});
vi.mock("node:fs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:fs")>();
  return { ...actual, watch: () => ({ on() { return this; }, close() {} }) };
});
vi.mock("../src/lib/collect/health", () => ({ collectHealth: async () => [] }));

import { createAggregator } from "../src/lib/collect";
import { collectPrGates } from "../src/lib/collect/prGates";
import type { DashboardConfig } from "../src/lib/config";

afterEach(() => {
  vi.useRealTimers();
  command.mockReset();
});

describe("PR sweep lifecycle", () => {
  it("returns one repository error only after every view settles", async () => {
    let sibling: ((error: Error | null, stdout?: string, stderr?: string) => void) | undefined;
    command.mockImplementation((_: string, args: string[], _options: unknown, callback: (error: Error | null, stdout?: string, stderr?: string) => void) => {
      if (args[1] === "list") callback(null, '[{"number":1},{"number":2}]', "");
      else if (args[2] === "1") callback(new Error("view failed"));
      else sibling = callback;
      return { on() { return this; } };
    });
    const cfg: DashboardConfig = { repos: ["owner/repo"], wikiPaths: [], buttons: [] };
    let settled = false;
    const result = collectPrGates(cfg).then((gates) => { settled = true; return gates; });
    await Promise.resolve();
    await Promise.resolve();
    expect(sibling).toBeDefined();
    expect(settled).toBe(false);
    sibling?.(null, '{"number":2,"title":"second","headRefOid":"sha","comments":[]}', "");
    expect(await result).toEqual([{ repo: "owner/repo", error: "view failed" }]);
  });

  it("keeps a failed sweep owned until sibling views settle, then aborts it on stop without publishing", async () => {
    vi.useFakeTimers();
    const dir = mkdtempSync(join(tmpdir(), "pr-gate-lifecycle-"));
    try {
      let sibling: ((error: Error | null, stdout?: string, stderr?: string) => void) | undefined;
      let siblingSignal: AbortSignal | undefined;
      let lists = 0;
      command.mockImplementation((_: string, args: string[], options: { signal: AbortSignal }, callback: (error: Error | null, stdout?: string, stderr?: string) => void) => {
        if (args[1] === "list") {
          lists++;
          callback(null, '[{"number":1},{"number":2}]', "");
        } else if (args[2] === "1") {
          callback(new Error("view failed"));
        } else {
          sibling = callback;
          siblingSignal = options.signal;
        }
        return { on() { return this; } };
      });
      const cfg: DashboardConfig = { repos: ["owner/repo"], wikiPaths: [], buttons: [] };
      const subject = createAggregator({ cfg, projectsDir: dir, loopsDir: dir, gatesPollMs: 100, activityReconcileMs: 10_000 });
      const frames: unknown[] = [];
      subject.subscribe((event, data) => { if (event === "gates") frames.push(data); });
      subject.start();
      await vi.advanceTimersByTimeAsync(0);
      expect(sibling).toBeDefined();
      await vi.advanceTimersByTimeAsync(300);
      expect(lists).toBe(1);
      expect(frames).toEqual([]);
      subject.stop();
      expect(siblingSignal?.aborted).toBe(true);
      sibling?.(null, '{"number":2,"title":"second","headRefOid":"sha","comments":[]}', "");
      await vi.advanceTimersByTimeAsync(0);
      expect(frames).toEqual([]);
      expect(lists).toBe(1);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
