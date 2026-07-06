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
// one line per hook invocation: "<timestamp> hook=<name> ... blocked=<0|1>".
// Counting non-blank lines counts invocations; an unreadable/missing log
// degrades to unavailable rather than throwing.
function hooksFiredTile(path: string): HealthTile {
  let contents: string;
  try {
    contents = readFileSync(path, "utf-8");
  } catch {
    return { key: "hooksFired", value: null, note: "unavailable: discipline.log not readable" };
  }
  const count = contents.split("\n").filter((line) => line.trim().length > 0).length;
  return { key: "hooksFired", value: String(count) };
}

// collectHealth never throws: each tile degrades independently to
// value: null with a note when its source is absent or unreadable.
export function collectHealth(options: CollectHealthOptions = {}): HealthTile[] {
  const disciplineLogPath = options.disciplineLogPath ?? DEFAULT_DISCIPLINE_LOG_PATH;
  return [usageTile("usage5h"), usageTile("usageWeek"), hooksFiredTile(disciplineLogPath), lintFindingsTile()];
}
