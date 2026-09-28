import { tmpDir, TOKEN, testConfig, makeControllableFakeSpawn, req } from "./run.fixture";
import { describe, it, expect } from "vitest";
import { existsSync } from "node:fs";
import { join } from "node:path";
import { createRunHandler } from "../src/app/api/run/route";

describe("POST /api/run — spawn 'error' event (regression for the hang/lock-leak bug)", () => {
  it("resolves the request, releases the lock, and records the failure when spawn fires 'error' instead of 'exit'", async () => {
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

    const spawnError = Object.assign(new Error("spawn codex ENOENT"), { code: "ENOENT" });
    controllable.emitError(spawnError);

    // The request must resolve — before this fix, an "error"-only failure
    // left the promise pending forever because resolve() lived exclusively
    // in the "exit" handler.
    const res = await Promise.race([
      pending,
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error("handler did not resolve after spawn 'error'")), 1000)
      ),
    ]);
    expect(res.status).toBe(200);

    expect(existsSync(join(locksDir, "wiki-lint.lock"))).toBe(false);

    const { readRuns } = await import("../src/lib/runlog");
    const rec = readRuns(10, { runsDir })[0];
    expect(rec.endedAt).toBeDefined();
    expect(rec.exitCode).toBe(-1);
  });

  it("does not double-settle if both 'error' and 'exit' fire (defensive: some Node failure modes can emit both)", async () => {
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

    controllable.emitError(new Error("spawn failed"));
    controllable.emitExit(1);

    const res = await pending;
    expect(res.status).toBe(200);

    const { readRuns } = await import("../src/lib/runlog");
    const runs = readRuns(10, { runsDir });
    expect(runs.length).toBe(1);
    // The first-to-fire ("error") wins: exitCode stays -1, not overwritten
    // by the later "exit" (1).
    expect(runs[0].exitCode).toBe(-1);
  });
});
