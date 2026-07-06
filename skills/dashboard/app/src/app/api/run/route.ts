import { execFile as execFileReal } from "node:child_process";
import { randomBytes } from "node:crypto";
import { mkdirSync, statSync, writeFileSync, unlinkSync, appendFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { buildArgv } from "../../../lib/argv";
import { loadConfig, type DashboardConfig } from "../../../lib/config";
import { isLocalOrigin } from "../../../lib/requestGuard";
import { appendRun, getRunToken, type RunRecord } from "../../../lib/runlog";

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

function getConfig(): DashboardConfig {
  if (!cachedConfig) cachedConfig = loadConfig();
  return cachedConfig;
}

// Token caching lives in runlog.ts, not here — see getRunToken's comment
// there for why a route.ts-local cache is unsafe to share with page.tsx.
// Re-exported so existing callers importing getRunToken from this route
// module keep working.
export { getRunToken };

export async function POST(request: Request): Promise<Response> {
  return createRunHandler({ config: getConfig(), token: getRunToken() })(request);
}
