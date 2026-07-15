import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

export interface CostBucket {
  // null signals NO completed loops fell in this window — distinct from a
  // real $0 spend (e.g. a completed loop with an empty/unpriced cost {}),
  // which is a genuine zero and stays a number. Mirrors the UsageTotals |
  // null pattern in usage.ts: a silently-0 number would be indistinguishable
  // from "nothing to report" on the rendered tile.
  usd: number | null;
  tokens: number | null;
  // Only set when every summed loop's retro.json carries the SAME
  // prices_as_of — a mix of dates has no single honest answer, so the
  // bucket omits it rather than picking one arbitrarily (see
  // deriveSharedPricesAsOf below).
  pricesAsOf?: string;
}

export interface LoopCostSummary {
  week: CostBucket;
  month: CostBucket;
}

const SEVEN_DAYS_MS = 7 * 24 * 60 * 60_000;

function listDirs(baseDir: string): string[] {
  try {
    return readdirSync(baseDir, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && !entry.name.startsWith("."))
      .map((entry) => entry.name);
  } catch {
    return [];
  }
}

function readJson(path: string): unknown {
  try {
    return JSON.parse(readFileSync(path, "utf-8"));
  } catch {
    return undefined;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

interface LoopCostEntry {
  createdMs: number;
  usd: number;
  tokens: number;
  pricesAsOf?: string;
}

// Reads a loop dir's frozen cost, if any. This NEVER re-prices — it only
// sums the total_usd_estimate a retro.json already carries (pricing is
// frozen at teardown by the miner). A loop dir with no retro.json (still
// in-flight) or an empty cost {} (fail-open) contributes nothing rather
// than crashing.
function readLoopCost(loopDir: string): LoopCostEntry | undefined {
  const retro = readJson(join(loopDir, "retro.json"));
  if (!isRecord(retro)) return undefined;

  if (!isRecord(retro.cost)) return undefined;
  const cost = retro.cost;
  const usd = typeof cost.total_usd_estimate === "number" ? cost.total_usd_estimate : undefined;
  if (usd === undefined) return undefined;

  let createdMs = typeof retro.created === "string" ? Date.parse(retro.created) : NaN;
  if (Number.isNaN(createdMs)) {
    const progress = readJson(join(loopDir, "progress.json"));
    const progressCreated = isRecord(progress) && typeof progress.created === "string" ? progress.created : undefined;
    createdMs = progressCreated ? Date.parse(progressCreated) : NaN;
  }
  if (Number.isNaN(createdMs)) return undefined;

  return {
    createdMs,
    usd,
    tokens: typeof cost.total_tokens === "number" ? cost.total_tokens : 0,
    pricesAsOf: typeof cost.prices_as_of === "string" ? cost.prices_as_of : undefined,
  };
}

// Returns the shared prices_as_of only when every entry agrees (including
// "every entry lacks one" -> undefined); a mix of dates has no single
// honest answer, so the caller omits the staleness note rather than
// fabricating one.
function deriveSharedPricesAsOf(entries: LoopCostEntry[]): string | undefined {
  if (entries.length === 0) return undefined;
  const first = entries[0].pricesAsOf;
  if (!first) return undefined;
  return entries.every((entry) => entry.pricesAsOf === first) ? first : undefined;
}

function sumBucket(entries: LoopCostEntry[], startMs: number, endMs: number): CostBucket {
  const inWindow = entries.filter((entry) => entry.createdMs >= startMs && entry.createdMs < endMs);
  return {
    usd: inWindow.reduce((sum, entry) => sum + entry.usd, 0),
    tokens: inWindow.reduce((sum, entry) => sum + entry.tokens, 0),
    pricesAsOf: deriveSharedPricesAsOf(inWindow),
  };
}

// baseDir is the same ~/.claude/agentic-loop-shaped tree collectLoops walks:
// <baseDir>/<slug>/<sessionId>/, each holding a sibling retro.json next to
// progress.json. Buckets by two windows: WEEK (rolling 7 days from now) and
// MONTH (current calendar month, boundaries by month not by a fixed day
// count — a loop from last calendar month is excluded even if within 30
// days). Never throws: a missing base dir or any per-loop read failure
// degrades that loop to "excluded" rather than propagating.
export function collectLoopCost(baseDir: string, now: Date): LoopCostSummary {
  const nowMs = now.getTime();
  const weekStartMs = nowMs - SEVEN_DAYS_MS;
  const monthStartMs = new Date(now.getFullYear(), now.getMonth(), 1).getTime();
  const monthEndMs = new Date(now.getFullYear(), now.getMonth() + 1, 1).getTime();

  const entries: LoopCostEntry[] = [];
  for (const slug of listDirs(baseDir)) {
    const projectDir = join(baseDir, slug);
    for (const sessionId of listDirs(projectDir)) {
      const entry = readLoopCost(join(projectDir, sessionId));
      if (entry) entries.push(entry);
    }
  }

  return {
    week: sumBucket(entries, weekStartMs, nowMs + 1),
    month: sumBucket(entries, monthStartMs, monthEndMs),
  };
}
