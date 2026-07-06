import { execFile as execFileReal } from "node:child_process";
import { randomBytes } from "node:crypto";
import { mkdirSync, statSync, writeFileSync, unlinkSync, appendFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { buildArgv } from "../../../lib/argv";
import { loadConfig, type DashboardConfig } from "../../../lib/config";
import { appendRun, mintToken, type RunRecord } from "../../../lib/runlog";

const STALE_LOCK_MS = 24 * 60 * 60 * 1000;
const DEFAULT_LOCKS_DIR = join(homedir(), ".claude", "coderails-dashboard", "locks");
const DEFAULT_RUNS_DIR = join(homedir(), ".claude", "coderails-dashboard", "runs");

// Matches ExecFile's callback-style signature closely enough for this route
// (and its tests) to treat a real node:child_process.execFile and a fake
// identically: (command, args, options, callback) => ChildProcess-like.
type ExecFileFn = (
  command: string,
  args: readonly string[],
  options: { cwd: string },
  callback: (error: Error | null, stdout: string, stderr: string) => void
) => unknown;

export interface RunHandlerDeps {
  config: DashboardConfig;
  token: string;
  execFileImpl?: ExecFileFn;
  locksDir?: string;
  runsDir?: string;
}

// hostname, as returned by `new URL(...).hostname`, always has IPv6 brackets
// stripped ("::1", never "[::1]"). A bare Host header does not, so callers
// extracting a hostname from Host must strip brackets themselves before
// comparing against this.
function isLocalhost(hostname: string): boolean {
  return hostname === "localhost" || hostname === "127.0.0.1" || hostname === "::1";
}

// Host: "[::1]:3000" → "::1" (brackets stripped, port dropped). Host:
// "127.0.0.1:3000" → "127.0.0.1". A bare IPv6 host with no port and no
// brackets shouldn't occur in a real Host header, so no special-case for it.
function hostnameFromHostHeader(host: string): string {
  if (host.startsWith("[")) {
    const end = host.indexOf("]");
    return end === -1 ? host : host.slice(1, end);
  }
  return host.split(":")[0];
}

// Any doubt → reject, with ONE deliberate exception: a request with no
// Origin header at all (as opposed to one present but invalid) is treated as
// a non-browser client (curl, a CLI, a same-machine script) rather than
// rejected — browsers always send Origin on a cross-origin fetch, so the
// absence of the header is not itself a spoofable signal, and Host is still
// required and validated. An Origin header that IS present but doesn't
// resolve to localhost (including the literal string "null", which browsers
// send for opaque/sandboxed origins) is rejected — any open browser tab can
// reach 127.0.0.1, so this is the wall against cross-origin/DNS-rebinding
// requests reaching the run endpoint.
function isLocalOrigin(request: Request): boolean {
  const host = request.headers.get("host");
  if (!host) return false;
  if (!isLocalhost(hostnameFromHostHeader(host))) return false;

  const origin = request.headers.get("origin");
  if (origin === null) return true;

  let originHost: string;
  try {
    originHost = new URL(origin).hostname;
  } catch {
    return false;
  }
  return isLocalhost(originHost);
}

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function lockPathFor(locksDir: string, button: string): string {
  return join(locksDir, `${button}.lock`);
}

function isStale(lockPath: string): boolean {
  let stat;
  try {
    stat = statSync(lockPath);
  } catch {
    return false;
  }
  return Date.now() - stat.mtimeMs >= STALE_LOCK_MS;
}

// Acquires the lock by attempting an EXCLUSIVE create ("wx": fails with
// EEXIST if the file already exists). The create itself IS the check —
// there is no separate "is it held" read before the write, so two worker
// processes racing to acquire the same lock cannot both succeed: the
// filesystem serializes the two open(O_EXCL) calls and exactly one of them
// gets ENOENT-turned-success while the other gets EEXIST. (The prior
// implementation did statSync-then-writeFileSync, which has a window
// between the two calls where both processes could observe "absent" and
// both write.)
//
// A lock file older than 24h is treated as abandoned (e.g. left behind by a
// crashed server) and ignored: on EEXIST, if the existing lock is stale we
// unlink it and retry the exclusive create exactly once. If that retry also
// hits EEXIST (a genuine concurrent acquisition, or the file reappeared),
// the lock is held — return false rather than looping.
function acquireLock(lockPath: string): boolean {
  try {
    writeFileSync(lockPath, String(process.pid), { flag: "wx" });
    return true;
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code !== "EEXIST") throw err;
  }

  if (isStale(lockPath)) {
    try {
      unlinkSync(lockPath);
    } catch {
      // lost the race to remove it; fall through to the retry below anyway
    }
    try {
      writeFileSync(lockPath, String(process.pid), { flag: "wx" });
      return true;
    } catch (err) {
      if ((err as NodeJS.ErrnoException).code !== "EEXIST") throw err;
      return false;
    }
  }

  return false;
}

