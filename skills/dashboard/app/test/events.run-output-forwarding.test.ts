import { tmpDir, testConfig, req, readFramesUntil } from "./events.fixture";
import { describe, it, expect } from "vitest";
import { createEventsHandler } from "../src/app/api/events/route";
import { runOutputBus } from "../src/lib/runOutputBus";

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
