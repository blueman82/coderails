import { createReadStream, readdirSync, statSync } from "node:fs";
import { createInterface } from "node:readline";
import { join } from "node:path";

export interface UsageTotals {
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
  // Portion of inputTokens that was cache re-reads. On real transcripts this
  // dominates the input total (~99%), so the tile note surfaces it rather
  // than letting the headline read as raw consumption.
  cacheReadTokens: number;
}

export interface UsageSummary {
  last5h: UsageTotals | null;
  week: UsageTotals | null;
}

const FIVE_HOURS_MS = 5 * 60 * 60_000;
const SEVEN_DAYS_MS = 7 * 24 * 60 * 60_000;

interface UsageEvent {
  messageId: string;
  timestampMs: number;
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// Parses one JSONL line into a usage event, or null if the line is malformed,
// blank, or not an assistant line carrying a usable usage object. Real
// transcripts (~/.claude/projects/<slug>/*.jsonl) also carry "user",
// "summary", "pr-link", and "bridge-session" lines with no usage at all —
// those are expected, not errors.
function parseUsageEvent(line: string): UsageEvent | null {
  if (line.trim() === "") return null;
  let data: unknown;
  try {
    data = JSON.parse(line);
  } catch {
    return null;
  }
  if (!isRecord(data) || data.type !== "assistant") return null;

  const message = data.message;
  if (!isRecord(message) || typeof message.id !== "string") return null;

  const usage = message.usage;
  if (!isRecord(usage)) return null;
  if (typeof usage.input_tokens !== "number" || typeof usage.output_tokens !== "number") return null;

  const timestamp = typeof data.timestamp === "string" ? Date.parse(data.timestamp) : NaN;
  if (Number.isNaN(timestamp)) return null;

  const cacheCreation = typeof usage.cache_creation_input_tokens === "number" ? usage.cache_creation_input_tokens : 0;
  const cacheRead = typeof usage.cache_read_input_tokens === "number" ? usage.cache_read_input_tokens : 0;

  return {
    messageId: message.id,
    timestampMs: timestamp,
    inputTokens: usage.input_tokens + cacheCreation + cacheRead,
    outputTokens: usage.output_tokens,
    cacheReadTokens: cacheRead,
  };
}

// Streams a single transcript file line-by-line (readline over a read
// stream) rather than reading it whole — transcripts can run to tens of MB
// and the process must not hold one entirely in memory. Each real streaming
// step re-emits an assistant line with the SAME message.id and an identical
// cumulative usage snapshot (confirmed against real transcripts); only the
// first occurrence of each id is kept so repeats don't inflate the total.
// Dedup here is WITHIN this file only — cross-file dedup happens at merge
// time in collectUsage, never persisted (see CachedFile / mergeCandidates).
async function collectFileEvents(path: string): Promise<UsageEvent[]> {
  const events: UsageEvent[] = [];
  const seenIds = new Set<string>();
  let stream;
  try {
    stream = createReadStream(path, { encoding: "utf-8" });
  } catch {
    return events;
  }
  const rl = createInterface({ input: stream, crlfDelay: Infinity });
  try {
    for await (const line of rl) {
      // Cheap prefilter before the JSON.parse in parseUsageEvent: only
      // assistant lines can ever carry a usage object, and they are a
      // minority of lines in a real transcript (~40%, dominated by other
      // event types) — skipping the parse on the rest cuts parse cost.
      if (!line.includes('"type":"assistant"')) continue;
      const event = parseUsageEvent(line);
      if (!event) continue;
      if (seenIds.has(event.messageId)) continue;
      seenIds.add(event.messageId);
      events.push(event);
    }
  } catch {
    // unreadable mid-stream (e.g. permissions changed) — keep whatever was
    // parsed so far rather than losing the whole file
  } finally {
    stream.destroy();
  }
  return events;
}

// Lists .jsonl files under dir, recursing into subdirectories. Read failures
// on nested entries are skipped (matches collectSessions' per-entry
// tolerance); the caller is responsible for treating a failure on the base
// dir itself as fatal.
function listJsonlFiles(dir: string, out: string[]): void {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return;
  }
  for (const entry of entries) {
    if (entry.name.startsWith(".")) continue;
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      listJsonlFiles(path, out);
    } else if (entry.name.endsWith(".jsonl")) {
      out.push(path);
    }
  }
}

function sumWithinWindow(events: UsageEvent[], windowStartMs: number): UsageTotals {
  let inputTokens = 0;
  let outputTokens = 0;
  let cacheReadTokens = 0;
  for (const event of events) {
    if (event.timestampMs < windowStartMs) continue;
    inputTokens += event.inputTokens;
    outputTokens += event.outputTokens;
    cacheReadTokens += event.cacheReadTokens;
  }
  return { inputTokens, outputTokens, totalTokens: inputTokens + outputTokens, cacheReadTokens };
}

