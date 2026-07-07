#!/usr/bin/env node
import { existsSync, realpathSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { loadConfig } from "@coderails/dashboard-lib";
import type { DashboardConfig } from "@coderails/dashboard-lib";
import { sweepOnce, type SweepResult } from "./sweep.ts";
import { defaultNotify } from "./escalate.ts";

const BASE_DIR = join(homedir(), ".claude", "coderails-dashboard");

export interface RunDeps {
  baseDir?: string;
  loadConfigImpl?: () => DashboardConfig;
  sweepOnceImpl?: typeof sweepOnce;
  notifyImpl?: (title: string, message: string) => void;
  log?: (message: string) => void;
  logError?: (message: string, err: unknown) => void;
}

// Exit code contract (B5): 0 = clean sweep, 1 = one or more routine
// failures (result.failed > 0), 2 = the sweeper itself crashed before or
// during producing a SweepResult at all — a strictly worse outcome than
// "some routines failed", since even the failure bookkeeping in that case
// isn't trustworthy.
export async function run(deps: RunDeps = {}): Promise<number> {
  const baseDir = deps.baseDir ?? BASE_DIR;
  const loadConfigImpl = deps.loadConfigImpl ?? loadConfig;
  const sweepOnceImpl = deps.sweepOnceImpl ?? sweepOnce;
  const log = deps.log ?? console.log;
  const logError = deps.logError ?? ((message: string, err: unknown) => console.error(message, err));

  let result: SweepResult;
  try {
    const config = loadConfigImpl();
    result = await sweepOnceImpl({
      queueDir: join(baseDir, "queue"),
      processingDir: join(baseDir, "processing"),
      archiveDir: join(baseDir, "archive"),
      quarantineDir: join(baseDir, "quarantine"),
      config,
      runsDir: join(baseDir, "runs"),
      vaultNotesDir: config.wikiPaths[0] ? join(config.wikiPaths[0], "dashboard-runs") : undefined,
      notifyImpl: deps.notifyImpl,
    });
  } catch (err) {
    logError("Sweep failed with an uncaught error:", err);
    // Last-resort notification that the sweeper crashed outright — best
    // effort, guarded in its own try/catch so a broken notification channel
    // can't mask the real crash or throw a second error out of the catch
    // block itself.
    try {
      (deps.notifyImpl ?? defaultNotify)("coderails sweeper crashed", err instanceof Error ? err.message : String(err));
    } catch (notifyErr) {
      logError("Sweep-crash notification itself failed:", notifyErr);
    }
    return 2;
  }

  log(
    `Sweep complete: ${result.claimed} claimed, ${result.succeeded} succeeded, ${result.failed} failed, ${result.quarantined} quarantined`
  );
  return result.failed > 0 ? 1 : 0;
}

// Thin bin shim: all logic lives in run() above so it can be tested without
// process.exit tearing down the test runner. The guard below keeps this
// from firing (and exiting the process) when main.test.ts imports run()
// directly — only firing when this file is the actual entry point, e.g.
// via bin/sweeper.sh invoking src/main.ts.
//
// Comparing realpaths (rather than import.meta.url against process.argv[1]
// verbatim) is required because import.meta.url always resolves through
// the filesystem while process.argv[1] keeps whatever path string was
// typed on the command line — the two silently diverge whenever the
// invocation path traverses a symlink, including macOS's own /var ->
// /private/var, which every /tmp-rooted invocation crosses. An unguarded
// mismatch here doesn't error; it just skips run() entirely, so a routine
// invoked this way silently does nothing (exit 0, no output). Each side is
// wrapped so a path that vanishes between argv parsing and this check
// (e.g. a deleted temp dir) can't crash the guard itself — it just falls
// through to "not the entry point".
function tryRealpath(path: string): string | undefined {
  try {
    return existsSync(path) ? realpathSync(path) : undefined;
  } catch {
    return undefined;
  }
}

const isEntryPoint =
  process.argv[1] !== undefined &&
  tryRealpath(fileURLToPath(import.meta.url)) === tryRealpath(process.argv[1]);

if (isEntryPoint) {
  run().then((code) => process.exit(code));
}
