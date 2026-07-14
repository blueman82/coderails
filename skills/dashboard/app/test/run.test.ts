import { describe, it, expect, afterEach, vi } from "vitest";
import { mkdtempSync, rmSync, readFileSync, existsSync, mkdirSync, utimesSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRunHandler } from "../src/app/api/run/route";
import type { DashboardConfig } from "../src/lib/config";
import { createRunOutputBus } from "../src/lib/runOutputBus";

const tmpDirs: string[] = [];

function tmpDir(prefix: string): string {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  tmpDirs.push(dir);
  return dir;
}

afterEach(() => {
  vi.restoreAllMocks();
  for (const dir of tmpDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

const TOKEN = "test-token-abc123";

function testConfig(): DashboardConfig {
  return {
    repos: [],
    wikiPaths: [],
    buttons: [
      {
        name: "wiki-lint",
        label: "WIKI LINT",
        command: "/coderails:wiki-lint",
        cwd: "/Users/harrison/Github/coderails",
        profile: "standard",
      },
      {
        name: "with-input",
        label: "WITH INPUT",
        command: "/coderails:assumptions",
        cwd: "/Users/harrison/Github/coderails",
        profile: "read-only",
        inputAllowed: true,
      },
      {
        name: "ask",
        label: "ASK",
        command: "",
        cwd: "/Users/harrison/Github/coderails",
        profile: "standard",
        inputAllowed: true,
      },
    ],
  };
}

// A fake spawn-shaped fn that never actually spawns a process: it records
// the args it was called with, emits "ok" on stdout, and immediately fires
// exit with code 0. Mirrors route.ts's ChildProcessLike/SpawnFn seam
// (stdout/stderr as chunk-emitting streams, an "exit" event carrying the
// numeric code) closely enough for the route to treat it identically to a
// real node:child_process.spawn result.
function makeFakeSpawn() {
  const calls: { command: string; args: unknown; options: unknown }[] = [];
  const fn = vi.fn((command: string, args: unknown, options: unknown) => {
    calls.push({ command, args, options });
    const stdoutListeners: ((chunk: Buffer | string) => void)[] = [];
    const exitListeners: ((code: number | null) => void)[] = [];
    return {
      stdout: {
        on(event: "data", listener: (chunk: Buffer | string) => void) {
          if (event === "data") stdoutListeners.push(listener);
        },
      },
      stderr: {
        on() {
          // no stderr output in the fake — nothing to emit
        },
      },
      on(event: "exit", listener: (code: number | null) => void) {
        if (event === "exit") {
          exitListeners.push(listener);
          // fire synchronously, after listeners are registered, mirroring
          // the previous fake execFile's immediate-callback semantics
          for (const l of stdoutListeners) l("ok");
          for (const l of exitListeners) l(0);
        }
      },
    };
  });
  return { fn, calls };
}

// A fake spawn-shaped fn that simulates a still-running process: it never
// fires "exit", so the lock is held for the duration of the test.
function makeHangingSpawn() {
  return vi.fn(() => ({
    stdout: { on() {} },
    stderr: { on() {} },
    on() {
      // exit listener registered but never invoked — process never exits
    },
  }));
}

// A fake spawn-shaped fn whose stdout/stderr/exit/error firing is entirely
// under the test's control (nothing fires until the test calls one of the
// returned methods) — unlike makeFakeSpawn, which fires one chunk then exits
// synchronously and so can't distinguish incremental delivery from
// buffer-until-exit. Used to prove: (a) a chunk is observable (log file
// written, bus published) before a later chunk/exit arrives, and (b) the
// child "error" event is handled independently of "exit".
function makeControllableFakeSpawn() {
  const calls: { command: string; args: unknown; options: unknown }[] = [];
  let stdoutListener: ((chunk: Buffer | string) => void) | undefined;
  let stderrListener: ((chunk: Buffer | string) => void) | undefined;
  let exitListener: ((code: number | null, signal: NodeJS.Signals | null) => void) | undefined;
  let errorListener: ((err: Error) => void) | undefined;

  const fn = vi.fn((command: string, args: unknown, options: unknown) => {
    calls.push({ command, args, options });
    return {
      stdout: {
        on(event: "data", listener: (chunk: Buffer | string) => void) {
          if (event === "data") stdoutListener = listener;
        },
      },
      stderr: {
        on(event: "data", listener: (chunk: Buffer | string) => void) {
          if (event === "data") stderrListener = listener;
        },
      },
      on(event: "exit" | "error", listener: never) {
        if (event === "exit") exitListener = listener;
        if (event === "error") errorListener = listener;
      },
    };
  });

  return {
    fn,
    calls,
    emitStdout(chunk: string) {
      stdoutListener?.(chunk);
    },
    emitStderr(chunk: string) {
      stderrListener?.(chunk);
    },
    emitExit(code: number | null, signal: NodeJS.Signals | null = null) {
      exitListener?.(code, signal);
    },
    emitError(err: Error) {
      errorListener?.(err);
    },
  };
}

function makeHandler(overrides: {
  config?: DashboardConfig;
  token?: string;
  spawnImpl?: ReturnType<typeof makeFakeSpawn>["fn"];
  locksDir?: string;
  runsDir?: string;
} = {}) {
  const locksDir = overrides.locksDir ?? tmpDir("dashboard-run-locks-");
  const runsDir = overrides.runsDir ?? tmpDir("dashboard-run-runs-");
  const fake = overrides.spawnImpl ? undefined : makeFakeSpawn();
  const spawnImpl = overrides.spawnImpl ?? fake!.fn;
  const handler = createRunHandler({
    config: overrides.config ?? testConfig(),
    token: overrides.token ?? TOKEN,
    spawnImpl: spawnImpl as never,
    locksDir,
    runsDir,
  });
  return { handler, locksDir, runsDir, spawnImpl, fake };
}

function req(body: unknown, headers: Record<string, string> = {}): Request {
  return new Request("http://127.0.0.1:3000/api/run", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      origin: "http://127.0.0.1:3000",
      host: "127.0.0.1:3000",
      ...headers,
    },
    body: JSON.stringify(body),
  });
}

// Like req(), but never sets an Origin header at all (not even an empty
// string) — for testing the no-Origin/non-browser-client path, which is
// distinct from an Origin header that is present but invalid.
function reqNoOrigin(body: unknown, host = "127.0.0.1:3000"): Request {
  return new Request("http://127.0.0.1:3000/api/run", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      host,
    },
    body: JSON.stringify(body),
  });
}

