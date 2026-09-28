import { tmpDir, testConfig, req, readFramesUntil, readFramesUntilPlus } from "./events.fixture";
import { describe, it, expect, vi } from "vitest";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { createEventsHandler } from "../src/app/api/events/route";
import { createAggregator } from "../src/lib/collect";
import * as prGatesModule from "../src/lib/collect/prGates";

describe("GET /api/events — gates freshness", () => {
  it("a runs-dir change triggers a second gates frame after the debounce window", async () => {
    const projectsDir = tmpDir("dashboard-gates-debounce-projects-");
    const loopsDir = tmpDir("dashboard-gates-debounce-loops-");
    const runsDir = tmpDir("dashboard-gates-debounce-runs-");
    mkdirSync(runsDir, { recursive: true });

    const handler = createEventsHandler({
      config: testConfig(),
      projectsDir,
      loopsDir,
      runsDir,
      gatesPollMs: 999_999, // disable the periodic poll so only the runsDir-triggered debounce can produce a 2nd gates frame
    });
    const res = handler(req());

    // The first "gates" frame comes from start()'s unconditional initial
    // refreshGates() call, before any runsDir write. Wait for it, THEN write
    // into runsDir, then require a SECOND gates frame — asserting merely
    // "a gates frame arrived" would be satisfied by the startup frame alone
    // even with the runsDir watcher wired to a no-op.
    let touched = false;
    const framesPromise = readFramesUntil(res.body!, (frames) => {
      const gatesFrames = frames.filter((f) => f.event === "gates");
      if (gatesFrames.length >= 1 && !touched) {
        touched = true;
        writeFileSync(join(runsDir, "test1.log"), "{}");
      }
      return gatesFrames.length >= 2;
    });

    const timeout = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error("timed out waiting for second gates frame")), 12000)
    );
    const frames = await Promise.race([framesPromise, timeout]);

    const gatesFrames = frames.filter((f) => f.event === "gates");
    expect(gatesFrames.length).toBe(2);
  }, 13000);

  it("two rapid runs-dir writes collapse into exactly one additional gates frame", async () => {
    const projectsDir = tmpDir("dashboard-gates-debounce-projects-");
    const loopsDir = tmpDir("dashboard-gates-debounce-loops-");
    const runsDir = tmpDir("dashboard-gates-debounce-runs-");
    mkdirSync(runsDir, { recursive: true });

    const handler = createEventsHandler({
      config: testConfig(),
      projectsDir,
      loopsDir,
      runsDir,
      gatesPollMs: 999_999,
    });
    const res = handler(req());

    let touched = false;
    // After the 2nd gates frame arrives (startup + the debounced refresh
    // from the two rapid writes), keep reading for another 2s — long enough
    // to catch a 3rd frame if the two writes were wrongly treated as two
    // separate un-debounced refreshes instead of collapsing into one. The
    // two writes are spaced ~250ms apart (still well inside the 3s debounce
    // window, so correct code still collapses them to one refresh) so the OS
    // delivers two distinct fs.watch change events rather than coalescing a
    // pair of synchronous writes into one — otherwise a no-debounce
    // implementation could also land exactly 2 frames and this test would
    // prove nothing about debouncing specifically.
    const framesPromise = readFramesUntilPlus(
      res.body!,
      (frames) => {
        const gatesFrames = frames.filter((f) => f.event === "gates");
        if (gatesFrames.length >= 1 && !touched) {
          touched = true;
          writeFileSync(join(runsDir, "rapid1.log"), "{}");
          setTimeout(() => writeFileSync(join(runsDir, "rapid2.log"), "{}"), 250);
        }
        return gatesFrames.length >= 2;
      },
      2000
    );

    const timeout = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error("timed out waiting for the debounced gates frame")), 12000)
    );
    const frames = await Promise.race([framesPromise, timeout]);

    const gatesFrames = frames.filter((f) => f.event === "gates");
    expect(gatesFrames.length).toBe(2);
  }, 15000);

  it("stop() cancels a pending gates debounce — collectPrGates is not called again after stop()", async () => {
    const projectsDir = tmpDir("dashboard-gates-stop-projects-");
    const loopsDir = tmpDir("dashboard-gates-stop-loops-");
    const runsDir = tmpDir("dashboard-gates-stop-runs-");
    mkdirSync(runsDir, { recursive: true });

    const collectPrGatesMock = prGatesModule.collectPrGates as unknown as ReturnType<typeof vi.fn>;
    collectPrGatesMock.mockClear();

    const aggregator = createAggregator({
      cfg: testConfig(),
      projectsDir,
      loopsDir,
      runsDir,
      gatesPollMs: 999_999,
    });
    aggregator.start();

    // Let the initial (unconditional) refreshGates() from start() resolve.
    await new Promise((r) => setTimeout(r, 200));
    const callsAfterStart = collectPrGatesMock.mock.calls.length;
    expect(callsAfterStart).toBeGreaterThanOrEqual(1);

    // Give fs.watch a tick to be armed, then write into runsDir to schedule
    // the 3s gates debounce — then stop() well before it would fire.
    await new Promise((r) => setTimeout(r, 50));
    writeFileSync(join(runsDir, "test1.log"), "{}");
    await new Promise((r) => setTimeout(r, 100));
    aggregator.stop();

    // Wait past the 3s debounce window. If stop() failed to clear the
    // pending timer, refreshGates() fires here and collectPrGates is called
    // again.
    await new Promise((r) => setTimeout(r, 4000));

    expect(collectPrGatesMock.mock.calls.length).toBe(callsAfterStart);
  }, 12000);

  it("default poll fires refreshGates at 30s, not only at 120s", async () => {
    const projectsDir = tmpDir("dashboard-gates-poll-projects-");
    const loopsDir = tmpDir("dashboard-gates-poll-loops-");

    const collectPrGatesMock = prGatesModule.collectPrGates as unknown as ReturnType<typeof vi.fn>;
    collectPrGatesMock.mockClear();

    vi.useFakeTimers();
    try {
      // Deliberately omit runsDir: on this fs.watch implementation, a fresh
      // recursive watcher on a brand-new empty directory can fire one
      // spurious initial "change" event shortly after registration, which
      // would arm the (unrelated) runsDir debounce path and add a spurious
      // gates refresh independent of the poll interval under test — this
      // test only cares about the setInterval(gatesPollMs) path in start().
      const aggregator = createAggregator({
        cfg: testConfig(),
        projectsDir,
        loopsDir,
        // Do not override gatesPollMs, so it uses DEFAULT_GATES_POLL_MS (30_000).
      });
      aggregator.start();

      // start()'s unconditional initial refreshGates() call is async (it
      // awaits collectPrGates) — advancing by 0ms flushes that pending
      // microtask under fake timers before we read the call count.
      await vi.advanceTimersByTimeAsync(0);
      const callsAfterStart = collectPrGatesMock.mock.calls.length;
      expect(callsAfterStart).toBeGreaterThanOrEqual(1);

      // Just short of 30s: the poll must NOT have fired yet.
      await vi.advanceTimersByTimeAsync(29_000);
      expect(collectPrGatesMock.mock.calls.length).toBe(callsAfterStart);

      // Past 30s total: exactly one additional call from the poll interval —
      // if the interval were still 120_000 (or any longer default), this
      // would still show callsAfterStart with no new call.
      await vi.advanceTimersByTimeAsync(1_100);
      expect(collectPrGatesMock.mock.calls.length).toBe(callsAfterStart + 1);

      aggregator.stop();
    } finally {
      // Restore real timers unconditionally so a failure inside the try
      // block above can't leak fake timers into later tests in this file —
      // exactly the leak that made the previous version of this test
      // (mocking setInterval directly) order-dependent.
      vi.useRealTimers();
    }
  });
});
