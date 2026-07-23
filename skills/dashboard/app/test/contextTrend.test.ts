import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync, appendFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { collectContextTrend, type ContextTrendFileCache } from "../src/lib/collect/contextTrend";

const tmpDirs: string[] = [];

function makeTmpBase(): string {
  const dir = mkdtempSync(join(tmpdir(), "dashboard-token-trend-test-"));
  tmpDirs.push(dir);
  return dir;
}

afterEach(() => {
  for (const dir of tmpDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

// Same real-transcript shape usage.test.ts documents: an "assistant" line per
// streaming step, the SAME message.id repeated with an IDENTICAL cumulative
// usage snapshot — dedupe by message.id or overcount.
function assistantLine(
  id: string,
  timestamp: string,
  usage: { input_tokens: number; output_tokens: number; cache_read_input_tokens?: number }
): string {
  return JSON.stringify({ type: "assistant", timestamp, message: { id, role: "assistant", usage } });
}

// Real agentic-loop orchestrator transcripts carry the skill marker inside
// ordinary message content — any line containing the marker string qualifies.
function markerLine(timestamp: string): string {
  return JSON.stringify({
    type: "user",
    timestamp,
    message: { role: "user", content: "loading coderails:agentic-loop for this run" },
  });
}

// Real compaction records (verified against ~/.claude/projects transcripts):
// type "system", subtype "compact_boundary", compactMetadata.trigger
// "manual"|"auto", plus a uuid that dedupes re-emitted copies.
function compactLine(uuid: string, timestamp: string, trigger: "manual" | "auto"): string {
  return JSON.stringify({
    type: "system",
    subtype: "compact_boundary",
    uuid,
    timestamp,
    compactMetadata: { trigger, pre_tokens: 12345 },
  });
}

interface SessionFixture {
  slug?: string;
  sid?: string;
  lines: string[];
  subagents?: boolean;
  subagentLines?: string[];
}

// Writes <base>/<slug>/<sid>.jsonl, plus an (empty or populated)
// <base>/<slug>/<sid>/subagents/ dir when subagents is true — the cohort
// signal that the session actually orchestrated workers.
function writeSession(base: string, fixture: SessionFixture): void {
  const slug = fixture.slug ?? "-users-h-github-coderails";
  const sid = fixture.sid ?? "session-1";
  const dir = join(base, slug);
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, `${sid}.jsonl`), fixture.lines.join("\n") + "\n");
  if (fixture.subagents) {
    const subDir = join(dir, sid, "subagents");
    mkdirSync(subDir, { recursive: true });
    if (fixture.subagentLines) {
      writeFileSync(join(subDir, "agent-1.jsonl"), fixture.subagentLines.join("\n") + "\n");
    }
  }
}

const NOW = new Date("2026-07-22T12:00:00Z");
const CUTOVER = Date.parse("2026-07-17T20:22:00Z");
const WINDOW_START = Date.parse("2026-07-07T00:00:00Z");

const BEFORE_TS = "2026-07-10T10:00:00.000Z";
const AFTER_TS = "2026-07-20T10:00:00.000Z";

function cohortLines(ts: string, perTurnTokens: number[], idPrefix = "msg"): string[] {
  return [
    markerLine(ts),
    ...perTurnTokens.map((cacheRead, i) =>
      assistantLine(`${idPrefix}_${i}`, ts, { input_tokens: 1, output_tokens: 1, cache_read_input_tokens: cacheRead })
    ),
  ];
}

describe("collectContextTrend — cohort membership", () => {
  it("includes a marker-carrying session with a subagents dir, orchestrator cache-read summed per unique message.id", async () => {
    const base = makeTmpBase();
    writeSession(base, { lines: cohortLines(BEFORE_TS, [100, 200]), subagents: true });
    const trend = await collectContextTrend(base, { now: NOW });
    expect(trend).not.toBeNull();
    expect(trend!.sessions).toHaveLength(1);
    expect(trend!.sessions[0]).toMatchObject({
      sessionId: "session-1",
      startMs: Date.parse(BEFORE_TS),
      turns: 2,
      cacheRead: 300,
    });
  });

  it("excludes a session with the marker but no subagents dir", async () => {
    const base = makeTmpBase();
    writeSession(base, { lines: cohortLines(BEFORE_TS, [100]), subagents: false });
    const trend = await collectContextTrend(base, { now: NOW });
    expect(trend!.sessions).toHaveLength(0);
  });

  it("excludes a session with a subagents dir but no agentic-loop marker", async () => {
    const base = makeTmpBase();
    writeSession(base, {
      lines: [assistantLine("msg_0", BEFORE_TS, { input_tokens: 1, output_tokens: 1, cache_read_input_tokens: 50 })],
      subagents: true,
    });
    const trend = await collectContextTrend(base, { now: NOW });
    expect(trend!.sessions).toHaveLength(0);
  });

  it("excludes a session whose first message timestamp predates the analysis window", async () => {
    const base = makeTmpBase();
    writeSession(base, { lines: cohortLines("2026-07-01T10:00:00.000Z", [100]), subagents: true });
    const trend = await collectContextTrend(base, { now: NOW });
    expect(trend!.sessions).toHaveLength(0);
  });

  it("excludes a session with zero assistant turns (no per-turn figure exists)", async () => {
    const base = makeTmpBase();
    writeSession(base, { lines: [markerLine(BEFORE_TS)], subagents: true });
    const trend = await collectContextTrend(base, { now: NOW });
    expect(trend!.sessions).toHaveLength(0);
  });

  it("ignores project dirs whose slug does not match the filter", async () => {
    const base = makeTmpBase();
    writeSession(base, { slug: "-users-h-github-otherproj", lines: cohortLines(BEFORE_TS, [100]), subagents: true });
    const trend = await collectContextTrend(base, { now: NOW });
    expect(trend!.sessions).toHaveLength(0);
  });

  it("includes worktree-suffixed coderails dirs (same project, same measures)", async () => {
    const base = makeTmpBase();
    writeSession(base, {
      slug: "-users-h-github-coderails--claude-worktrees-wu1",
      lines: cohortLines(BEFORE_TS, [100]),
      subagents: true,
    });
    const trend = await collectContextTrend(base, { now: NOW });
    expect(trend!.sessions).toHaveLength(1);
  });
});

describe("collectContextTrend — orchestrator-only scope", () => {
  it("does not count subagent transcript usage toward the orchestrator's totals", async () => {
    const base = makeTmpBase();
    writeSession(base, {
      lines: cohortLines(BEFORE_TS, [100]),
      subagents: true,
      subagentLines: [
        assistantLine("sub_0", BEFORE_TS, { input_tokens: 1, output_tokens: 1, cache_read_input_tokens: 999_999 }),
      ],
    });
    const trend = await collectContextTrend(base, { now: NOW });
    expect(trend!.sessions).toHaveLength(1);
    expect(trend!.sessions[0].cacheRead).toBe(100);
    expect(trend!.sessions[0].turns).toBe(1);
  });

  it("dedupes repeated streaming lines sharing one message.id — one turn, one usage snapshot", async () => {
    const base = makeTmpBase();
    writeSession(base, {
      lines: [
        markerLine(BEFORE_TS),
        assistantLine("msg_0", BEFORE_TS, { input_tokens: 1, output_tokens: 1, cache_read_input_tokens: 500 }),
        assistantLine("msg_0", BEFORE_TS, { input_tokens: 1, output_tokens: 1, cache_read_input_tokens: 500 }),
        assistantLine("msg_0", BEFORE_TS, { input_tokens: 1, output_tokens: 1, cache_read_input_tokens: 500 }),
      ],
      subagents: true,
    });
    const trend = await collectContextTrend(base, { now: NOW });
    expect(trend!.sessions[0].turns).toBe(1);
    expect(trend!.sessions[0].cacheRead).toBe(500);
  });

  it("dates the session by its first non-null message timestamp, not any later one", async () => {
    const base = makeTmpBase();
    const first = "2026-07-16T23:44:00.000Z";
    writeSession(base, {
      lines: [
        JSON.stringify({ type: "summary", summary: "no timestamp here" }),
        markerLine(first),
        assistantLine("msg_0", AFTER_TS, { input_tokens: 1, output_tokens: 1, cache_read_input_tokens: 100 }),
      ],
      subagents: true,
    });
    const trend = await collectContextTrend(base, { now: NOW });
    // First timestamp (07-16) predates the cutover even though later activity
    // postdates it — the audit's real misfiling case; must bin as before.
    expect(trend!.sessions[0].startMs).toBe(Date.parse(first));
    expect(trend!.before.n).toBe(1);
    expect(trend!.after.n).toBe(0);
  });
});

describe("collectContextTrend — before/after split and stats", () => {
  it("splits sessions at the cutover: strictly-before goes before, exactly-at goes after", async () => {
    const base = makeTmpBase();
    const atCutover = new Date(CUTOVER).toISOString();
    writeSession(base, { sid: "s-before", lines: cohortLines(BEFORE_TS, [100], "b"), subagents: true });
    writeSession(base, { sid: "s-at", lines: cohortLines(atCutover, [200], "a"), subagents: true });
    const trend = await collectContextTrend(base, { now: NOW });
    expect(trend!.before.n).toBe(1);
    expect(trend!.after.n).toBe(1);
    expect(trend!.cutoverMs).toBe(CUTOVER);
  });

  it("computes per-side median and quartiles of cache-read per turn (lower nearest-rank)", async () => {
    const base = makeTmpBase();
    // Three before-sessions with per-turn 100, 200, 400 (single-turn each).
    writeSession(base, { sid: "s1", lines: cohortLines(BEFORE_TS, [100], "s1"), subagents: true });
    writeSession(base, { sid: "s2", lines: cohortLines(BEFORE_TS, [200], "s2"), subagents: true });
    writeSession(base, { sid: "s3", lines: cohortLines(BEFORE_TS, [400], "s3"), subagents: true });
    const trend = await collectContextTrend(base, { now: NOW });
    expect(trend!.before).toEqual({ n: 3, medianPerTurn: 200, q1PerTurn: 100, q3PerTurn: 200 });
  });

  it("averages an even-count median and derives per-turn from multi-turn sessions", async () => {
    const base = makeTmpBase();
    // Two after-sessions: 2 turns totalling 600 (300/turn) and 1 turn of 500.
    writeSession(base, { sid: "s1", lines: cohortLines(AFTER_TS, [200, 400], "s1"), subagents: true });
    writeSession(base, { sid: "s2", lines: cohortLines(AFTER_TS, [500], "s2"), subagents: true });
    const trend = await collectContextTrend(base, { now: NOW });
    expect(trend!.after.n).toBe(2);
    expect(trend!.after.medianPerTurn).toBe(400); // (300 + 500) / 2
  });

  it("reports an empty side as n=0 with null stats rather than fabricating numbers", async () => {
    const base = makeTmpBase();
    writeSession(base, { lines: cohortLines(BEFORE_TS, [100]), subagents: true });
    const trend = await collectContextTrend(base, { now: NOW });
    expect(trend!.after).toEqual({ n: 0, medianPerTurn: null, q1PerTurn: null, q3PerTurn: null });
  });

  it("sorts sessions by start time ascending", async () => {
    const base = makeTmpBase();
    writeSession(base, { sid: "late", lines: cohortLines(AFTER_TS, [100], "l"), subagents: true });
    writeSession(base, { sid: "early", lines: cohortLines(BEFORE_TS, [100], "e"), subagents: true });
    const trend = await collectContextTrend(base, { now: NOW });
    expect(trend!.sessions.map((s) => s.sessionId)).toEqual(["early", "late"]);
  });
});

describe("collectContextTrend — compaction events", () => {
  it("collects compactMetadata records with trigger and timestamp, sorted ascending", async () => {
    const base = makeTmpBase();
    writeSession(base, {
      lines: [
        ...cohortLines(BEFORE_TS, [100]),
        compactLine("uuid-b", "2026-07-14T18:26:48.000Z", "manual"),
        compactLine("uuid-a", "2026-07-08T07:35:27.000Z", "auto"),
      ],
      subagents: true,
    });
    const trend = await collectContextTrend(base, { now: NOW });
    expect(trend!.compactions).toEqual([
      { timestampMs: Date.parse("2026-07-08T07:35:27.000Z"), trigger: "auto" },
      { timestampMs: Date.parse("2026-07-14T18:26:48.000Z"), trigger: "manual" },
    ]);
  });

  it("dedupes compaction records re-emitted across files by uuid", async () => {
    const base = makeTmpBase();
    const record = compactLine("uuid-1", "2026-07-14T18:26:48.000Z", "manual");
    writeSession(base, { sid: "s1", lines: [...cohortLines(BEFORE_TS, [100], "s1"), record], subagents: true });
    writeSession(base, { sid: "s2", lines: [...cohortLines(BEFORE_TS, [100], "s2"), record], subagents: true });
    const trend = await collectContextTrend(base, { now: NOW });
    expect(trend!.compactions).toHaveLength(1);
  });

  it("counts compactions from non-cohort sessions too — inertness is a project-wide fact", async () => {
    const base = makeTmpBase();
    writeSession(base, {
      lines: [compactLine("uuid-1", "2026-07-14T18:26:48.000Z", "manual")],
      subagents: false,
    });
    const trend = await collectContextTrend(base, { now: NOW });
    expect(trend!.sessions).toHaveLength(0);
    expect(trend!.compactions).toHaveLength(1);
  });
});

describe("collectContextTrend — degradation and caching", () => {
  it("returns null when the base dir is unreadable", async () => {
    const trend = await collectContextTrend(join(tmpdir(), "does-not-exist-token-trend"), { now: NOW });
    expect(trend).toBeNull();
  });

  it("skips malformed JSON lines without losing the rest of the file", async () => {
    const base = makeTmpBase();
    writeSession(base, {
      lines: ["not json {{{", ...cohortLines(BEFORE_TS, [100])],
      subagents: true,
    });
    const trend = await collectContextTrend(base, { now: NOW });
    expect(trend!.sessions).toHaveLength(1);
  });

  it("re-parses a file that grew since the cached parse (append-only transcript growth)", async () => {
    const base = makeTmpBase();
    const cache: ContextTrendFileCache = new Map();
    writeSession(base, { lines: cohortLines(AFTER_TS, [100]), subagents: true });
    const first = await collectContextTrend(base, { now: NOW, cache });
    expect(first!.sessions[0].turns).toBe(1);

    appendFileSync(
      join(base, "-users-h-github-coderails", "session-1.jsonl"),
      assistantLine("msg_new", AFTER_TS, { input_tokens: 1, output_tokens: 1, cache_read_input_tokens: 300 }) + "\n"
    );
    const second = await collectContextTrend(base, { now: NOW, cache });
    expect(second!.sessions[0].turns).toBe(2);
    expect(second!.sessions[0].cacheRead).toBe(400);
  });

  it("returns identical results on a warm cache for unchanged files", async () => {
    const base = makeTmpBase();
    const cache: ContextTrendFileCache = new Map();
    writeSession(base, { lines: cohortLines(BEFORE_TS, [100, 200]), subagents: true });
    const cold = await collectContextTrend(base, { now: NOW, cache });
    const warm = await collectContextTrend(base, { now: NOW, cache });
    expect(warm).toEqual(cold);
  });

  it("exposes the fixed analysis window and cutover so the panel never re-declares them", async () => {
    const base = makeTmpBase();
    writeSession(base, { lines: cohortLines(BEFORE_TS, [100]), subagents: true });
    const trend = await collectContextTrend(base, { now: NOW });
    expect(trend!.windowStartMs).toBe(WINDOW_START);
    expect(trend!.cutoverMs).toBe(CUTOVER);
  });
});
