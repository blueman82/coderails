import { tmpDir, TOKEN, makeHandler, req } from "./run.fixture";
import { describe, it, expect } from "vitest";
import { readFileSync, existsSync } from "node:fs";

describe("POST /api/run — run log", () => {
  it("appends a JSONL RunRecord at start and finish, and returns a runId", async () => {
    const runsDir = tmpDir("dashboard-run-runs-");
    const { handler } = makeHandler({ runsDir });
    const res = await handler(req({ token: TOKEN, button: "wiki-lint" }));
    expect(res.status).toBe(200);
    const body = (await res.json()) as { runId: string };
    expect(typeof body.runId).toBe("string");
    expect(body.runId.length).toBeGreaterThan(0);

    const { readRuns } = await import("../src/lib/runlog");
    const runs = readRuns(10, { runsDir });
    const rec = runs.find((r) => r.runId === body.runId);
    expect(rec).toBeDefined();
    expect(rec?.button).toBe("wiki-lint");
    expect(rec?.endedAt).toBeDefined();
    expect(rec?.exitCode).toBe(0);
  });

  it("writes stdout/stderr to the run's output log file", async () => {
    const runsDir = tmpDir("dashboard-run-runs-");
    const { handler } = makeHandler({ runsDir });
    const res = await handler(req({ token: TOKEN, button: "wiki-lint" }));
    const body = (await res.json()) as { runId: string };
    const { readRuns } = await import("../src/lib/runlog");
    const rec = readRuns(10, { runsDir }).find((r) => r.runId === body.runId);
    expect(rec?.outputPath).toBeDefined();
    expect(existsSync(rec!.outputPath)).toBe(true);
    const contents = readFileSync(rec!.outputPath, "utf-8");
    expect(contents).toContain("ok");
  });
});
