import { tmpDir, TOKEN, makeHandler, req } from "./run.fixture";
import { describe, it, expect } from "vitest";
import { statSync, chmodSync } from "node:fs";
import { join } from "node:path";

describe("POST /api/run — file/dir permissions", () => {
  it("writes the per-run output log mode 0600 — not world/group readable (it holds full prompts and model output)", async () => {
    const { handler, runsDir } = makeHandler();
    const res = await handler(req({ token: TOKEN, button: "wiki-lint" }));
    expect(res.status).toBe(200);

    const { readRuns } = await import("../src/lib/runlog");
    const outputPath = readRuns(10, { runsDir })[0].outputPath;
    expect(statSync(outputPath).mode & 0o777).toBe(0o600);
  });

  it("creates a not-yet-existing locks dir mode 0700 — not world/group readable", async () => {
    // A path under a tmpDir() (already 0700 from mkdtempSync) rather than
    // tmpDir() itself: mkdirSync's mode arg only takes effect on a dir it
    // actually creates, so the assertion must exercise that path, not an
    // already-0700 dir mkdirSync leaves untouched either way.
    const locksDir = join(tmpDir("dashboard-run-locks-parent-"), "locks");
    const { handler } = makeHandler({ locksDir });
    const res = await handler(req({ token: TOKEN, button: "wiki-lint" }));
    expect(res.status).toBe(200);
    expect(statSync(locksDir).mode & 0o777).toBe(0o700);
  });

  it("tightens an already-existing locks dir's mode to 0700, since mkdirSync's mode arg is a no-op on a dir that already exists", async () => {
    const locksDir = tmpDir("dashboard-run-locks-");
    // chmodSync sets the mode exactly as given (unlike mkdirSync's mode arg,
    // which the umask could mask down to 0700 anyway), so this fixture is
    // reliably loose regardless of this process's umask.
    chmodSync(locksDir, 0o755);
    expect(statSync(locksDir).mode & 0o777).toBe(0o755);

    const { handler } = makeHandler({ locksDir });
    const res = await handler(req({ token: TOKEN, button: "wiki-lint" }));
    expect(res.status).toBe(200);

    expect(statSync(locksDir).mode & 0o777).toBe(0o700);
  });
});
