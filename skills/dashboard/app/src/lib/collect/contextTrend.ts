import { createReadStream, readdirSync, statSync, existsSync } from "node:fs";
import { createInterface } from "node:readline";
import { join, basename } from "node:path";

// Measures orchestrator-only cache-read tokens per assistant turn, per
// agentic-loop session, across the 2026-07-17 token-reduction cutover (the
// measures shipped as PRs #228/#229/#230 — see CUTOVER_MS below).
//
// Whether those measures reduced token burn is NOT established: the before and
// after groups differ in size and composition, and no controlled comparison was
// run. So this collector deliberately reports only the raw per-session series
// plus per-side summary stats (median, quartiles, n) and leaves the judgement
// to the reader. It never computes a headline saving, and the panel that renders
// it never displays one.
//
// (An earlier version of this comment cited docs/TOKEN-REDUCTION-AUDIT.md as the
// source of that verdict. No such file has ever existed on any ref, so each
// constant below now carries its own in-repo justification instead.)

export interface TrendSession {
  sessionId: string;
  // First non-null message timestamp inside the jsonl — NEVER file mtime. The
  // remember plugin rewrites transcripts on resume and bumps mtime; the audit
  // documents a real session (007e525b…) that mtime would have misfiled
  // across the cutover.
  startMs: number;
  // Unique assistant message.id count in the orchestrator transcript alone.
  turns: number;
  // cache_read_input_tokens summed over the orchestrator transcript alone,
  // deduped by message.id. Same scope as `turns` — the audit's first pass
  // divided a subagent-tree-pooled numerator by an orchestrator-only turn
  // count and had to be corrected; keep both sides orchestrator-only.
  cacheRead: number;
}

export interface TrendSideStats {
  n: number;
  medianPerTurn: number | null;
  q1PerTurn: number | null;
  q3PerTurn: number | null;
}

export interface CompactionEvent {
  timestampMs: number;
  trigger: "manual" | "auto";
}

export interface ContextTrendSummary {
  windowStartMs: number;
  cutoverMs: number;
  // Cohort sessions sorted by startMs ascending.
  sessions: TrendSession[];
  before: TrendSideStats;
  after: TrendSideStats;
  // All compaction boundaries found in matching project transcripts (cohort
  // or not — row 1's inertness is a project-wide fact), uuid-deduped, sorted
  // ascending. The panel derives "zero fires since cutover" from this.
  compactions: CompactionEvent[];
}

// The token-burn reduction measures shipped as PRs #228/#229/#230, merged
// 2026-07-17 at 20:22:29Z, 20:25:46Z and 20:27:27Z (verifiable with
// `gh pr view 228 --json mergedAt`). Sessions are binned against the FIRST of
// those merges, so the boundary is a real, checkable repo event rather than a
// chosen date.
const CUTOVER_MS = Date.parse("2026-07-17T20:22:00Z");
// Window start, picked to give the before-group a span comparable to the
// after-group rather than an unbounded tail: it reaches ~10 days back from the
// cutover. Sessions starting earlier are out of population — they ran against
// materially different skill versions, so their per-turn cost is not
// comparable. This bound only selects WHICH sessions are plotted; it does not
// weight or adjust any of them.
const WINDOW_START_MS = Date.parse("2026-07-07T00:00:00Z");
// The measures under audit shipped to the coderails project; its transcript
// dirs (primary checkout + worktree-suffixed variants) all carry this token.
const PROJECT_SLUG_TOKEN = "coderails";
// A session is in-cohort only if it BOTH loaded the agentic-loop skill and
// actually orchestrated workers (a <sid>/subagents/ dir exists) — marker
// alone matches any session that merely mentioned the skill text.
const LOOP_MARKERS = ["coderails:agentic-loop", "skills/agentic-loop/SKILL.md"];

interface FileStats {
  firstTimestampMs: number | null;
  turns: number;
  cacheRead: number;
  hasLoopMarker: boolean;
  compactions: { uuid: string; timestampMs: number; trigger: "manual" | "auto" }[];
}

