import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { collectHealth } from "../src/lib/collect/health";

const tmpDirs: string[] = [];
const MISSING_PROJECTS_DIR = join(tmpdir(), "does-not-exist-health-projects");

function makeTmpDisciplineLog(lines: string[]): string {
  const dir = mkdtempSync(join(tmpdir(), "dashboard-health-test-"));
  tmpDirs.push(dir);
  const path = join(dir, "discipline.log");
  writeFileSync(path, lines.join("\n") + (lines.length ? "\n" : ""));
  return path;
}

function assistantLine(
  id: string,
  timestamp: string,
  inputTokens: number,
  outputTokens: number,
  cacheReadTokens = 0
): string {
  return JSON.stringify({
    type: "assistant",
    timestamp,
    message: {
      id,
      role: "assistant",
      usage: {
        input_tokens: inputTokens,
        output_tokens: outputTokens,
        ...(cacheReadTokens > 0 ? { cache_read_input_tokens: cacheReadTokens } : {}),
      },
    },
  });
}

function makeTmpProjectsDir(lines: string[]): string {
  const dir = mkdtempSync(join(tmpdir(), "dashboard-health-usage-test-"));
  tmpDirs.push(dir);
  const projectDir = join(dir, "-proj");
  mkdirSync(projectDir, { recursive: true });
  writeFileSync(join(projectDir, "a.jsonl"), lines.join("\n") + (lines.length ? "\n" : ""));
  return dir;
}

// Creates <dir>/-proj/<sessionId>/retro.json carrying a frozen cost block —
// mirrors the real ~/.claude/agentic-loop/<slug>/<sessionId>/ tree.
function makeTmpLoopsDir(loops: { sessionId: string; created: string; usd: number; tokens: number }[]): string {
  const dir = mkdtempSync(join(tmpdir(), "dashboard-health-loops-test-"));
  tmpDirs.push(dir);
  for (const loop of loops) {
    const loopDir = join(dir, "-proj", loop.sessionId);
    mkdirSync(loopDir, { recursive: true });
    writeFileSync(join(loopDir, "progress.json"), JSON.stringify({ created: loop.created }));
    writeFileSync(
      join(loopDir, "retro.json"),
      JSON.stringify({
        created: loop.created,
        cost: { total_usd_estimate: loop.usd, total_tokens: loop.tokens, prices_as_of: "2026-07-01" },
      })
    );
  }
  return dir;
}