export function createRunHandler(deps: RunHandlerDeps) {
  const execFileImpl = deps.execFileImpl ?? (execFileReal as unknown as ExecFileFn);
  const locksDir = deps.locksDir ?? DEFAULT_LOCKS_DIR;
  const runsDir = deps.runsDir ?? DEFAULT_RUNS_DIR;

  return async function POST(request: Request): Promise<Response> {
    if (!isLocalOrigin(request)) {
      return jsonResponse(403, { error: "forbidden" });
    }

    let payload: { token?: unknown; button?: unknown; input?: unknown };
    try {
      payload = (await request.json()) as typeof payload;
    } catch {
      return jsonResponse(400, { error: "invalid JSON body" });
    }

    if (typeof payload.token !== "string" || payload.token !== deps.token) {
      return jsonResponse(401, { error: "unauthorized" });
    }

    if (typeof payload.button !== "string") {
      return jsonResponse(404, { error: "unknown button" });
    }
    const button = deps.config.buttons.find((b) => b.name === payload.button);
    if (!button) {
      return jsonResponse(404, { error: "unknown button" });
    }

    const input = payload.input;
    if (input !== undefined) {
      if (typeof input !== "string" || !button.inputAllowed) {
        return jsonResponse(400, { error: "input not allowed for this button" });
      }
    }

    // buildArgv throws on flag-smuggling input (e.g. "--dangerously-skip-
    // permissions") — reject with 400 before ever touching the lock.
    let argv: string[];
    try {
      argv = buildArgv(button, typeof input === "string" ? input : undefined);
    } catch {
      return jsonResponse(400, { error: "invalid input" });
    }

    mkdirSync(locksDir, { recursive: true });
    const lockPath = lockPathFor(locksDir, button.name);
    if (!acquireLock(lockPath)) {
      return jsonResponse(409, { error: "already running" });
    }

    const runId = randomBytes(8).toString("hex");
    mkdirSync(runsDir, { recursive: true });
    const outputPath = join(runsDir, `${runId}.log`);
    const startedAt = Date.now();

    const startRecord: RunRecord = {
      runId,
      button: button.name,
      argv,
      cwd: button.cwd,
      profile: button.profile,
      startedAt,
      outputPath,
    };
    appendRun(startRecord, { runsDir });

    await new Promise<void>((resolve) => {
      execFileImpl("claude", argv, { cwd: button.cwd }, (error, stdout, stderr) => {
        appendFileSync(outputPath, stdout + stderr);
        const errorCode = (error as { code?: unknown } | null)?.code;
        const exitCode = !error ? 0 : typeof errorCode === "number" ? errorCode : 1;
        appendRun({ ...startRecord, endedAt: Date.now(), exitCode }, { runsDir });
        try {
          unlinkSync(lockPath);
        } catch {
          // already removed; nothing to clean up
        }
        resolve();
      });
    });

    return jsonResponse(200, { runId });
  };
}

let cachedConfig: DashboardConfig | undefined;
let cachedToken: string | undefined;

function getConfig(): DashboardConfig {
  if (!cachedConfig) cachedConfig = loadConfig();
  return cachedConfig;
}

function getToken(): string {
  if (!cachedToken) cachedToken = mintToken();
  return cachedToken;
}

// Exported for the server-render page (Task 8/9) to embed the token — never
// exposed via any API response body.
export function getRunToken(): string {
  return getToken();
}

export async function POST(request: Request): Promise<Response> {
  return createRunHandler({ config: getConfig(), token: getToken() })(request);
}
