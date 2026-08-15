// Scheduled routines enter execution as intent PRODUCERS, not as a runner
// scheduling engine: seed() runs before sweepOnce() (see bin/seed-and-sweep.sh)
// and, for each due routine, drops one intent file into queue/ using the
// same Intent shape any other producer (obsidian, web, cli) writes. The
// runner itself (sweep.ts/main.ts) stays a pure executor — it has no idea
// a routine's cadence exists as anything other than a stored config field,
// exactly as verified against origin/main before this file was authorised.
import { readdirSync, readFileSync, writeFileSync, mkdirSync, existsSync } from "node:fs";
import { join } from "node:path";
import { randomBytes } from "node:crypto";
import type { Intent, DashboardConfig, RoutineDef } from "@coderails/dashboard-lib";
import type { ButtonDef } from "../../app/src/lib/config.ts";
import { readRuns, type RunRecord } from "./runlog.ts";
import { escalate, defaultNotify } from "./escalate.ts";

export type SeedCadence = "nightly" | "weekly";

const NIGHTLY_DUE_AFTER_MS = 20 * 60 * 60 * 1000; // 20h
const WEEKLY_DUE_AFTER_MS = 6.5 * 24 * 60 * 60 * 1000; // 6.5 days

export interface SeedOptions {
  queueDir: string;
  processingDir: string;
  config: DashboardConfig;
  runsDir?: string;
  vaultNotesDir?: string;
  notifyImpl?: (title: string, message: string) => void;
  nowImpl?: () => number;
  readRunsImpl?: typeof readRuns;
}

export interface SeedResult {
  seeded: number;
  skippedNotDue: number;
  skippedAlreadyQueued: number;
  errored: number;
}

// Resolution rule (recorded per the team lead's brief): a routine's button
// is its buttonRef if set, otherwise a ButtonDef whose name equals the
// routine's own name. This mirrors sweep.ts's own findButton/findRoutine
// symmetry — findRoutine there matches a claimed intent's button name back
// to a RoutineDef by either routine.name or routine.buttonRef, so seeding
// must produce an intent whose `button` field resolves the same way in
// reverse (see sweep.ts's findRoutine for the matching half of this
// contract; it was fixed in PR #53 to accept the buttonRef arm too, closing
// the gap this comment used to document).
function resolveButton(config: DashboardConfig, routine: RoutineDef): ButtonDef | undefined {
  const targetName = routine.buttonRef ?? routine.name;
  return config.buttons.find((b) => b.name === targetName);
}

function isDue(cadence: SeedCadence, lastRun: RunRecord | undefined, now: number): boolean {
  if (!lastRun) return true;
  const elapsed = now - lastRun.startedAt;
  // A negative elapsed means lastRun.startedAt is in the future relative to
  // `now` (clock skew across machines, or a system clock corrected
  // backward after the run was recorded) — treat it as DUE rather than
  // comparing a negative number against a positive threshold, which would
  // always be false and wedge the routine as permanently "not due" until
  // someone notices and intervenes (I2). Failing toward running once is the
  // safer default: a spurious extra run is recoverable, a silently
  // never-firing routine is not.
  if (elapsed < 0) return true;
  if (cadence === "nightly") return elapsed >= NIGHTLY_DUE_AFTER_MS;
  return elapsed >= WEEKLY_DUE_AFTER_MS;
}

function mostRecentRun(runs: RunRecord[], buttonName: string): RunRecord | undefined {
  // readRuns already sorts newest-first by startedAt.
  return runs.find((r) => r.button === buttonName);
}

function isAlreadyQueued(dir: string, buttonName: string): boolean {
  if (!existsSync(dir)) return false;
  for (const file of readdirSync(dir)) {
    if (!file.endsWith(".json")) continue;
    try {
      const raw = JSON.parse(readFileSync(join(dir, file), "utf-8"));
      if (raw && typeof raw === "object" && raw.button === buttonName) return true;
    } catch {
      continue; // malformed file — not this seed's concern, sweepOnce quarantines it
    }
  }
  return false;
}

