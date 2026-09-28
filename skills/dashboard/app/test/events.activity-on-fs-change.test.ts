import { tmpDir, testConfig, req, readFramesUntil } from "./events.fixture";
import { describe, it, expect } from "vitest";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { createEventsHandler } from "../src/app/api/events/route";

describe("GET /api/events — activity on fs change", () => {
  it("emits an activity event within the debounce window after a watched fixture file is touched", async () => {
    const projectsDir = tmpDir("dashboard-events-projects-");
    const loopsDir = tmpDir("dashboard-events-loops-");
    const runsDir = tmpDir("dashboard-events-runs-");
    const debounceMs = 200;

    const handler = createEventsHandler({
      config: testConfig(),
      projectsDir,
      loopsDir,
      runsDir,
      activityDebounceMs: debounceMs,
      gatesPollMs: 999_999,
    });
    const res = handler(req());
    const framesPromise = readFramesUntil(res.body!, (frames) =>
      frames.some((f) => f.event === "activity")
    );

    // give the stream a tick to start() (and thus begin watching) before touching
    await new Promise((r) => setTimeout(r, 50));
    mkdirSync(join(projectsDir, "-touched-project"), { recursive: true });
    writeFileSync(join(projectsDir, "-touched-project", "session.jsonl"), "{}\n");

    const timeout = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error("timed out waiting for activity event")), 5000)
    );
    const frames = await Promise.race([framesPromise, timeout]);

    expect(frames[0].event).toBe("snapshot");
    const activityFrame = frames.find((f) => f.event === "activity");
    expect(activityFrame).toBeDefined();
    const activity = activityFrame!.data as Record<string, unknown>;
    // Wire-shape regression guard: the activity payload's key set is
    // enumerated exactly here (rather than spot-checked) so a future slice
    // drop — trail removal, or dropping any other key — is caught on the
    // wire instead of degrading silently on the client.
    expect(Object.keys(activity).sort()).toEqual(["builds", "health", "loops", "queue", "sessions"].sort());
    expect(Array.isArray(activity.sessions)).toBe(true);
    // Regression: health used to be computed alongside sessions/loops but
    // dropped before the emit, so tiles never left "unavailable" on the
    // client past the initial (necessarily empty) snapshot frame.
    expect(Array.isArray(activity.health)).toBe(true);
    expect((activity.health as unknown[]).length).toBeGreaterThan(0);
  }, 6000);

  it("populates health without any watched-dir touch — the initial refreshActivity() from start() alone must eventually emit it", async () => {
    // Reproduces the reported defect: a fresh SSE connection's first
    // "snapshot" frame necessarily ships health:[] (aggregator.start()
    // fires refreshActivity() without awaiting it before the snapshot is
    // read), but nothing in the client's control ever touches
    // projectsDir/loopsDir on a cold connection — so if health only ever
    // repopulates on a fs-watch event (as the "activity on fs change" test
    // above exercises), a page that never causes a watched-dir write would
    // see health:[] forever. This test opens a connection and does NOT
    // touch either watched dir, asserting that a populated-health frame
    // still arrives (from start()'s own unconditional initial collect).
    const projectsDir = tmpDir("dashboard-events-health-projects-");
    const loopsDir = tmpDir("dashboard-events-health-loops-");
    const runsDir = tmpDir("dashboard-events-health-runs-");
    mkdirSync(join(projectsDir, "-proj"), { recursive: true });
    writeFileSync(
      join(projectsDir, "-proj", "a.jsonl"),
      JSON.stringify({
        type: "assistant",
        timestamp: new Date().toISOString(),
        message: { id: "msg_1", role: "assistant", usage: { input_tokens: 10, output_tokens: 5 } },
      }) + "\n"
    );

    const handler = createEventsHandler({
      config: testConfig(),
      projectsDir,
      loopsDir,
      runsDir,
      gatesPollMs: 999_999,
    });
    const res = handler(req());

    const framesPromise = readFramesUntil(
      res.body!,
      (frames) =>
        frames.some(
          (f) => f.event === "activity" && Array.isArray((f.data as Record<string, unknown>).health) &&
            ((f.data as Record<string, unknown>).health as unknown[]).length > 0
        )
    );
    const timeout = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error("timed out waiting for a populated-health activity frame")), 5000)
    );
    const frames = await Promise.race([framesPromise, timeout]);

    const populatedActivity = frames.find(
      (f) => f.event === "activity" && ((f.data as Record<string, unknown>).health as unknown[]).length > 0
    );
    expect(populatedActivity).toBeDefined();
  }, 6000);

  it("emits contextTrend on its OWN 'context-trend' frame, not inside the activity slice", async () => {
    // Decoupling guard: the contextTrend collect streams every coderails
    // orchestrator transcript and
    // is far slower than the activity slice, so it must ride a separate frame.
    // If it were folded back into "activity", the slow collect would gate the
    // KPI tiles (the ~10s cold-cache all-loading regression). Assert (1) a
    // "context-trend" frame arrives on a cold connection from start()'s own
    // collect, and (2) the activity frame never carries a contextTrend key.
    const projectsDir = tmpDir("dashboard-events-ct-projects-");
    const loopsDir = tmpDir("dashboard-events-ct-loops-");
    const runsDir = tmpDir("dashboard-events-ct-runs-");
    mkdirSync(join(projectsDir, "-proj"), { recursive: true });
    writeFileSync(
      join(projectsDir, "-proj", "a.jsonl"),
      JSON.stringify({
        type: "assistant",
        timestamp: new Date().toISOString(),
        message: { id: "msg_1", role: "assistant", usage: { input_tokens: 10, output_tokens: 5 } },
      }) + "\n"
    );

    const handler = createEventsHandler({
      config: testConfig(),
      projectsDir,
      loopsDir,
      runsDir,
      gatesPollMs: 999_999,
    });
    const res = handler(req());

    const framesPromise = readFramesUntil(res.body!, (frames) =>
      frames.some((f) => f.event === "context-trend")
    );
    const timeout = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error("timed out waiting for a context-trend frame")), 5000)
    );
    const frames = await Promise.race([framesPromise, timeout]);

    expect(frames.some((f) => f.event === "context-trend")).toBe(true);
    // The "no activity frame carries contextTrend" half of this property is
    // asserted by the exact-key-set wire-shape guard above (the "activity on fs
    // change" test), which enumerates the activity payload's full key set and
    // so strictly dominates a "lacks one key" check here. Not repeated: reading
    // stops at the first context-trend frame, which on a cold connection
    // arrives before any activity frame, so a loop over activity frames here
    // would iterate zero times and assert nothing.
  }, 6000);

  it("re-emits a 'context-trend' frame when projectsDir changes, not only on start()", async () => {
    // Watch-refresh guard. start() fires refreshContextTrend() once, so a test
    // that merely waits for A context-trend frame is satisfied by that cold
    // start emit alone — it would still pass with scheduleContextTrendRefresh()
    // deleted from the projectsDir watcher, leaving the panel frozen at its
    // first-paint value while the KPI tiles kept refreshing. So count to TWO:
    // the start() frame, then a second one caused by the fs write below. This
    // mirrors the activity and gates collectors, which both already have a
    // watch/debounce refresh test.
    const projectsDir = tmpDir("dashboard-events-ctwatch-projects-");
    const loopsDir = tmpDir("dashboard-events-ctwatch-loops-");
    const runsDir = tmpDir("dashboard-events-ctwatch-runs-");
    mkdirSync(join(projectsDir, "-proj"), { recursive: true });

    const handler = createEventsHandler({
      config: testConfig(),
      projectsDir,
      loopsDir,
      runsDir,
      gatesPollMs: 999_999,
      activityDebounceMs: 50,
    });
    const res = handler(req());

    const framesPromise = readFramesUntil(
      res.body!,
      (frames) => frames.filter((f) => f.event === "context-trend").length >= 2
    );
    const timeout = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error("timed out waiting for a SECOND context-trend frame")), 5000)
    );

    // Give the start() collect a moment to land, then touch the watched dir.
    await new Promise((r) => setTimeout(r, 150));
    mkdirSync(join(projectsDir, "-touched-coderails-project"), { recursive: true });
    writeFileSync(join(projectsDir, "-touched-coderails-project", "session.jsonl"), "{}\n");

    const frames = await Promise.race([framesPromise, timeout]);
    expect(frames.filter((f) => f.event === "context-trend").length).toBeGreaterThanOrEqual(2);
  }, 6000);

  it("snapshot carries a builds field populated from buildsDir, and it refreshes when a build's state.json changes", async () => {
    const projectsDir = tmpDir("dashboard-events-projects-");
    const loopsDir = tmpDir("dashboard-events-loops-");
    const runsDir = tmpDir("dashboard-events-runs-");
    const buildsDir = tmpDir("dashboard-events-builds-");
    const debounceMs = 200;

    const firstHash = "a".repeat(64);
    mkdirSync(join(buildsDir, firstHash), { recursive: true });
    writeFileSync(
      join(buildsDir, firstHash, "state.json"),
      JSON.stringify({ schemaVersion: 1, hash: firstHash, state: "running" })
    );

    const handler = createEventsHandler({
      config: testConfig(),
      projectsDir,
      loopsDir,
      runsDir,
      buildsDir,
      activityDebounceMs: debounceMs,
      gatesPollMs: 999_999,
    });
    const res = handler(req());

    // The first "activity" frame comes from start()'s unconditional initial
    // refreshActivity() call (unrelated to file watching) and carries only
    // firstHash. Once it lands, write the second build; the debounced
    // fs.watch-triggered refresh then emits a second "activity" frame
    // carrying both. Read continuously (a stream's reader/cancel can only be
    // used once) until two activity frames have arrived.
    let secondBuildWritten = false;
    const framesPromise = readFramesUntil(res.body!, (frames) => {
      const activityFrames = frames.filter((f) => f.event === "activity");
      if (activityFrames.length >= 1 && !secondBuildWritten) {
        secondBuildWritten = true;
        const secondHash = "b".repeat(64);
        mkdirSync(join(buildsDir, secondHash), { recursive: true });
        writeFileSync(
          join(buildsDir, secondHash, "state.json"),
          JSON.stringify({ schemaVersion: 1, hash: secondHash, state: "pr_open" })
        );
      }
      return activityFrames.length >= 2;
    });

    const timeout = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error("timed out waiting for two activity frames")), 8000)
    );
    const frames = await Promise.race([framesPromise, timeout]);

    const activityFrames = frames.filter((f) => f.event === "activity");
    const firstActivity = activityFrames[0].data as { builds: { hash: string }[] };
    expect(firstActivity.builds.map((b) => b.hash)).toEqual([firstHash]);

    const secondActivity = activityFrames[1].data as { builds: { hash: string }[] };
    expect(secondActivity.builds.map((b) => b.hash).sort()).toEqual(["a".repeat(64), "b".repeat(64)]);
  }, 10000);
});
