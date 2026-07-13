import { spawn as spawnReal } from "node:child_process";
import { randomBytes } from "node:crypto";
import { mkdirSync, statSync, writeFileSync, unlinkSync, appendFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { buildArgv } from "../../../lib/argv";
import { loadConfig, type DashboardConfig } from "../../../lib/config";
import { isLocalOrigin } from "../../../lib/requestGuard";
import { appendRun, getRunToken, type RunRecord } from "../../../lib/runlog";
import { runOutputBus as defaultRunOutputBus, type RunOutputBus } from "../../../lib/runOutputBus";
import { StreamJsonSplitter, parseStreamJsonLine } from "../../../lib/streamJson";

const STALE_LOCK_MS = 24 * 60 * 60 * 1000;
const DEFAULT_LOCKS_DIR = join(homedir(), ".claude", "coderails-dashboard", "locks");
const DEFAULT_RUNS_DIR = join(homedir(), ".claude", "coderails-dashboard", "runs");

// The stream-json flags MUST come immediately after "-p" — buildArgv (Task
// 7's single profile→flag mapping, not touched by this change) may append a
// "--" end-of-options sentinel followed by the merged prompt when input is
// present, and anything inserted after that sentinel would be swallowed into
// the prompt text instead of being parsed as flags. Splicing right after the
// leading "-p" keeps these flags before any such sentinel regardless of
// which buildArgv branch produced the rest of argv.
//
// --verbose is required alongside --output-format stream-json under --print
// — confirmed empirically on this machine 2026-07-07: omitting it fails
// fast with "Error: When using --print, --output-format=stream-json requires
// --verbose" before the CLI does anything else.
const STREAM_JSON_FLAGS = ["--output-format", "stream-json", "--include-partial-messages", "--verbose"];

function withStreamJsonFlags(argv: readonly string[]): string[] {
  return [argv[0], ...STREAM_JSON_FLAGS, ...argv.slice(1)];
}

// Minimal shape of a spawned child process this route actually uses: stdout/
// stderr as chunk-emitting streams (not the full Node.js Readable interface)
// plus exit/error events. node:child_process.spawn's real ChildProcess
// satisfies this structurally, so the real spawn can be passed directly via
// the same type-assertion pattern used for the analogous spawn seam in
// build/spawn.ts's SpawnFn.
//
// "error" is required (not optional) alongside "exit": Node fires "error"
// instead of "exit" when the process never launches at all (e.g. ENOENT if
// the "claude" binary isn't on PATH, EACCES, or a bad cwd) — a fake spawn
// that only implements "exit" would silently hide the fact that this route
// never handled that path. See the shared settle() helper below.
interface ChildProcessLike {
  stdout: { on(event: "data", listener: (chunk: Buffer | string) => void): void } | null;
  stderr: { on(event: "data", listener: (chunk: Buffer | string) => void): void } | null;
  on(event: "exit", listener: (code: number | null, signal: NodeJS.Signals | null) => void): void;
  on(event: "error", listener: (err: Error) => void): void;
}

type SpawnFn = (
  command: string,
  args: readonly string[],
  options: { cwd: string; env?: NodeJS.ProcessEnv },
) => ChildProcessLike;

export interface RunHandlerDeps {
  config: DashboardConfig;
  token: string;
  spawnImpl?: SpawnFn;
  locksDir?: string;
  runsDir?: string;
  runOutputBus?: RunOutputBus;
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
  const spawnImpl = deps.spawnImpl ?? (spawnReal as unknown as SpawnFn);
  const locksDir = deps.locksDir ?? DEFAULT_LOCKS_DIR;
  const runsDir = deps.runsDir ?? DEFAULT_RUNS_DIR;
  const runOutputBus = deps.runOutputBus ?? defaultRunOutputBus;

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
      argv = withStreamJsonFlags(buildArgv(button, typeof input === "string" ? input : undefined));
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

    // Intentionally long-lived: this response only resolves once the child
    // process exits, since the lock is held for its entire lifetime (see
    // acquireLock above). Frontend state during the run comes from the SSE
    // stream plus an optimistic flag, not this response — don't convert this
    // to fire-and-forget without redesigning the lock's release semantics.
    //
    // Output delivery is now incremental rather than one post-exit write:
    // each stdout/stderr chunk is appended to the log file and published on
    // the run-output bus as it arrives, so an SSE subscriber (and the log
    // file, for anyone tailing it) sees output live instead of only after
    // the whole run finishes. The stream-json splitter/parser
    // (src/lib/streamJson.ts) is applied per chunk purely to prove each line
    // is at least well-formed-or-gracefully-skipped — parsing failures never
    // affect what gets appended/published, which is always the raw chunk
    // text, so a malformed or unrecognised line can never crash the run or
    // drop output.
    const splitter = new StreamJsonSplitter();

    function handleChunk(chunk: Buffer | string): void {
      const text = typeof chunk === "string" ? chunk : chunk.toString("utf-8");
      appendFileSync(outputPath, text);
      runOutputBus.publish(runId, text);
      // Non-throwing by construction (see streamJson.ts) — parsed here only
      // so a malformed/unrecognised stream-json line is observed and
      // discarded rather than silently never looked at; the parsed value
      // itself isn't currently consumed further.
      for (const line of splitter.push(text)) {
        parseStreamJsonLine(line);
      }
    }

    await new Promise<void>((resolve) => {
      // Node emits at most one of "error"/"exit" as the terminal event for a
      // normal launch failure, but some failure modes (e.g. a bad cwd) can
      // fire both — settled guards so whichever arrives first wins and the
      // lock release + resolve() only ever happen once. Both paths funnel
      // through this single helper rather than duplicating the
      // record-then-unlock-then-resolve sequence, so the two can't drift.
      let settled = false;
      function settle(finishRecord: RunRecord): void {
        if (settled) return;
        settled = true;
        appendRun(finishRecord, { runsDir });
        try {
          unlinkSync(lockPath);
        } catch {
          // already removed; nothing to clean up
        }
        resolve();
      }

      const child = spawnImpl("claude", argv, { cwd: button.cwd });
      child.stdout?.on("data", handleChunk);
      child.stderr?.on("data", handleChunk);
      child.on("error", (err) => {
        // Fires instead of "exit" when the process never launched at all
        // (ENOENT if "claude" isn't on PATH, EACCES, bad cwd, etc) — without
        // this handler the promise above never resolves (the request hangs
        // forever) and the lock is never released (the button 409s until the
        // 24h stale-lock TTL).
        console.error("[api/run] spawn error", {
          runId,
          button: button.name,
          argv0: argv[0],
          cwd: button.cwd,
          err,
        });
        settle({ ...startRecord, endedAt: Date.now(), exitCode: -1 });
      });
      child.on("exit", (code, signal) => {
        for (const line of splitter.flush()) {
          parseStreamJsonLine(line);
        }
        const exitCode = code ?? 1;
        settle({
          ...startRecord,
          endedAt: Date.now(),
          exitCode,
          ...(signal ? { signal } : {}),
        });
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
// there for why a route.ts-local cache is unsafe to share with page.tsx
// (page.tsx imports getRunToken directly from lib/runlog, never from here).

export async function POST(request: Request): Promise<Response> {
  return createRunHandler({ config: getConfig(), token: getRunToken() })(request);
}
