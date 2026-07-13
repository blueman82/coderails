import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createEventsHandler } from "../src/app/api/events/route";
import type { DashboardConfig } from "../src/lib/config";
import { runOutputBus } from "../src/lib/runOutputBus";

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

function testConfig(memoryPaths: string[] = []): DashboardConfig {
  return {
    repos: [],
    wikiPaths: [],
    memoryPaths,
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
    const activity = activityFrame!.data as { sessions: unknown[]; health: unknown[] };
    expect(Array.isArray(activity.sessions)).toBe(true);
    // Regression: health used to be computed alongside sessions/loops/trail
    // but dropped before the emit, so tiles never left "unavailable" on the
    // client past the initial (necessarily empty) snapshot frame.
    expect(Array.isArray(activity.health)).toBe(true);
    expect(activity.health.length).toBeGreaterThan(0);
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
