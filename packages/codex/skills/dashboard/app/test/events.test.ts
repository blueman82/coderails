import { tmpDir, testConfig, req } from "./events.fixture";
import { describe, it, expect } from "vitest";
import { createEventsHandler } from "../src/app/api/events/route";

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
