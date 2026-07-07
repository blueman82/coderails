#!/usr/bin/env node
// CLI entrypoint for the seed step (see seed.ts's header for why seeding
// exists as a producer rather than a sweep.ts/main.ts change). Mirrors
// main.ts's shape (deps injection for testability, an entrypoint guard so
// importing run() in tests doesn't call process.exit) but is a separate
// file rather than an edit to main.ts, per the authorised scope: only new
// files in the runner package.
import { existsSync, realpathSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { loadConfig } from "@coderails/dashboard-lib";
import type { DashboardConfig } from "@coderails/dashboard-lib";
import { seedDueRoutines, type SeedResult } from "./seed.ts";
import { defaultNotify } from "./escalate.ts";

const BASE_DIR = join(homedir(), ".claude", "coderails-dashboard");

export interface SeedRunDeps {
  baseDir?: string;
  loadConfigImpl?: () => DashboardConfig;
  seedDueRoutinesImpl?: typeof seedDueRoutines;
  notifyImpl?: (title: string, message: string) => void;
  log?: (message: string) => void;
  logError?: (message: string, err: unknown) => void;
}

// Exit code contract mirrors main.ts's B5: 0 = clean seed pass (even if
// nothing was due), 1 is not used here — seeding failures are per-routine
// escalations, not a run-blocking condition, since sweepOnce still needs to
// run afterwards regardless of whether seeding had a problem — 2 = the
// seed step itself crashed before producing a SeedResult at all.
export async function run(deps: SeedRunDeps = {}): Promise<number> {
  const baseDir = deps.baseDir ?? BASE_DIR;
  const loadConfigImpl = deps.loadConfigImpl ?? loadConfig;
  const seedDueRoutinesImpl = deps.seedDueRoutinesImpl ?? seedDueRoutines;
  const log = deps.log ?? console.log;
  const logError = deps.logError ?? ((message: string, err: unknown) => console.error(message, err));

  let result: SeedResult;
  try {
    const config = loadConfigImpl();
    result = seedDueRoutinesImpl({
      queueDir: join(baseDir, "queue"),
      processingDir: join(baseDir, "processing"),
      config,
      runsDir: join(baseDir, "runs"),
      vaultNotesDir: config.wikiPaths[0] ? join(config.wikiPaths[0], "dashboard-runs") : undefined,
      notifyImpl: deps.notifyImpl,
    });
  } catch (err) {
    logError("Seed failed with an uncaught error:", err);
    try {
      (deps.notifyImpl ?? defaultNotify)("coderails seed step crashed", err instanceof Error ? err.message : String(err));
    } catch (notifyErr) {
      logError("Seed-crash notification itself failed:", notifyErr);
    }
    return 2;
  }

  log(
    `Seed complete: ${result.seeded} seeded, ${result.skippedNotDue} not due, ${result.skippedAlreadyQueued} already queued, ${result.errored} errored`
  );
  return 0;
}

// See main.ts's guard for why this compares realpaths rather than
// import.meta.url against process.argv[1] verbatim: the two silently
// diverge whenever the invocation path traverses a symlink (including
// macOS's own /var -> /private/var), which would otherwise make this
// entrypoint skip run() entirely — exit 0, no output, nothing seeded.
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