describe("POST /api/run — token", () => {
  it("rejects a missing token with 401 and does not spawn", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(req({ button: "wiki-lint" }));
    expect(res.status).toBe(401);
    expect(fake!.calls.length).toBe(0);
  });

  it("rejects a wrong token with 401 and does not spawn", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(req({ token: "wrong", button: "wiki-lint" }));
    expect(res.status).toBe(401);
    expect(fake!.calls.length).toBe(0);
  });

  it("never includes the token in a response body", async () => {
    const { handler } = makeHandler();
    const res = await handler(req({ token: "wrong", button: "wiki-lint" }));
    const text = await res.text();
    expect(text).not.toContain(TOKEN);
  });
});

describe("POST /api/run — origin/host", () => {
  it("rejects a non-localhost Origin with 403 and does not spawn", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(
      req({ token: TOKEN, button: "wiki-lint" }, { origin: "https://evil.example" })
    );
    expect(res.status).toBe(403);
    expect(fake!.calls.length).toBe(0);
  });

  it("rejects a non-localhost Host with 403 and does not spawn", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(
      req({ token: TOKEN, button: "wiki-lint" }, { host: "evil.example", origin: "http://evil.example" })
    );
    expect(res.status).toBe(403);
    expect(fake!.calls.length).toBe(0);
  });

  it("accepts an http://localhost origin", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(
      req({ token: TOKEN, button: "wiki-lint" }, { origin: "http://localhost:3000", host: "localhost:3000" })
    );
    expect(res.status).toBe(200);
    expect(fake!.calls.length).toBe(1);
  });

  it("accepts a request with NO Origin header at all (non-browser client), provided Host is localhost", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(reqNoOrigin({ token: TOKEN, button: "wiki-lint" }, "127.0.0.1:3000"));
    expect(res.status).toBe(200);
    expect(fake!.calls.length).toBe(1);
  });

  it("rejects an Origin header literally 'null' even though Host is localhost", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(req({ token: TOKEN, button: "wiki-lint" }, { origin: "null" }));
    expect(res.status).toBe(403);
    expect(fake!.calls.length).toBe(0);
  });

  it("accepts a bracketed IPv6 Host [::1] consistently with an IPv6 Origin", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(
      req({ token: TOKEN, button: "wiki-lint" }, { origin: "http://[::1]:3000", host: "[::1]:3000" })
    );
    expect(res.status).toBe(200);
    expect(fake!.calls.length).toBe(1);
  });
});

