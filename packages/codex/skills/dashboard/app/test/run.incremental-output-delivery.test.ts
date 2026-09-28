import { tmpDir, TOKEN, testConfig, makeControllableFakeSpawn, req } from "./run.fixture";
import { describe, it, expect } from "vitest";
import { readFileSync, existsSync } from "node:fs";
import { createRunHandler } from "../src/app/api/run/route";
import { createRunOutputBus } from "../src/lib/runOutputBus";

describe("POST /api/run — incremental output delivery", () => {
  it("makes chunk1 observable in the log file before chunk2 arrives or the process exits (proves streaming, not buffer-until-exit)", async () => {
    const runsDir = tmpDir("dashboard-run-runs-");
    const locksDir = tmpDir("dashboard-run-locks-");
    const controllable = makeControllableFakeSpawn();
    const handler = createRunHandler({
      config: testConfig(),
      token: TOKEN,
      spawnImpl: controllable.fn as never,
      locksDir,
      runsDir,
    });

    const pending = handler(req({ token: TOKEN, button: "wiki-lint" }));

    // Let the handler register its listeners before emitting.
    await new Promise((r) => setTimeout(r, 0));
    controllable.emitStdout("chunk1\n");
    await new Promise((r) => setTimeout(r, 0));

    // A regression to "buffer until exit" would mean the log file doesn't
    // exist yet / doesn't contain chunk1 at this point, since exit hasn't
    // fired. We can find the output path from the still-pending run's
    // start record on disk.
    const { readRuns } = await import("../src/lib/runlog");
    const startedRuns = readRuns(10, { runsDir });
    expect(startedRuns.length).toBe(1);
    const outputPath = startedRuns[0].outputPath;
    expect(existsSync(outputPath)).toBe(true);
    expect(readFileSync(outputPath, "utf-8")).toBe("chunk1\n");

    controllable.emitStdout("chunk2\n");
    await new Promise((r) => setTimeout(r, 0));
    expect(readFileSync(outputPath, "utf-8")).toBe("chunk1\nchunk2\n");

    controllable.emitExit(0);
    await pending;
    expect(readFileSync(outputPath, "utf-8")).toBe("chunk1\nchunk2\n");
  });

  it("publishes each chunk on the injected RunOutputBus as it arrives, as {runId, chunk}", async () => {
    const runsDir = tmpDir("dashboard-run-runs-");
    const locksDir = tmpDir("dashboard-run-locks-");
    const controllable = makeControllableFakeSpawn();
    const bus = createRunOutputBus();
    const published: { runId: string; chunk: string }[] = [];
    bus.subscribe((event) => published.push(event));

    const handler = createRunHandler({
      config: testConfig(),
      token: TOKEN,
      spawnImpl: controllable.fn as never,
      locksDir,
      runsDir,
      runOutputBus: bus,
    });

    const pending = handler(req({ token: TOKEN, button: "wiki-lint" }));
    await new Promise((r) => setTimeout(r, 0));

    controllable.emitStdout("hello\n");
    await new Promise((r) => setTimeout(r, 0));

    const { readRuns } = await import("../src/lib/runlog");
    const runId = readRuns(10, { runsDir })[0].runId;

    expect(published).toEqual([{ runId, chunk: "hello\n" }]);

    controllable.emitExit(0);
    await pending;
  });

  it("routes stderr chunks through the same append/publish path as stdout", async () => {
    const runsDir = tmpDir("dashboard-run-runs-");
    const locksDir = tmpDir("dashboard-run-locks-");
    const controllable = makeControllableFakeSpawn();
    const bus = createRunOutputBus();
    const published: string[] = [];
    bus.subscribe((event) => published.push(event.chunk));

    const handler = createRunHandler({
      config: testConfig(),
      token: TOKEN,
      spawnImpl: controllable.fn as never,
      locksDir,
      runsDir,
      runOutputBus: bus,
    });

    const pending = handler(req({ token: TOKEN, button: "wiki-lint" }));
    await new Promise((r) => setTimeout(r, 0));

    controllable.emitStderr("uh oh\n");
    controllable.emitExit(0);
    await pending;

    const { readRuns } = await import("../src/lib/runlog");
    const outputPath = readRuns(10, { runsDir })[0].outputPath;
    expect(readFileSync(outputPath, "utf-8")).toContain("uh oh\n");
    expect(published).toContain("uh oh\n");
  });
});
