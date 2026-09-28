import { tmpDir, TOKEN, testConfig, makeControllableFakeSpawn, req } from "./run.fixture";
import { describe, it, expect } from "vitest";
import { createRunHandler } from "../src/app/api/run/route";

describe("POST /api/run — exit signal", () => {
  it("records the signal when the child is terminated by one, rather than collapsing it into exitCode 1", async () => {
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
    await new Promise((r) => setTimeout(r, 0));

    controllable.emitExit(null, "SIGTERM");
    await pending;

    const { readRuns } = await import("../src/lib/runlog");
    const rec = readRuns(10, { runsDir })[0];
    expect(rec.signal).toBe("SIGTERM");
  });
});
