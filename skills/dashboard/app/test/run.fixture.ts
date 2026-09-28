import { afterEach, vi } from "vitest";

import { mkdtempSync, rmSync } from "node:fs";

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
    stdout: { on() { } },
    stderr: { on() { } },
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

export { tmpDir, TOKEN, testConfig, makeHangingSpawn, makeControllableFakeSpawn, makeHandler, req, reqNoOrigin };
