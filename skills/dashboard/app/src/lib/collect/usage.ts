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

// baseDir is a ~/.claude/projects-shaped tree: <baseDir>/<slug>/ holding
// transcript *.jsonl files (directly or nested). Sums usage across ALL
// project transcripts within each rolling window. Only files whose mtime
// falls within the (wider) week window are read at all — a cheap prefilter,
// since an old file's content cannot contain in-window events by definition
// (transcripts are append-only, so mtime is a safe upper bound on content
// recency). Never throws: an unreadable base dir degrades both sections to
// null rather than propagating an error.
export async function collectUsage(baseDir: string, now: Date): Promise<UsageSummary> {
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

  const candidates = files.filter((path) => {
    try {
      return statSync(path).mtimeMs >= weekStartMs;
    } catch {
      return false;
    }
  });

  const events: UsageEvent[] = [];
  const seenIds = new Set<string>();
  for (const path of candidates) {
    await collectFileEvents(path, seenIds, events);
  }

  return {
    last5h: sumWithinWindow(events, fiveHourStartMs),
    week: sumWithinWindow(events, weekStartMs),
  };
}
