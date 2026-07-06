import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createEventsHandler } from "../src/app/api/events/route";
import type { DashboardConfig } from "../src/lib/config";

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
// arrive; stops once `count` frames have been read or the stream ends.
async function readFrames(
  body: ReadableStream<Uint8Array>,
  count: number
): Promise<{ event: string; data: unknown }[]> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const frames: { event: string; data: unknown }[] = [];

  while (frames.length < count) {
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
      if (frames.length >= count) break;
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
    expect(snapshot).toHaveProperty("trail");
    expect(snapshot).toHaveProperty("health");
    expect(snapshot).toHaveProperty("runs");
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
    const framesPromise = readFrames(res.body!, 2); // snapshot + activity

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
    const activity = activityFrame!.data as { sessions: unknown[] };
    expect(Array.isArray(activity.sessions)).toBe(true);
  }, 6000);
});