interface CacheEntry {
  mtimeMs: number;
  size: number;
  stats: FileStats;
}

export type ContextTrendFileCache = Map<string, CacheEntry>;

// Transcripts are append-only in normal operation and wholly rewritten by the
// remember plugin on resume — both bump (mtimeMs, size), so a per-file parse
// keyed on them is safe to reuse and the steady-state cost of a refresh is a
// stat() per file plus a re-parse of only the actively-growing transcript,
// not a re-stream of the full multi-hundred-MB corpus.
const moduleCache: ContextTrendFileCache = new Map();

export interface CollectContextTrendOptions {
  now?: Date;
  cache?: ContextTrendFileCache;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// Streams one orchestrator transcript and folds every signal this collector
// needs in a single pass: first message timestamp, unique-assistant-turn
// usage, loop markers, and compaction boundaries. Same streaming/dedupe
// approach as usage.ts's collectFileEvents; unreadable-mid-stream keeps the
// partial parse rather than losing the file.
async function parseTranscript(path: string): Promise<FileStats> {
  const stats: FileStats = {
    firstTimestampMs: null,
    turns: 0,
    cacheRead: 0,
    hasLoopMarker: false,
    compactions: [],
  };
  const seenIds = new Set<string>();
  let stream;
  try {
    stream = createReadStream(path, { encoding: "utf-8" });
  } catch {
    return stats;
  }
  const rl = createInterface({ input: stream, crlfDelay: Infinity });
  try {
    for await (const line of rl) {
      if (line.trim() === "") continue;
      if (!stats.hasLoopMarker && LOOP_MARKERS.some((marker) => line.includes(marker))) {
        stats.hasLoopMarker = true;
      }
      let data: unknown;
      try {
        data = JSON.parse(line);
      } catch {
        continue;
      }
      if (!isRecord(data)) continue;

      if (stats.firstTimestampMs === null && typeof data.timestamp === "string") {
        const timestampMs = Date.parse(data.timestamp);
        if (!Number.isNaN(timestampMs)) stats.firstTimestampMs = timestampMs;
      }

      const compactMetadata = data.compactMetadata;
      if (isRecord(compactMetadata) && typeof data.uuid === "string" && typeof data.timestamp === "string") {
        const trigger = compactMetadata.trigger;
        const timestampMs = Date.parse(data.timestamp);
        if ((trigger === "manual" || trigger === "auto") && !Number.isNaN(timestampMs)) {
          stats.compactions.push({ uuid: data.uuid, timestampMs, trigger });
        }
      }

      if (data.type !== "assistant") continue;
      const message = data.message;
      if (!isRecord(message) || typeof message.id !== "string") continue;
      const usage = message.usage;
      if (!isRecord(usage)) continue;
      if (seenIds.has(message.id)) continue;
      seenIds.add(message.id);
      stats.turns += 1;
      stats.cacheRead += typeof usage.cache_read_input_tokens === "number" ? usage.cache_read_input_tokens : 0;
    }
  } catch {
    // unreadable mid-stream — keep the partial parse
  } finally {
    stream.destroy();
  }
  return stats;
}

async function statsForFile(path: string, cache: ContextTrendFileCache): Promise<FileStats | null> {
  let mtimeMs: number;
  let size: number;
  try {
    const stat = statSync(path);
    mtimeMs = stat.mtimeMs;
    size = stat.size;
  } catch {
    return null;
  }
  const cached = cache.get(path);
  if (cached && cached.mtimeMs === mtimeMs && cached.size === size) return cached.stats;
  const stats = await parseTranscript(path);
  cache.set(path, { mtimeMs, size, stats });
  return stats;
}

// Lower nearest-rank quantile over an ASCENDING-sorted array — the audit's
// method, kept so the panel's before-side numbers reconcile against the
// audit's published table.
function quantile(sortedAsc: number[], p: number): number | null {
  if (sortedAsc.length === 0) return null;
  return sortedAsc[Math.floor((sortedAsc.length - 1) * p)];
}

// Median averages the two middle values on even counts (matching the audit's
// medians); quartiles stay lower nearest-rank.
function median(sortedAsc: number[]): number | null {
  const n = sortedAsc.length;
  if (n === 0) return null;
  if (n % 2 === 1) return sortedAsc[(n - 1) / 2];
  return (sortedAsc[n / 2 - 1] + sortedAsc[n / 2]) / 2;
}

function sideStats(sessions: TrendSession[]): TrendSideStats {
  const perTurn = sessions.map((s) => s.cacheRead / s.turns).sort((a, b) => a - b);
  return {
    n: perTurn.length,
    medianPerTurn: median(perTurn),
    q1PerTurn: quantile(perTurn, 0.25),
    q3PerTurn: quantile(perTurn, 0.75),
  };
}

// baseDir is a ~/.claude/projects-shaped tree. Only TOP-LEVEL <slug>/<sid>.jsonl
// files are read — the orchestrator transcript; subagent transcripts under
// <slug>/<sid>/subagents/ are deliberately never opened (orchestrator-only on
// both numerator and denominator). No mtime prefilter: unlike usage.ts's
// rolling windows, old sessions stay in this population forever, so recency
// of the file says nothing about relevance — the cache is what keeps repeat
// collection cheap. Never throws: an unreadable base dir degrades to null.
export async function collectContextTrend(
  baseDir: string,
  options: CollectContextTrendOptions = {}
): Promise<ContextTrendSummary | null> {
  const cache = options.cache ?? moduleCache;

  let slugs: string[];
  try {
    slugs = readdirSync(baseDir, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && !entry.name.startsWith("."))
      .filter((entry) => entry.name.includes(PROJECT_SLUG_TOKEN))
      .map((entry) => entry.name);
  } catch {
    return null;
  }

  const sessions: TrendSession[] = [];
  const compactionsByUuid = new Map<string, CompactionEvent>();
  const seenPaths = new Set<string>();

  for (const slug of slugs) {
    const projectDir = join(baseDir, slug);
    let entries;
    try {
      entries = readdirSync(projectDir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      if (!entry.isFile() || !entry.name.endsWith(".jsonl") || entry.name.startsWith(".")) continue;
      const path = join(projectDir, entry.name);
      seenPaths.add(path);
      const stats = await statsForFile(path, cache);
      if (!stats) continue;

      for (const compaction of stats.compactions) {
        compactionsByUuid.set(compaction.uuid, {
          timestampMs: compaction.timestampMs,
          trigger: compaction.trigger,
        });
      }

      const sessionId = basename(entry.name, ".jsonl");
      const inCohort =
        stats.hasLoopMarker &&
        stats.turns > 0 &&
        stats.firstTimestampMs !== null &&
        stats.firstTimestampMs >= WINDOW_START_MS &&
        existsSync(join(projectDir, sessionId, "subagents"));
      if (!inCohort) continue;

      sessions.push({
        sessionId,
        startMs: stats.firstTimestampMs!,
        turns: stats.turns,
        cacheRead: stats.cacheRead,
      });
    }
  }

  // Drop cache entries for files gone from disk (deleted worktree dirs and
  // the like) so the map tracks the live corpus rather than growing forever.
  for (const path of cache.keys()) {
    if (!seenPaths.has(path)) cache.delete(path);
  }

  sessions.sort((a, b) => a.startMs - b.startMs);
  const before = sessions.filter((s) => s.startMs < CUTOVER_MS);
  const after = sessions.filter((s) => s.startMs >= CUTOVER_MS);

  return {
    windowStartMs: WINDOW_START_MS,
    cutoverMs: CUTOVER_MS,
    sessions,
    before: sideStats(before),
    after: sideStats(after),
    compactions: [...compactionsByUuid.values()].sort((a, b) => a.timestampMs - b.timestampMs),
  };
}