describe("POST /api/run — button validation", () => {
  it("rejects an undeclared button name with 404 and does not spawn", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(req({ token: TOKEN, button: "does-not-exist" }));
    expect(res.status).toBe(404);
    expect(fake!.calls.length).toBe(0);
  });

  it("rejects input on a button without inputAllowed with 400 and does not spawn", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(req({ token: TOKEN, button: "wiki-lint", input: "hello" }));
    expect(res.status).toBe(400);
    expect(fake!.calls.length).toBe(0);
  });

  it("accepts input on a button with inputAllowed", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(req({ token: TOKEN, button: "with-input", input: "hello" }));
    expect(res.status).toBe(200);
    expect(fake!.calls.length).toBe(1);
  });

  it("rejects input starting with '-' (flag smuggling) with 400 and does not spawn", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(
      req({ token: TOKEN, button: "with-input", input: "--dangerously-skip-permissions" })
    );
    expect(res.status).toBe(400);
    expect(fake!.calls.length).toBe(0);
  });

  it("rejects an empty-command button pressed with no input (empty prompt) with a clean 400, not a 500, and does not spawn", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(req({ token: TOKEN, button: "ask" }));
    expect(res.status).toBe(400);
    expect(fake!.calls.length).toBe(0);
  });

  it("rejects an empty-command button pressed with empty-string input (empty prompt) with a clean 400, not a 500, and does not spawn", async () => {
    const { handler, fake } = makeHandler();
    const res = await handler(req({ token: TOKEN, button: "ask", input: "" }));
    expect(res.status).toBe(400);
    expect(fake!.calls.length).toBe(0);
  });
});

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

describe("POST /api/run — spawn shape", () => {
  it("calls spawn with 'claude' and an argv ARRAY (never a string)", async () => {
    const { handler, fake } = makeHandler();
    await handler(req({ token: TOKEN, button: "wiki-lint" }));
    expect(fake!.calls.length).toBe(1);
    expect(fake!.calls[0].command).toBe("claude");
    expect(Array.isArray(fake!.calls[0].args)).toBe(true);
  });

  it("passes the button's cwd to spawn's options", async () => {
    const { handler, fake } = makeHandler();
    await handler(req({ token: TOKEN, button: "wiki-lint" }));
    expect(fake!.calls[0].options).toMatchObject({ cwd: "/Users/harrison/Github/coderails" });
  });

  it("sets CODERAILS_HEADLESS_RUN=1 in the spawned child's env, so the discipline\n     Stop hooks (check_confidence_labels.sh / check_verify_loop.sh) exempt this run", async () => {
    const { handler, fake } = makeHandler();
    await handler(req({ token: TOKEN, button: "wiki-lint" }));
    const options = fake!.calls[0].options as { env?: Record<string, string | undefined> };
    expect(options.env).toMatchObject({ CODERAILS_HEADLESS_RUN: "1" });
  });

  it("builds argv via buildArgv's mapping (read-only button gets --allowedTools)", async () => {
    const { handler, fake } = makeHandler();
    await handler(req({ token: TOKEN, button: "with-input", input: "hello" }));
    const args = fake!.calls[0].args as string[];
    expect(args).toContain("--allowedTools");
    expect(args[args.length - 1]).toBe("/coderails:assumptions hello");
  });
});

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

    const spawnError = Object.assign(new Error("spawn claude ENOENT"), { code: "ENOENT" });
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
