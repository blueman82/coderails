import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

export interface HealthTile {
  key: "usage5h" | "usageWeek" | "hooksFired" | "lintFindings";
  value: string | null;
  note?: string;
}

export interface CollectHealthOptions {
  disciplineLogPath?: string;
  now?: Date;
}

const DEFAULT_DISCIPLINE_LOG_PATH = join(homedir(), ".claude", "discipline.log");

// Local calendar-day key (YYYY-MM-DD) for a Date, in that Date's own zone
// offset — used to compare a log line's leading timestamp against "now"'s
// day without normalizing either to UTC first.
function localDayKey(date: Date): string {
  return `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
}

// No local Claude Code usage/rate-limit file exists on disk to read from
// (investigated: no ~/.claude/usage*, no ccusage-style cache) — ship these
// tiles permanently unavailable rather than guess or scrape private files.
function usageTile(key: "usage5h" | "usageWeek"): HealthTile {
  return { key, value: null, note: "unavailable: no local usage source" };
}

// wiki-lint (skills/wiki-lint/SKILL.md) reports findings conversationally and
// persists no findings file — ship permanently unavailable rather than guess.
function lintFindingsTile(): HealthTile {
  return { key: "lintFindings", value: null, note: "unavailable: wiki-lint persists no report file" };
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
export function collectHealth(options: CollectHealthOptions = {}): HealthTile[] {
  const disciplineLogPath = options.disciplineLogPath ?? DEFAULT_DISCIPLINE_LOG_PATH;
  const now = options.now ?? new Date();
  return [
    usageTile("usage5h"),
    usageTile("usageWeek"),
    hooksFiredTile(disciplineLogPath, now),
    lintFindingsTile(),
  ];
}
