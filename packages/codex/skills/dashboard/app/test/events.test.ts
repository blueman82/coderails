import { describe, it, expect, afterEach, vi } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createEventsHandler } from "../src/app/api/events/route";
import type { DashboardConfig } from "../src/lib/config";
import { runOutputBus } from "../src/lib/runOutputBus";
import { createAggregator } from "../src/lib/collect";
import * as prGatesModule from "../src/lib/collect/prGates";

// Wraps the real collectPrGates so the "gates freshness" tests below can
// assert on call *count* (did stop() actually suppress a pending debounced
// refresh?) without changing what it returns — every other test in this file
// still exercises the real (empty-repos, so fast+empty) implementation.
vi.mock("../src/lib/collect/prGates", async () => {
  const actual = await vi.importActual<typeof prGatesModule>("../src/lib/collect/prGates");
  return { ...actual, collectPrGates: vi.fn(actual.collectPrGates) };
});

const tmpDirs: string[] = [];

function tmpDir(prefix: string): string {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  tmpDirs.push(dir);
  return dir;
}

afterEach(() => {
  for (const dir of tmpDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

function testConfig(): DashboardConfig {
  return {
    repos: [],
    wikiPaths: [],
    buttons: [],
  };
}

function req(headers: Record<string, string> = {}): Request {
  return new Request("http://127.0.0.1:3000/api/events", {
    headers: {
      origin: "http://127.0.0.1:3000",
      host: "127.0.0.1:3000",
      ...headers,
    },
  });
}

// Reads named SSE frames off a ReadableStream<Uint8Array> body, splitting on
// the blank-line frame terminator. Returns { event, data } pairs as they
// arrive; stops once `stop(frames)` returns true or the stream ends.
async function readFramesUntil(
  body: ReadableStream<Uint8Array>,
  stop: (frames: { event: string; data: unknown }[]) => boolean
): Promise<{ event: string; data: unknown }[]> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const frames: { event: string; data: unknown }[] = [];

  while (!stop(frames)) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const eventLine = raw.split("\n").find((l) => l.startsWith("event: "));
      const dataLine = raw.split("\n").find((l) => l.startsWith("data: "));
      if (eventLine && dataLine) {
        frames.push({
          event: eventLine.slice("event: ".length),
          data: JSON.parse(dataLine.slice("data: ".length)),
        });
      }
      if (stop(frames)) break;
    }
  }
  await reader.cancel();
  return frames;
}

// Reads exactly `count` frames regardless of event name.
function readFrames(body: ReadableStream<Uint8Array>, count: number) {
  return readFramesUntil(body, (frames) => frames.length >= count);
}

// Like readFramesUntil, but keeps reading for `extraMs` past the point
// `stop(frames)` first becomes true, to catch a straggler frame that arrives
// shortly after the condition is met (e.g. an incorrectly un-debounced
// second refresh). Uses a single reader for the whole window.
async function readFramesUntilPlus(
  body: ReadableStream<Uint8Array>,
  stop: (frames: { event: string; data: unknown }[]) => boolean,
  extraMs: number
): Promise<{ event: string; data: unknown }[]> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const frames: { event: string; data: unknown }[] = [];
  let deadline: number | undefined;

  while (true) {
    if (deadline !== undefined && Date.now() >= deadline) break;
    const readPromise = reader.read();
    const remaining = deadline !== undefined ? deadline - Date.now() : undefined;
    const raced =
      remaining !== undefined
        ? await Promise.race([readPromise, new Promise<{ done: true; value: undefined }>((r) => setTimeout(() => r({ done: true, value: undefined }), remaining))])
        : await readPromise;
    if (raced.done) break;
    buffer += decoder.decode(raced.value, { stream: true });

    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const eventLine = raw.split("\n").find((l) => l.startsWith("event: "));
      const dataLine = raw.split("\n").find((l) => l.startsWith("data: "));
      if (eventLine && dataLine) {
        frames.push({
          event: eventLine.slice("event: ".length),
          data: JSON.parse(dataLine.slice("data: ".length)),
        });
      }
    }
    if (deadline === undefined && stop(frames)) {
      deadline = Date.now() + extraMs;
    }
  }
  await reader.cancel();
  return frames;
}

async function readRawText(body: ReadableStream<Uint8Array>, minBytes: number, timeoutMs: number): Promise<string> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let text = "";
  const deadline = Date.now() + timeoutMs;
  while (text.length < minBytes && Date.now() < deadline) {
    const { value, done } = await reader.read();
    if (done) break;
    text += decoder.decode(value, { stream: true });
  }
  await reader.cancel();
  return text;
}

