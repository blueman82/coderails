import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, utimesSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { collectUsage, resetUsageMemo } from "../src/lib/collect/usage";

const tmpDirs: string[] = [];

function makeTmpBase(): string {
  const dir = mkdtempSync(join(tmpdir(), "dashboard-usage-test-"));
  tmpDirs.push(dir);
  return dir;
}

// Real transcript lines carry an "assistant" line per streaming step, with the
// SAME message.id repeated across consecutive lines and an IDENTICAL usage
// snapshot on each repeat (confirmed against real ~/.claude/projects data) —
// summing every line overcounts; callers must dedupe by message.id first.
function assistantLine(
  id: string,
  timestamp: string,
  usage: { input_tokens: number; output_tokens: number; cache_creation_input_tokens?: number; cache_read_input_tokens?: number }
): string {
  return JSON.stringify({
    type: "assistant",
    timestamp,
    message: { id, role: "assistant", usage },
  });
}

// Writes <base>/<slug>/<file>.jsonl with the given raw lines, and sets the
// file's mtime so the mtime-prefilter (cheap skip of definitely-out-of-window
// files) doesn't exclude it in tests that need the content read.
function writeTranscript(base: string, slug: string, file: string, lines: string[], mtime: Date): void {
  const dir = join(base, slug);
  mkdirSync(dir, { recursive: true });
  const path = join(dir, file);
  writeFileSync(path, lines.join("\n") + (lines.length ? "\n" : ""));
  utimesSync(path, mtime, mtime);
}

