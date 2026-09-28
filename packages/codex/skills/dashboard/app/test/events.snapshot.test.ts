import { tmpDir, testConfig, req, readFrames, readRawText } from "./events.fixture";
import { describe, it, expect } from "vitest";
import { createEventsHandler } from "../src/app/api/events/route";

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
