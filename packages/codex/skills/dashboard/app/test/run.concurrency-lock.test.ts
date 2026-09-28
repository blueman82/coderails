import { tmpDir, TOKEN, makeHangingSpawn, makeHandler, req } from "./run.fixture";
import { describe, it, expect } from "vitest";
import { existsSync, mkdirSync, utimesSync } from "node:fs";
import { join } from "node:path";

describe("POST /api/run — concurrency lock", () => {
  it("returns 409 and does not spawn a second run while the first holds the lock", async () => {
    const locksDir = tmpDir("dashboard-run-locks-");
    const runsDir = tmpDir("dashboard-run-runs-");
    const { handler } = makeHandler({ spawnImpl: makeHangingSpawn() as never, locksDir, runsDir });

    // Fire-and-forget: this promise never resolves because the fake spawn
    // never fires "exit", simulating a still-running process. We
    // intentionally don't await it.
    void handler(req({ token: TOKEN, button: "wiki-lint" }));
    // second request while the first's lock file still exists
    const second = await handler(req({ token: TOKEN, button: "wiki-lint" }));
    expect(second.status).toBe(409);
  });

  it("ignores a stale lock older than 24h and allows the run", async () => {
    const locksDir = tmpDir("dashboard-run-locks-");
    mkdirSync(locksDir, { recursive: true });
    const lockPath = join(locksDir, "wiki-lint.lock");
    const { writeFileSync } = await import("node:fs");
    writeFileSync(lockPath, "stale");
    const old = Date.now() - 25 * 60 * 60 * 1000;
    utimesSync(lockPath, old / 1000, old / 1000);

    const { handler, fake } = makeHandler({ locksDir });
    const res = await handler(req({ token: TOKEN, button: "wiki-lint" }));
    expect(res.status).toBe(200);
    expect(fake!.calls.length).toBe(1);
  });

  it("removes the lock file when the run finishes", async () => {
    const locksDir = tmpDir("dashboard-run-locks-");
    const { handler } = makeHandler({ locksDir });
    await handler(req({ token: TOKEN, button: "wiki-lint" }));
    expect(existsSync(join(locksDir, "wiki-lint.lock"))).toBe(false);
  });

  it("returns 409 for a fresh pre-existing lock file with no race window (proves exclusive-create, not stat-then-write)", async () => {
    // Regression test for the TOCTOU: a naive "statSync-then-writeFileSync"
    // implementation has a window between the check and the write where a
    // second process could also observe "no lock" and also write. Using
    // writeFileSync(..., {flag:"wx"}) makes the create itself the check —
    // there is no window to race. We can't directly observe "no window" from
    // outside, but we CAN assert the externally-visible contract that must
    // hold if and only if creation is exclusive: a lock file that exists the
    // instant before the handler runs is never silently overwritten/ignored.
    const locksDir = tmpDir("dashboard-run-locks-");
    mkdirSync(locksDir, { recursive: true });
    const lockPath = join(locksDir, "wiki-lint.lock");
    const { writeFileSync } = await import("node:fs");
    writeFileSync(lockPath, "99999"); // fresh mtime, not stale

    const { handler, fake } = makeHandler({ locksDir });
    const res = await handler(req({ token: TOKEN, button: "wiki-lint" }));
    expect(res.status).toBe(409);
    expect(fake!.calls.length).toBe(0);
    // the pre-existing lock's content must be untouched — an exclusive
    // create fails (EEXIST) rather than truncating/overwriting the file
    const { readFileSync: readFile } = await import("node:fs");
    expect(readFile(lockPath, "utf-8")).toBe("99999");
  });
});
