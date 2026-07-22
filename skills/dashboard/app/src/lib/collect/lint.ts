import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { HealthTile } from "./health";

const LINT_HEADING_RE = /^## \[(\d{4}-\d{2}-\d{2})\] lint \|/gm;

// wiki-lint (skills/wiki-lint/SKILL.md, Step 5) appends one heading per run:
// "## [YYYY-MM-DD] lint | <summary>", where <summary> is a freeform prose
// paragraph — not structured data. That prose is NEVER regex-scanned for a
// findings count: a paragraph reporting "999 orphan links" would silently
// surface 999 as though it were a real, current count, when it is just a
// number mentioned in a sentence. The only thing read out of the prose is
// what the heading unambiguously states — the date of the most recent run —
// surfaced as recency (days since last lint). A real findings count is only
// ever taken from the structured record below, which a lint run writes
// deliberately for this purpose. Do not "improve" this into a prose regex.
const STRUCTURED_FINDINGS_RE = /<!--\s*lint-findings:\s*(\d+)\s*-->/;

function mostRecentLintDate(logContents: string): string | null {
  let latest: string | null = null;
  for (const match of logContents.matchAll(LINT_HEADING_RE)) {
    const date = match[1];
    if (latest === null || date > latest) latest = date;
  }
  return latest;
}

function daysSince(dateStr: string, now: Date): number {
  const then = new Date(`${dateStr}T00:00:00Z`).getTime();
  const nowMs = now.getTime();
  return Math.floor((nowMs - then) / (24 * 60 * 60_000));
}

function unavailable(note: string): HealthTile {
  return { key: "lintFindings", value: null, note: `unavailable: ${note}` };
}

// Reads $vault/log.md (the first resolvable vault path in vaultPaths — mirrors
// how other collectors take a single base dir) and derives the lintFindings
// tile. Prefers a structured findings-count record when a lint run has left
// one; otherwise falls back to honest recency (days since the last lint) read
// from the heading date. Never throws: an absent/unreadable vault (most
// coderails users have no wiki) degrades to unavailable rather than guessing.
export function collectLintFindings(vaultPaths: string[], now: Date): HealthTile {
  if (vaultPaths.length === 0) return unavailable("no wiki vault configured");

  let contents: string | undefined;
  for (const vaultPath of vaultPaths) {
    try {
      contents = readFileSync(join(vaultPath, "log.md"), "utf-8");
      break;
    } catch {
      continue;
    }
  }
  if (contents === undefined) return unavailable("wiki vault log.md not readable");

  const structured = contents.match(STRUCTURED_FINDINGS_RE);
  if (structured) {
    return { key: "lintFindings", value: structured[1] };
  }

  const latestDate = mostRecentLintDate(contents);
  if (latestDate === null) return unavailable("no lint entries found in wiki vault log.md");

  const days = daysSince(latestDate, now);
  return { key: "lintFindings", value: `${days}d since last lint`, note: `last lint ${latestDate}` };
}
