import { describe, it, expect, afterEach, vi } from "vitest";
import { mkdtempSync, rmSync, readFileSync, existsSync, mkdirSync, utimesSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRunHandler } from "../src/app/api/run/route";
import type { DashboardConfig } from "../src/lib/config";

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
    memoryPaths: [],
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
    ],
  };
}

// A fake execFile-shaped fn that never actually spawns a process: it
// immediately invokes the callback with success, after recording the args it
// was called with. Mirrors node:child_process.execFile's callback signature
// closely enough for the route to treat it identically.
function makeFakeExecFile() {
  const calls: { command: string; args: unknown; options: unknown }[] = [];
  const fn = vi.fn(
    (
      command: string,
      args: unknown,
      options: unknown,
      callback: (err: Error | null, stdout: string, stderr: string) => void
    ) => {
      calls.push({ command, args, options });
      callback(null, "ok", "");
      return { pid: 1234 };
    }
  );
  return { fn, calls };
}

function makeHandler(overrides: {
  config?: DashboardConfig;
  token?: string;
  execFileImpl?: ReturnType<typeof makeFakeExecFile>["fn"];
  locksDir?: string;
  runsDir?: string;
} = {}) {
  const locksDir = overrides.locksDir ?? tmpDir("dashboard-run-locks-");
  const runsDir = overrides.runsDir ?? tmpDir("dashboard-run-runs-");
  const fake = overrides.execFileImpl ? undefined : makeFakeExecFile();
  const execFileImpl = overrides.execFileImpl ?? fake!.fn;
  const handler = createRunHandler({
    config: overrides.config ?? testConfig(),
    token: overrides.token ?? TOKEN,
    execFileImpl: execFileImpl as never,
    locksDir,
    runsDir,
  });
  return { handler, locksDir, runsDir, execFileImpl, fake };
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
});

describe("POST /api/run — concurrency lock", () => {
  it("returns 409 and does not spawn a second run while the first holds the lock", async () => {
    const locksDir = tmpDir("dashboard-run-locks-");
    const runsDir = tmpDir("dashboard-run-runs-");
    // execFile that never calls back — simulates a still-running process so
    // the lock is held for the duration of this test.
    const hangingExecFile = vi.fn(() => ({ pid: 1 })) as unknown as (
      ...args: unknown[]
    ) => unknown;
    const { handler } = makeHandler({ execFileImpl: hangingExecFile as never, locksDir, runsDir });

    // Fire-and-forget: this promise never resolves because the fake
    // execFile never calls its callback, simulating a still-running
    // process. We intentionally don't await it.
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
});

describe("POST /api/run — spawn shape", () => {
  it("calls execFile with 'claude' and an argv ARRAY (never a string)", async () => {
    const { handler, fake } = makeHandler();
    await handler(req({ token: TOKEN, button: "wiki-lint" }));
    expect(fake!.calls.length).toBe(1);
    expect(fake!.calls[0].command).toBe("claude");
    expect(Array.isArray(fake!.calls[0].args)).toBe(true);
  });

  it("passes the button's cwd to execFile's options", async () => {
    const { handler, fake } = makeHandler();
    await handler(req({ token: TOKEN, button: "wiki-lint" }));
    expect(fake!.calls[0].options).toMatchObject({ cwd: "/Users/harrison/Github/coderails" });
  });

  it("builds argv via buildArgv's mapping (read-only button gets --allowedTools)", async () => {
    const { handler, fake } = makeHandler();
    await handler(req({ token: TOKEN, button: "with-input", input: "hello" }));
    const args = fake!.calls[0].args as string[];
    expect(args).toContain("--allowedTools");
    expect(args[args.length - 1]).toBe("hello");
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