describe("GET /api/events — origin/host wall", () => {
  it("rejects a non-localhost Origin with 403", async () => {
    const handler = createEventsHandler({ config: testConfig() });
    const res = handler(req({ origin: "https://evil.example" }));
    expect(res.status).toBe(403);
  });

  it("rejects a non-localhost Host with 403", async () => {
    const handler = createEventsHandler({ config: testConfig() });
    const res = handler(req({ host: "evil.example", origin: "http://evil.example" }));
    expect(res.status).toBe(403);
  });

  it("accepts an http://127.0.0.1 origin with a text/event-stream response", async () => {
    const handler = createEventsHandler({
      config: testConfig(),
      projectsDir: tmpDir("dashboard-events-projects-"),
      loopsDir: tmpDir("dashboard-events-loops-"),
      runsDir: tmpDir("dashboard-events-runs-"),
    });
    const res = handler(req());
    expect(res.status).toBe(200);
    expect(res.headers.get("content-type")).toContain("text/event-stream");
    await res.body?.cancel();
  });
});

describe("GET /api/events — snapshot", () => {
  it("emits a complete snapshot event as the first frame, within 3s", async () => {
    const handler = createEventsHandler({
      config: testConfig(),
      projectsDir: tmpDir("dashboard-events-projects-"),
      loopsDir: tmpDir("dashboard-events-loops-"),
      runsDir: tmpDir("dashboard-events-runs-"),
    });
    const res = handler(req());
    expect(res.body).toBeTruthy();

    const framesPromise = readFrames(res.body!, 1);
    const timeout = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error("timed out waiting for snapshot")), 3000)
    );
    const frames = await Promise.race([framesPromise, timeout]);

    expect(frames[0].event).toBe("snapshot");
    const snapshot = frames[0].data as Record<string, unknown>;
    expect(snapshot).toHaveProperty("sessions");
    expect(snapshot).toHaveProperty("loops");
    expect(snapshot).toHaveProperty("gates");
    expect(snapshot).toHaveProperty("health");
    expect(snapshot).toHaveProperty("runs");
    expect(snapshot).not.toHaveProperty("trail");
  }, 4000);

  it("never includes a token key anywhere in the captured stream", async () => {
    const handler = createEventsHandler({
      config: testConfig(),
      projectsDir: tmpDir("dashboard-events-projects-"),
      loopsDir: tmpDir("dashboard-events-loops-"),
      runsDir: tmpDir("dashboard-events-runs-"),
    });
    const res = handler(req());
    const text = await readRawText(res.body!, 1, 3000);
    expect(text).toContain("event: snapshot");
    expect(text.toLowerCase()).not.toContain("token");
  });
});

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

describe("GET /api/events — run-output forwarding", () => {
  it("forwards a chunk published on the shared runOutputBus as a 'run-output' SSE event carrying {runId, chunk}", async () => {
    const handler = createEventsHandler({
      config: testConfig(),
      projectsDir: tmpDir("dashboard-events-projects-"),
      loopsDir: tmpDir("dashboard-events-loops-"),
      runsDir: tmpDir("dashboard-events-runs-"),
      gatesPollMs: 999_999,
    });
    const res = handler(req());

    const framesPromise = readFramesUntil(res.body!, (frames) =>
      frames.some((f) => f.event === "run-output")
    );

    // give the stream a tick to start() (and thus subscribe to the bus)
    // before publishing.
    await new Promise((r) => setTimeout(r, 50));
    runOutputBus.publish("abc123", "hello from the child process\n");

    const timeout = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error("timed out waiting for run-output event")), 3000)
    );
    const frames = await Promise.race([framesPromise, timeout]);

    const runOutputFrame = frames.find((f) => f.event === "run-output");
    expect(runOutputFrame).toBeDefined();
    expect(runOutputFrame!.data).toEqual({ runId: "abc123", chunk: "hello from the child process\n" });
  }, 4000);

  it("stops forwarding to a cancelled/disconnected stream (unsubscribes on cancel)", async () => {
    const handler = createEventsHandler({
      config: testConfig(),
      projectsDir: tmpDir("dashboard-events-projects-"),
      loopsDir: tmpDir("dashboard-events-loops-"),
      runsDir: tmpDir("dashboard-events-runs-"),
      gatesPollMs: 999_999,
    });
    const res = handler(req());
    await new Promise((r) => setTimeout(r, 50));
    await res.body!.cancel();

    // Publishing after cancel must not throw (proves the bus subscription
    // was torn down cleanly, not left dangling against a closed controller).
    expect(() => runOutputBus.publish("after-cancel", "x")).not.toThrow();
  });
});

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
