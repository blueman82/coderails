import { vi, describe, it, expect } from "vitest";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpDir, testConfig, req, readFramesUntil } from "./events.fixture";
import { createEventsHandler } from "../src/app/api/events/route";
import { createAggregator } from "../src/lib/collect";

// A watcher can register successfully yet lose a native callback. Keep the
// filesystem and collectors real while suppressing only watch delivery.
vi.mock("node:fs", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:fs")>();
  return {
    ...actual,
    watch: () => ({ on() { return this; }, close() {} }),
  };
});

describe("GET /api/events — missed watcher callback", () => {
  it("reconciles activity and gates after writes even when fs.watch stays silent", async () => {
    const projectsDir = tmpDir("dashboard-reconcile-projects-");
    const loopsDir = tmpDir("dashboard-reconcile-loops-");
    const runsDir = tmpDir("dashboard-reconcile-runs-");
    const buildsDir = tmpDir("dashboard-reconcile-builds-");
    const hash = "a".repeat(64);
    mkdirSync(join(buildsDir, hash));
    writeFileSync(join(buildsDir, hash, "state.json"), JSON.stringify({ schemaVersion: 1, hash, state: "running" }));

    const response = createEventsHandler({ config: testConfig(), projectsDir, loopsDir, runsDir, buildsDir, gatesPollMs: 8_000 })(req());
    let wrote = false;
    const frames = await Promise.race([
      readFramesUntil(response.body!, (seen) => {
        if (!wrote && seen.some((frame) => frame.event === "activity") && seen.some((frame) => frame.event === "gates")) {
          wrote = true;
          const nextHash = "b".repeat(64);
          mkdirSync(join(buildsDir, nextHash));
          writeFileSync(join(buildsDir, nextHash, "state.json"), JSON.stringify({ schemaVersion: 1, hash: nextHash, state: "pr_open" }));
          writeFileSync(join(runsDir, "test.log"), "{}\n");
        }
        return seen.filter((frame) => frame.event === "activity").length >= 2 && seen.filter((frame) => frame.event === "gates").length >= 2;
      }),
      new Promise<never>((_, reject) => setTimeout(() => reject(new Error("reconciliation did not deliver both frames")), 11_000)),
    ]);
    expect(wrote).toBe(true);
    const activities = frames.filter((frame) => frame.event === "activity");
    expect((activities[1].data as { builds: unknown[] }).builds).toHaveLength(2);
    expect(frames.filter((frame) => frame.event === "gates")).toHaveLength(2);
  }, 12_000);

  it("clears both reconciliation intervals on stop", () => {
    vi.useFakeTimers();
    try {
      const aggregator = createAggregator({
        cfg: testConfig(),
        projectsDir: tmpDir("dashboard-reconcile-projects-"),
        loopsDir: tmpDir("dashboard-reconcile-loops-"),
      });
      aggregator.subscribe(() => {});
      aggregator.start();
      expect(vi.getTimerCount()).toBe(2);
      aggregator.stop();
      expect(vi.getTimerCount()).toBe(0);
    } finally {
      vi.useRealTimers();
    }
  });
});
