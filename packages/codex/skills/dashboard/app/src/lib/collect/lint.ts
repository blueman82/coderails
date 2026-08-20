import { readFileSync } from "node:fs";
import { join } from "node:path";
import type { HealthTile } from "./health";

// wiki-lint (skills/wiki-lint/SKILL.md, Step 5) appends one heading per run:
// "## [YYYY-MM-DD] lint | <summary>", where <summary> is a freeform prose
// paragraph — not structured data. That prose is NEVER regex-scanned for a
// findings count: a paragraph reporting "999 orphan links" would silently
// surface 999 as though it were a real, current count, when it is just a
// number mentioned in a sentence. The only thing read out of the prose is
// what the heading unambiguously states — the date of each run — used to
// pick the MOST RECENT entry (by date, not file position: wiki-lint appends,
// so newest is normally last, but nothing should rely on that ordering) and,
// for that entry only, surface either its structured findings count (below)
// or honest recency (days since last lint) as a fallback. A real findings
// count is only ever taken from the structured record, which a lint run
// writes deliberately for this purpose. Do not "improve" this into a prose
// regex.
const LINT_ENTRY_RE = /^## \[(\d{4}-\d{2}-\d{2})\] lint \|.*$/gm;
const STRUCTURED_FINDINGS_RE = /<!--\s*lint-findings:\s*(\d+)\s*-->/;

interface LintEntry {
  date: string;
  findingsCount: string | null;
}

// Splits log.md into one entry per lint heading, each entry's text running
// up to (not including) the next heading — so a structured record is
// attributed to the run that produced it, not to whichever run happens to be
// first in the file.
function parseLintEntries(logContents: string): LintEntry[] {
  const matches = [...logContents.matchAll(LINT_ENTRY_RE)];
  return matches.map((match, i) => {
    const start = match.index ?? 0;
    const end = i + 1 < matches.length ? (matches[i + 1].index ?? logContents.length) : logContents.length;
    const body = logContents.slice(start, end);
    const structured = body.match(STRUCTURED_FINDINGS_RE);
    return { date: match[1], findingsCount: structured ? structured[1] : null };
  });
}

// Same-date ties are normal, not an edge case: wiki-lint appends one entry
// per run, and multiple runs on the same day happen routinely. Comparing
// with ">=" (not ">") means a later same-date entry always wins the tie,
// record or not — log.md is append-only, so later-in-file means
// later-in-time. wiki-lint's Step 5 makes the structured findings-count
// record mandatory on every run (even "0" on a clean pass), so a same-date
// entry that legitimately has no record is the newest run's own state, not
// a gap to paper over with an older sibling's stale count. Do not revert
// this to ">" — that silently resurrects whichever same-date entry happens
// to appear first in the file, which is exactly backwards for an
// append-only log.
function mostRecentLintEntry(entries: LintEntry[]): LintEntry | null {
  if (entries.length === 0) return null;
  return entries.reduce((latest, entry) => (entry.date >= latest.date ? entry : latest));
}

// Clamped to 0 rather than returning a negative count: a heading dated in the
// future (clock skew, a hand-edited log, a timezone edge) means the entry is
// no older than "now" from the reader's point of view. A negative day count
// ("-3d since last lint") is not an honest number — nothing is 3 days
// negatively stale — so the honest floor is "at least as recent as today".
function daysSince(dateStr: string, now: Date): number {
  const then = new Date(`${dateStr}T00:00:00Z`).getTime();
  const nowMs = now.getTime();
  return Math.max(0, Math.floor((nowMs - then) / (24 * 60 * 60_000)));
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

  const latest = mostRecentLintEntry(parseLintEntries(contents));
  if (latest === null) return unavailable("no lint entries found in wiki vault log.md");

  if (latest.findingsCount !== null) {
    return { key: "lintFindings", value: latest.findingsCount, note: `last lint ${latest.date}` };
  }

  const days = daysSince(latest.date, now);
  return { key: "lintFindings", value: `${days}d since last lint`, note: `last lint ${latest.date}` };
}