// Module-scope memo: path -> the events last read from it, plus the mtime/size
// stamped at read time. Module scope (not per-aggregator) is deliberate — an
// aggregator is created fresh per SSE connection, so a narrower-scoped memo
// would be cold on every browser tab and useless across reconnects.
//
// Cross-file dedup is NEVER stored here — only within-file dedup (done once,
// in collectFileEvents, at read time). The global cross-file dedup is rebuilt
// from scratch on every collectUsage call, in mergeCandidateEvents below. A
// persisted cross-file seenIds would be wrong: if id X was first counted from
// file A, and A later ages out of the 7-day window, a persisted set would go
// on suppressing X from file B even though B is still in-window — a silent,
// permanent undercount. Rebuilding at merge time avoids that because an
// aged-out file simply isn't a candidate anymore, so it can't win the id.
interface CachedFile {
  mtimeMs: number;
  size: number;
  events: UsageEvent[];
}

const fileMemo = new Map<string, CachedFile>();
let inFlight: Promise<UsageSummary> | null = null;

// Test-only: clears the memo and any in-flight collect so tests don't leak
// state into each other. Module-scope state persists across the whole test
// file otherwise.
export function resetUsageMemo(): void {
  fileMemo.clear();
  inFlight = null;
}

// For each candidate: reuse the memo's events if mtime AND size both still
// match what was last read; otherwise read the file fresh and replace the
// memo entry (or evict it, if the read failed and the file was never seen —
// collectFileEvents returns [] either way, cached as the current truth).
async function collectCandidateEvents(path: string, mtimeMs: number, size: number): Promise<UsageEvent[]> {
  const cached = fileMemo.get(path);
  if (false && cached && cached.mtimeMs === mtimeMs && cached.size === size) {
    return cached.events;
  }
  const events = await collectFileEvents(path);
  fileMemo.set(path, { mtimeMs, size, events });
  return events;
}

// Rebuilds the global cross-file dedup EVERY call, over the candidate set
// (not the memo — see fileMemo's comment on why persisting dedup is wrong).
// Iterating candidates rather than all memo entries is what makes an aged-out
// file's events disappear from the total for free: a file that fell out of
// the week window is no longer a candidate, so it can't contribute here even
// though it may still sit in the memo until the next eviction pass.
function mergeCandidateEvents(perFileEvents: UsageEvent[][]): UsageEvent[] {
  const merged: UsageEvent[] = [];
  const seenIds = new Set<string>();
  for (const events of perFileEvents) {
    for (const event of events) {
      if (seenIds.has(event.messageId)) continue;
      seenIds.add(event.messageId);
      merged.push(event);
    }
  }
  return merged;
}

async function collectUsageUncached(baseDir: string, now: Date): Promise<UsageSummary> {
  const nowMs = now.getTime();
  const weekStartMs = nowMs - SEVEN_DAYS_MS;
  const fiveHourStartMs = nowMs - FIVE_HOURS_MS;

  try {
    readdirSync(baseDir);
  } catch {
    return { last5h: null, week: null };
  }

  const files: string[] = [];
  listJsonlFiles(baseDir, files);

  const candidates: { path: string; mtimeMs: number; size: number }[] = [];
  for (const path of files) {
    try {
      const stat = statSync(path);
      if (stat.mtimeMs >= weekStartMs) {
        candidates.push({ path, mtimeMs: stat.mtimeMs, size: stat.size });
      }
    } catch {
      continue;
    }
  }

  // Evict memo entries for paths no longer in the candidate set (aged out of
  // the week window, or deleted) so the memo can't grow unbounded.
  const candidatePaths = new Set(candidates.map((c) => c.path));
  for (const path of fileMemo.keys()) {
    if (!candidatePaths.has(path)) fileMemo.delete(path);
  }

  const perFileEvents = await Promise.all(
    candidates.map((c) => collectCandidateEvents(c.path, c.mtimeMs, c.size))
  );
  const events = mergeCandidateEvents(perFileEvents);

  return {
    last5h: sumWithinWindow(events, fiveHourStartMs),
    week: sumWithinWindow(events, weekStartMs),
  };
}

// baseDir is a ~/.claude/projects-shaped tree: <baseDir>/<slug>/ holding
// transcript *.jsonl files (directly or nested). Sums usage across ALL
// project transcripts within each rolling window. Only files whose mtime
// falls within the (wider) week window are read at all — a cheap prefilter,
// since an old file's content cannot contain in-window events by definition
// (transcripts are append-only, so mtime is a safe upper bound on content
// recency). Never throws: an unreadable base dir degrades both sections to
// null rather than propagating an error.
//
// Single-flight: concurrent calls (e.g. two open browser tabs each opening
// an SSE connection) share one in-flight promise rather than each re-reading
// every candidate file. The promise is assigned before any await so a second
// call arriving synchronously-after still sees it.
export async function collectUsage(baseDir: string, now: Date): Promise<UsageSummary> {
  if (inFlight) return inFlight;
  inFlight = collectUsageUncached(baseDir, now);
  try {
    return await inFlight;
  } finally {
    inFlight = null;
  }
}