export function seedDueRoutines(opts: SeedOptions): SeedResult {
  const now = (opts.nowImpl ?? Date.now)();
  const readRunsImpl = opts.readRunsImpl ?? readRuns;
  const notifyImpl = opts.notifyImpl ?? defaultNotify;
  const result: SeedResult = { seeded: 0, skippedNotDue: 0, skippedAlreadyQueued: 0, errored: 0 };

  mkdirSync(opts.queueDir, { recursive: true, mode: 0o700 });

  const routines = opts.config.routines ?? [];
  if (routines.length === 0) return result;

  const runs = readRunsImpl(1000, { runsDir: opts.runsDir });

  for (const routine of routines) {
    try {
      if (routine.cadence !== "nightly" && routine.cadence !== "weekly") {
        result.errored++;
        // No dedup state (I6): a permanently-misconfigured routine (e.g. a
        // typo'd cadence that's never fixed) re-escalates on every calendar
        // fire, forever — there's no "already notified about this" memory.
        // Accepted deliberately: too-loud beats a silently-swallowed
        // misconfiguration, and dedup adds state (what counts as "the same"
        // failure, when to expire it) that isn't worth building until the
        // noise actually annoys someone in practice. Same tradeoff applies
        // to every escalate() call in this function.
        escalate({
          routine,
          runId: randomBytes(8).toString("hex"),
          failureClass: "runner-error",
          reason: `Unrecognised cadence "${routine.cadence}" — seed only understands "nightly" or "weekly"`,
          notifyImpl,
          vaultNotesDir: opts.vaultNotesDir,
        });
        continue;
      }

      const button = resolveButton(opts.config, routine);
      if (!button) {
        result.errored++;
        // No dedup — see the cadence-escalation comment above.
        escalate({
          routine,
          runId: randomBytes(8).toString("hex"),
          failureClass: "runner-error",
          reason: `Routine "${routine.name}" resolves to no ButtonDef (buttonRef "${routine.buttonRef ?? routine.name}" matches none)`,
          notifyImpl,
          vaultNotesDir: opts.vaultNotesDir,
        });
        continue;
      }

      // Accepted race (I4): isAlreadyQueued() (the check) and the
      // writeFileSync() below (the act) are not atomic — two seed runs for
      // the same routine racing here could both pass the check and both
      // write an intent. In practice this is narrow: seed only runs from
      // the CALENDAR plist (see bin/seed-and-sweep.sh), and launchd
      // serialises a single calendar job's fires, so two seed passes for
      // the same routine can't overlap in the deployed setup. Worst case if
      // that assumption is ever violated (e.g. a manual second invocation)
      // is one duplicate execution, bounded by sweepOnce's own atomic
      // rename-based claim (sweep.ts) — a duplicate run, not data loss or a
      // crash. Not worth a lockfile for that bound.
      if (isAlreadyQueued(opts.queueDir, button.name) || isAlreadyQueued(opts.processingDir, button.name)) {
        result.skippedAlreadyQueued++;
        continue;
      }

      const lastRun = mostRecentRun(runs, button.name);
      if (!isDue(routine.cadence, lastRun, now)) {
        result.skippedNotDue++;
        continue;
      }

      const intent: Intent = {
        button: button.name,
        requestedAt: now,
        source: "scheduler",
      };
      const runId = randomBytes(8).toString("hex");
      writeFileSync(join(opts.queueDir, `${runId}.json`), JSON.stringify(intent), { mode: 0o600 });
      result.seeded++;
    } catch (err) {
      // Per-routine failure boundary, mirroring sweep.ts's own per-intent
      // try/catch: one routine's seeding failure (a malformed queue file
      // seed can't parse, a readRunsImpl throw, etc.) must not stop the
      // rest of the routines from being considered.
      result.errored++;
      try {
        // No dedup — see the cadence-escalation comment above.
        escalate({
          routine,
          runId: randomBytes(8).toString("hex"),
          failureClass: "runner-error",
          reason: err instanceof Error ? err.message : String(err),
          notifyImpl,
          vaultNotesDir: opts.vaultNotesDir,
        });
      } catch (escalationErr) {
        console.error("seedDueRoutines: escalation for a caught seed failure itself threw, continuing:", escalationErr);
      }
    }
  }

  return result;
}