afterEach(() => {
  for (const dir of tmpDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

beforeEach(() => {
  resetUsageMemo();
});

describe("collectUsage", () => {
  const NOW = new Date("2026-07-06T18:00:00Z");

  it("sums input/output tokens for a single assistant message within the 5h window", async () => {
    const base = makeTmpBase();
    writeTranscript(
      base,
      "-proj",
      "a.jsonl",
      [assistantLine("msg_1", "2026-07-06T17:00:00.000Z", { input_tokens: 10, output_tokens: 20 })],
      NOW
    );
    const usage = await collectUsage(base, NOW);
    expect(usage.last5h).toEqual({ inputTokens: 10, outputTokens: 20, totalTokens: 30, cacheReadTokens: 0 });
  });

  it("dedupes repeated lines sharing the same message.id, counting the usage once", async () => {
    const base = makeTmpBase();
    writeTranscript(
      base,
      "-proj",
      "a.jsonl",
      [
        assistantLine("msg_1", "2026-07-06T17:00:00.000Z", { input_tokens: 1, output_tokens: 100 }),
        assistantLine("msg_1", "2026-07-06T17:00:01.000Z", { input_tokens: 1, output_tokens: 100 }),
        assistantLine("msg_1", "2026-07-06T17:00:02.000Z", { input_tokens: 1, output_tokens: 100 }),
      ],
      NOW
    );
    const usage = await collectUsage(base, NOW);
    expect(usage.last5h).toEqual({ inputTokens: 1, outputTokens: 100, totalTokens: 101, cacheReadTokens: 0 });
  });

  it("counts cache_creation_input_tokens and cache_read_input_tokens toward inputTokens", async () => {
    const base = makeTmpBase();
    writeTranscript(
      base,
      "-proj",
      "a.jsonl",
      [
        assistantLine("msg_1", "2026-07-06T17:00:00.000Z", {
          input_tokens: 2,
          output_tokens: 50,
          cache_creation_input_tokens: 1000,
          cache_read_input_tokens: 500,
        }),
      ],
      NOW
    );
    const usage = await collectUsage(base, NOW);
    expect(usage.last5h).toEqual({ inputTokens: 1502, outputTokens: 50, totalTokens: 1552, cacheReadTokens: 500 });
  });

  it("excludes a message stamped just before the 5h window (boundary)", async () => {
    const base = makeTmpBase();
    const justOutside = new Date(NOW.getTime() - 5 * 60 * 60_000 - 1000).toISOString();
    writeTranscript(
      base,
      "-proj",
      "a.jsonl",
      [assistantLine("msg_1", justOutside, { input_tokens: 10, output_tokens: 20 })],
      NOW
    );
    const usage = await collectUsage(base, NOW);
    expect(usage.last5h).toEqual({ inputTokens: 0, outputTokens: 0, totalTokens: 0, cacheReadTokens: 0 });
  });

  it("includes a message stamped exactly at the 5h boundary", async () => {
    const base = makeTmpBase();
    const atBoundary = new Date(NOW.getTime() - 5 * 60 * 60_000).toISOString();
    writeTranscript(
      base,
      "-proj",
      "a.jsonl",
      [assistantLine("msg_1", atBoundary, { input_tokens: 10, output_tokens: 20 })],
      NOW
    );
    const usage = await collectUsage(base, NOW);
    expect(usage.last5h).toEqual({ inputTokens: 10, outputTokens: 20, totalTokens: 30, cacheReadTokens: 0 });
  });

  it("includes a message stamped just under the 7-day week boundary but excludes one just past it", async () => {
    const base = makeTmpBase();
    const insideWeek = new Date(NOW.getTime() - 7 * 24 * 60 * 60_000 + 1000).toISOString();
    const outsideWeek = new Date(NOW.getTime() - 7 * 24 * 60 * 60_000 - 1000).toISOString();
    writeTranscript(
      base,
      "-proj",
      "a.jsonl",
      [
        assistantLine("msg_in", insideWeek, { input_tokens: 5, output_tokens: 5 }),
        assistantLine("msg_out", outsideWeek, { input_tokens: 99, output_tokens: 99 }),
      ],
      NOW
    );
    const usage = await collectUsage(base, NOW);
    expect(usage.week).toEqual({ inputTokens: 5, outputTokens: 5, totalTokens: 10, cacheReadTokens: 0 });
  });

  it("sums usage across multiple project transcripts", async () => {
    const base = makeTmpBase();
    writeTranscript(
      base,
      "-proj-a",
      "a.jsonl",
      [assistantLine("msg_1", "2026-07-06T17:00:00.000Z", { input_tokens: 10, output_tokens: 20 })],
      NOW
    );
    writeTranscript(
      base,
      "-proj-b",
      "b.jsonl",
      [assistantLine("msg_2", "2026-07-06T17:30:00.000Z", { input_tokens: 5, output_tokens: 5 })],
      NOW
    );
    const usage = await collectUsage(base, NOW);
    expect(usage.last5h).toEqual({ inputTokens: 15, outputTokens: 25, totalTokens: 40, cacheReadTokens: 0 });
  });

  it("skips malformed JSON lines silently rather than throwing", async () => {
    const base = makeTmpBase();
    writeTranscript(
      base,
      "-proj",
      "a.jsonl",
      ["not valid json {{{", assistantLine("msg_1", "2026-07-06T17:00:00.000Z", { input_tokens: 10, output_tokens: 20 })],
      NOW
    );
    const usage = await collectUsage(base, NOW);
    expect(usage.last5h).toEqual({ inputTokens: 10, outputTokens: 20, totalTokens: 30, cacheReadTokens: 0 });
  });

  it("skips lines of the wrong shape (non-assistant type, missing usage) silently", async () => {
    const base = makeTmpBase();
    writeTranscript(
      base,
      "-proj",
      "a.jsonl",
      [
        JSON.stringify({ type: "user", timestamp: "2026-07-06T17:00:00.000Z", message: { role: "user", content: "hi" } }),
        JSON.stringify({ type: "assistant", timestamp: "2026-07-06T17:00:00.000Z", message: { id: "msg_bare", role: "assistant" } }),
        JSON.stringify({ type: "summary", summary: "some summary line" }),
        assistantLine("msg_1", "2026-07-06T17:00:00.000Z", { input_tokens: 10, output_tokens: 20 }),
      ],
      NOW
    );
    const usage = await collectUsage(base, NOW);
    expect(usage.last5h).toEqual({ inputTokens: 10, outputTokens: 20, totalTokens: 30, cacheReadTokens: 0 });
  });

  it("ignores blank lines", async () => {
    const base = makeTmpBase();
    writeTranscript(
      base,
      "-proj",
      "a.jsonl",
      ["", assistantLine("msg_1", "2026-07-06T17:00:00.000Z", { input_tokens: 10, output_tokens: 20 }), ""],
      NOW
    );
    const usage = await collectUsage(base, NOW);
    expect(usage.last5h).toEqual({ inputTokens: 10, outputTokens: 20, totalTokens: 30, cacheReadTokens: 0 });
  });

  it("only reads non-.jsonl files if present is a no-op (ignores unrelated files)", async () => {
    const base = makeTmpBase();
    mkdirSync(join(base, "-proj"), { recursive: true });
    writeFileSync(join(base, "-proj", "notes.txt"), "irrelevant content");
    const usage = await collectUsage(base, NOW);
    expect(usage.last5h).toEqual({ inputTokens: 0, outputTokens: 0, totalTokens: 0, cacheReadTokens: 0 });
  });

  it("returns null sections with a note when the base dir is unreadable", async () => {
    const usage = await collectUsage(join(tmpdir(), "does-not-exist-usage-base"), NOW);
    expect(usage.last5h).toBeNull();
    expect(usage.week).toBeNull();
  });

  it("never throws even when called with a garbage path", async () => {
    await expect(collectUsage("\0invalid", NOW)).resolves.not.toThrow();
  });

  it("prefilters files whose mtime is older than the week window (cheap skip)", async () => {
    const base = makeTmpBase();
    const longAgo = new Date(NOW.getTime() - 30 * 24 * 60 * 60_000);
    // File mtime is far older than the window AND its content (if read) would
    // also fall outside — this just confirms the result is correct either way;
    // the prefilter is a performance detail, not an observable behavior on its own.
    writeTranscript(
      base,
      "-proj",
      "old.jsonl",
      [assistantLine("msg_old", longAgo.toISOString(), { input_tokens: 999, output_tokens: 999 })],
      longAgo
    );
    const usage = await collectUsage(base, NOW);
    expect(usage.week).toEqual({ inputTokens: 0, outputTokens: 0, totalTokens: 0, cacheReadTokens: 0 });
  });
});

// vi.spyOn can't wrap a named ESM export ("Cannot redefine property"), confirmed
// elsewhere in this suite (see runlog.test.ts) — so a re-read count is taken via
// vi.doMock on node:fs, wrapping createReadStream with a counting spy that
// delegates to the real implementation, then a fresh dynamic import of the
// module under test so it picks up the mocked binding.
describe("collectUsage memo", () => {
  const NOW = new Date("2026-07-06T18:00:00Z");

  afterEach(() => {
    vi.doUnmock("node:fs");
    vi.resetModules();
  });

  async function loadWithReadSpy() {
    vi.resetModules();
    const createReadStreamSpy = vi.fn();
    vi.doMock("node:fs", async () => {
      const actual = await vi.importActual<typeof import("node:fs")>("node:fs");
      return {
        ...actual,
        createReadStream: (...args: Parameters<typeof actual.createReadStream>) => {
          createReadStreamSpy(...args);
          return actual.createReadStream(...args);
        },
      };
    });
    const mod = await import("../src/lib/collect/usage");
    return { collectUsage: mod.collectUsage, resetUsageMemo: mod.resetUsageMemo, createReadStreamSpy };
  }

  it("does not re-read a file whose mtime and size are unchanged between collects", async () => {
    const { collectUsage: collectUsageSpied, resetUsageMemo: reset, createReadStreamSpy } = await loadWithReadSpy();
    reset();
    const base = makeTmpBase();
    writeTranscript(
      base,
      "-proj",
      "a.jsonl",
      [assistantLine("msg_1", "2026-07-06T17:00:00.000Z", { input_tokens: 10, output_tokens: 20 })],
      NOW
    );

    await collectUsageSpied(base, NOW);
    expect(createReadStreamSpy).toHaveBeenCalledTimes(1);

    await collectUsageSpied(base, NOW);
    expect(createReadStreamSpy).toHaveBeenCalledTimes(1); // still 1 — second collect hit the memo
  });
});
