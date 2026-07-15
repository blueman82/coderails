import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { collectUsage, type UsageTotals } from "./usage";
import { collectLoopCost, type CostBucket } from "./cost";

export interface HealthTile {
  key: "usage5h" | "usageWeek" | "hooksFired" | "lintFindings" | "costWeek" | "costMonth";
  value: string | null;
  note?: string;
}

export interface CollectHealthOptions {
  disciplineLogPath?: string;
  projectsDir?: string;
  loopsDir?: string;
  now?: Date;
}

const DEFAULT_DISCIPLINE_LOG_PATH = join(homedir(), ".claude", "discipline.log");
const DEFAULT_PROJECTS_DIR = join(homedir(), ".claude", "projects");
const DEFAULT_LOOPS_DIR = join(homedir(), ".claude", "agentic-loop");

// Local calendar-day key (YYYY-MM-DD) for a Date, in that Date's own zone
// offset — used to compare a log line's leading timestamp against "now"'s
// day without normalizing either to UTC first.
function localDayKey(date: Date): string {
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

// Compact token count: 1_234_567 -> "1.2M", 412_000 -> "412K", 850 -> "850".
// One decimal place, trimmed when it would render as ".0".
function formatTokenCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1).replace(/\.0$/, "")}K`;
  return String(n);
}

// projectsDir is unreadable (no local Claude Code session transcripts to
// derive usage from) — degrade to unavailable rather than guess.
function unavailableUsageTile(key: "usage5h" | "usageWeek"): HealthTile {
  return { key, value: null, note: "unavailable: no local usage source" };
}

function usageTile(key: "usage5h" | "usageWeek", totals: UsageTotals | null): HealthTile {
  if (!totals) return unavailableUsageTile(key);
  return {
    key,
    value: `${formatTokenCount(totals.totalTokens)} tok`,
    // Cache re-reads dominate the input total on real transcripts (~99%) —
    // name their share so the headline isn't read as raw consumption.
    note:
      totals.cacheReadTokens > 0
        ? `in ${formatTokenCount(totals.inputTokens)} (${formatTokenCount(totals.cacheReadTokens)} cache) / out ${formatTokenCount(totals.outputTokens)}`
        : `in ${formatTokenCount(totals.inputTokens)} / out ${formatTokenCount(totals.outputTokens)}`,
  };
}

// wiki-lint (skills/wiki-lint/SKILL.md) reports findings conversationally and
// persists no findings file — ship permanently unavailable rather than guess.
function lintFindingsTile(): HealthTile {
  return { key: "lintFindings", value: null, note: "unavailable: wiki-lint persists no report file" };
}

// USD headline with two decimal places: 3.75 -> "$3.75". total_usd_estimate
// is frozen at teardown by the miner — this formats a stored number, it
// never re-prices.
function formatUsd(n: number): string {
  return `$${n.toFixed(2)}`;
}

// Cost tiles sum retro.json's frozen cost.total_usd_estimate across
// COMPLETED loops only — a different denominator from the usage5h/usageWeek
// tiles above, which sum every transcript regardless of loop completion.
// The note names that scope explicitly so the two don't read as
// contradictory. A derivable shared prices_as_of is surfaced as a
// staleness note; when the summed loops disagree (or none carry one) it's
// omitted rather than fabricated.
function costTile(key: "costWeek" | "costMonth", bucket: CostBucket): HealthTile {
  const scopeNote = "completed loops only";
  return {
    key,
    value: formatUsd(bucket.usd),
    note: bucket.pricesAsOf ? `${scopeNote} · prices as of ${bucket.pricesAsOf}` : scopeNote,
  };
}

// discipline.log (written by the hooks in ~/.claude/hooks) is plain text,
// one line per hook invocation, each line starting with an ISO-8601
// timestamp: "<timestamp> hook=<name> ... blocked=<0|1>". The dashboard
// tile is labelled "hooks fired today", so we count only lines whose
// leading timestamp falls on the current local calendar day — a line
// whose leading token doesn't parse as a date is excluded rather than
// guessed (fail-honest). An unreadable/missing log degrades to
// unavailable rather than throwing.
function hooksFiredTile(path: string, now: Date): HealthTile {
  let contents: string;
  try {
    contents = readFileSync(path, "utf-8");
  } catch {
    return { key: "hooksFired", value: null, note: "unavailable: discipline.log not readable" };
  }
  const todayKey = localDayKey(now);
  const count = contents
    .split("\n")
    .filter((line) => line.trim().length > 0)
    .filter((line) => {
      const leadingToken = line.split(/\s+/, 1)[0];
      const timestamp = new Date(leadingToken);
      return !Number.isNaN(timestamp.getTime()) && localDayKey(timestamp) === todayKey;
    }).length;
  return { key: "hooksFired", value: String(count) };
}

// collectHealth never throws: each tile degrades independently to
// value: null with a note when its source is absent or unreadable.
export async function collectHealth(options: CollectHealthOptions = {}): Promise<HealthTile[]> {
  const disciplineLogPath = options.disciplineLogPath ?? DEFAULT_DISCIPLINE_LOG_PATH;
  const projectsDir = options.projectsDir ?? DEFAULT_PROJECTS_DIR;
  const loopsDir = options.loopsDir ?? DEFAULT_LOOPS_DIR;
  const now = options.now ?? new Date();
  const usage = await collectUsage(projectsDir, now);
  const cost = collectLoopCost(loopsDir, now);
  return [
    usageTile("usage5h", usage.last5h),
    usageTile("usageWeek", usage.week),
    hooksFiredTile(disciplineLogPath, now),
    lintFindingsTile(),
    costTile("costWeek", cost.week),
    costTile("costMonth", cost.month),
  ];
}