afterEach(() => {
  for (const dir of tmpDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("collectHealth", () => {
  it("always returns exactly the six documented tile keys", async () => {
    const tiles = await collectHealth({
      disciplineLogPath: join(tmpdir(), "does-not-exist.log"),
      projectsDir: MISSING_PROJECTS_DIR,
      loopsDir: join(tmpdir(), "does-not-exist-health-loops"),
    });
    expect(tiles.map((t) => t.key).sort()).toEqual(
      ["costMonth", "costWeek", "hooksFired", "lintFindings", "usage5h", "usageWeek"].sort()
    );
  });

  it("reports costWeek and costMonth as unavailable (null, not $0.00) when the loops dir has no retro.json sources", async () => {
    const tiles = await collectHealth({
      disciplineLogPath: join(tmpdir(), "does-not-exist.log"),
      projectsDir: MISSING_PROJECTS_DIR,
      loopsDir: join(tmpdir(), "does-not-exist-health-loops"),
    });
    const week = tiles.find((t) => t.key === "costWeek");
    const month = tiles.find((t) => t.key === "costMonth");
    expect(week?.value).toBeNull();
    expect(week?.note).toBe("unavailable: no completed loops in this window");
    expect(month?.value).toBeNull();
    expect(month?.note).toBe("unavailable: no completed loops in this window");
  });

  it("sums frozen retro.json cost into costWeek, showing the summed token count and the shared prices_as_of as a staleness note", async () => {
    const now = new Date("2026-07-15T12:00:00Z");
    const loopsDir = makeTmpLoopsDir([
      { sessionId: "sess-1", created: "2026-07-14T10:00:00Z", usd: 1.5, tokens: 100_000 },
      { sessionId: "sess-2", created: "2026-07-13T10:00:00Z", usd: 2.25, tokens: 50_000 },
    ]);
    const tiles = await collectHealth({
      disciplineLogPath: join(tmpdir(), "does-not-exist.log"),
      projectsDir: MISSING_PROJECTS_DIR,
      loopsDir,
      now,
    });
    const week = tiles.find((t) => t.key === "costWeek");
    expect(week?.value).toBe("$3.75");
    expect(week?.note).toBe("150K tokens · completed loops only · prices as of 2026-07-01");
  });

  it("reports usage5h as unavailable when the projects dir has no local transcripts", async () => {
    const tiles = await collectHealth({
      disciplineLogPath: join(tmpdir(), "does-not-exist.log"),
      projectsDir: MISSING_PROJECTS_DIR,
    });
    const tile = tiles.find((t) => t.key === "usage5h");
    expect(tile?.value).toBeNull();
    expect(tile?.note).toMatch(/^unavailable: /);
  });

  it("reports usageWeek as unavailable when the projects dir has no local transcripts", async () => {
    const tiles = await collectHealth({
      disciplineLogPath: join(tmpdir(), "does-not-exist.log"),
      projectsDir: MISSING_PROJECTS_DIR,
    });
    const tile = tiles.find((t) => t.key === "usageWeek");
    expect(tile?.value).toBeNull();
    expect(tile?.note).toMatch(/^unavailable: /);
  });

  it("reports usage5h with a compact token count and in/out split from real transcripts", async () => {
    const now = new Date("2026-07-06T18:00:00Z");
    const projectsDir = makeTmpProjectsDir([
      assistantLine("msg_1", "2026-07-06T17:00:00.000Z", 400_000, 12_000),
    ]);
    const tiles = await collectHealth({
      disciplineLogPath: join(tmpdir(), "does-not-exist.log"),
      projectsDir,
      now,
    });
    const tile = tiles.find((t) => t.key === "usage5h");
    expect(tile?.value).toBe("412K tok");
    expect(tile?.note).toBe("in 400K / out 12K");
  });

  it("names the cache-read share in the note when cache re-reads contribute to the input total", async () => {
    const now = new Date("2026-07-06T18:00:00Z");
    const projectsDir = makeTmpProjectsDir([
      assistantLine("msg_1", "2026-07-06T17:00:00.000Z", 100_000, 12_000, 300_000),
    ]);
    const tiles = await collectHealth({
      disciplineLogPath: join(tmpdir(), "does-not-exist.log"),
      projectsDir,
      now,
    });
    const tile = tiles.find((t) => t.key === "usage5h");
    expect(tile?.value).toBe("412K tok");
    expect(tile?.note).toBe("in 400K (300K cache) / out 12K");
  });

  it("reports usageWeek summed independently of the 5h window", async () => {
    const now = new Date("2026-07-06T18:00:00Z");
    const sixDaysAgo = new Date(now.getTime() - 6 * 24 * 60 * 60_000).toISOString();
    const projectsDir = makeTmpProjectsDir([assistantLine("msg_1", sixDaysAgo, 1_000_000, 500_000)]);
    const tiles = await collectHealth({
      disciplineLogPath: join(tmpdir(), "does-not-exist.log"),
      projectsDir,
      now,
    });
    const usage5h = tiles.find((t) => t.key === "usage5h");
    const usageWeek = tiles.find((t) => t.key === "usageWeek");
    expect(usage5h?.value).toBe("0 tok");
    expect(usageWeek?.value).toBe("1.5M tok");
  });

  it("reports lintFindings as permanently unavailable (no persisted wiki-lint report file)", async () => {
    const tiles = await collectHealth({ disciplineLogPath: join(tmpdir(), "does-not-exist.log") });
    const tile = tiles.find((t) => t.key === "lintFindings");
    expect(tile?.value).toBeNull();
    expect(tile?.note).toMatch(/^unavailable: /);
  });

  it("reports hooksFired as unavailable with a reason when the discipline log is unreadable", async () => {
    const tiles = await collectHealth({ disciplineLogPath: join(tmpdir(), "does-not-exist.log") });
    const tile = tiles.find((t) => t.key === "hooksFired");
    expect(tile?.value).toBeNull();
    expect(tile?.note).toMatch(/^unavailable: /);
  });

  it("counts hook invocation lines from a real discipline log", async () => {
    const path = makeTmpDisciplineLog([
      "2026-07-06T15:19:45+01:00 hook=loop_stall_guard session=abc invocations=0 active=0 blocked=0",
      "2026-07-06T15:19:45+01:00 hook=confidence_labels session=abc text_len=405 attempts=0 matched=1 would_block=0",
      "2026-07-06T15:19:56+01:00 hook=verify_loop session=abc text_len=151 attempts=0 files=4 dnv_items=0 resolvable_dnv_items=0 blocked=0",
    ]);
    const tiles = await collectHealth({
      disciplineLogPath: path,
      now: new Date("2026-07-06T18:00:00+01:00"),
    });
    const tile = tiles.find((t) => t.key === "hooksFired");
    expect(tile?.value).toBe("3");
    expect(tile?.note).toBeUndefined();
  });

  it("counts zero for an empty discipline log without throwing", async () => {
    const path = makeTmpDisciplineLog([]);
    const tiles = await collectHealth({ disciplineLogPath: path });
    const tile = tiles.find((t) => t.key === "hooksFired");
    expect(tile?.value).toBe("0");
  });

  it("ignores blank lines when counting hook invocations", async () => {
    const path = makeTmpDisciplineLog([
      "2026-07-06T15:19:45+01:00 hook=loop_stall_guard session=abc invocations=0 active=0 blocked=0",
      "",
      "2026-07-06T15:19:56+01:00 hook=verify_loop session=abc text_len=151 attempts=0 files=4 dnv_items=0 resolvable_dnv_items=0 blocked=0",
    ]);
    const tiles = await collectHealth({
      disciplineLogPath: path,
      now: new Date("2026-07-06T18:00:00+01:00"),
    });
    const tile = tiles.find((t) => t.key === "hooksFired");
    expect(tile?.value).toBe("2");
  });

  it("never throws even when called with no options (uses real default paths)", async () => {
    await expect(collectHealth()).resolves.not.toThrow();
  });

  describe("hooksFired scoped to today", () => {
    const TODAY = new Date("2026-07-06T18:00:00+01:00");

    it("counts only lines stamped today, excluding older-day lines and a non-timestamp line", async () => {
      const path = makeTmpDisciplineLog([
        "2026-07-06T09:00:00+01:00 hook=confidence_labels session=abc matched=1 would_block=0",
        "2026-07-05T23:59:59+01:00 hook=verify_loop session=abc blocked=0",
        "2026-07-01T12:00:00+01:00 hook=loop_stall_guard session=abc blocked=0",
        "not-a-timestamp hook=weird session=abc blocked=0",
        "2026-07-06T17:30:00+01:00 hook=loop_state_guard session=abc blocked=0",
      ]);
      const tiles = await collectHealth({ disciplineLogPath: path, now: TODAY });
      const tile = tiles.find((t) => t.key === "hooksFired");
      expect(tile?.value).toBe("2");
      expect(tile?.note).toBeUndefined();
    });

    it("counts a line stamped 00:00:00 today", async () => {
      const path = makeTmpDisciplineLog([
        "2026-07-06T00:00:00+01:00 hook=confidence_labels session=abc blocked=0",
      ]);
      const tiles = await collectHealth({ disciplineLogPath: path, now: TODAY });
      const tile = tiles.find((t) => t.key === "hooksFired");
      expect(tile?.value).toBe("1");
    });

    it("excludes a line stamped 23:59:59 yesterday", async () => {
      const path = makeTmpDisciplineLog([
        "2026-07-05T23:59:59+01:00 hook=confidence_labels session=abc blocked=0",
      ]);
      const tiles = await collectHealth({ disciplineLogPath: path, now: TODAY });
      const tile = tiles.find((t) => t.key === "hooksFired");
      expect(tile?.value).toBe("0");
    });

    it("excludes lines whose leading token does not parse as a timestamp (fail-honest, does not guess their day)", async () => {
      const path = makeTmpDisciplineLog(["garbage line with no timestamp at all"]);
      const tiles = await collectHealth({ disciplineLogPath: path, now: TODAY });
      const tile = tiles.find((t) => t.key === "hooksFired");
      expect(tile?.value).toBe("0");
    });
  });
});
