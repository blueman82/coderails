import { makeTmpBase, assistantLine, writeTranscript } from "./usage.fixture";
import { describe, it, expect, afterEach, vi } from "vitest";
import { writeFileSync, utimesSync } from "node:fs";
import { join } from "node:path";

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

  it("re-reads a file whose mtime changed since the last collect", async () => {
    const { collectUsage: collectUsageSpied, resetUsageMemo: reset, createReadStreamSpy } = await loadWithReadSpy();
    reset();
    const base = makeTmpBase();
    const path = join(base, "-proj", "a.jsonl");
    writeTranscript(
      base,
      "-proj",
      "a.jsonl",
      [assistantLine("msg_1", "2026-07-06T17:00:00.000Z", { input_tokens: 10, output_tokens: 20 })],
      NOW
    );

    await collectUsageSpied(base, NOW);
    expect(createReadStreamSpy).toHaveBeenCalledTimes(1);

    // Same content, but bump mtime forward — same size, different mtime.
    const laterMtime = new Date(NOW.getTime() + 1000);
    utimesSync(path, laterMtime, laterMtime);

    await collectUsageSpied(base, NOW);
    expect(createReadStreamSpy).toHaveBeenCalledTimes(2);
  });

  it("re-reads a file whose size changed since the last collect, even if mtime did not", async () => {
    const { collectUsage: collectUsageSpied, resetUsageMemo: reset, createReadStreamSpy } = await loadWithReadSpy();
    reset();
    const base = makeTmpBase();
    const path = join(base, "-proj", "a.jsonl");
    writeTranscript(
      base,
      "-proj",
      "a.jsonl",
      [assistantLine("msg_1", "2026-07-06T17:00:00.000Z", { input_tokens: 10, output_tokens: 20 })],
      NOW
    );

    await collectUsageSpied(base, NOW);
    expect(createReadStreamSpy).toHaveBeenCalledTimes(1);

    // Append a second event but pin mtime back to the same value the memo
    // recorded — an artificial way to isolate the size-only signal.
    writeFileSync(
      path,
      [
        assistantLine("msg_1", "2026-07-06T17:00:00.000Z", { input_tokens: 10, output_tokens: 20 }),
        assistantLine("msg_2", "2026-07-06T17:05:00.000Z", { input_tokens: 1, output_tokens: 1 }),
      ].join("\n") + "\n"
    );
    utimesSync(path, NOW, NOW);

    await collectUsageSpied(base, NOW);
    expect(createReadStreamSpy).toHaveBeenCalledTimes(2);
  });

  it("evicts a memo entry once its path leaves the candidate set (ages out of the week window)", async () => {
    const { collectUsage: collectUsageSpied, resetUsageMemo: reset, createReadStreamSpy } = await loadWithReadSpy();
    reset();
    const base = makeTmpBase();
    const path = join(base, "-proj", "a.jsonl");
    writeTranscript(
      base,
      "-proj",
      "a.jsonl",
      [assistantLine("msg_1", "2026-07-06T17:00:00.000Z", { input_tokens: 10, output_tokens: 20 })],
      NOW
    );

    await collectUsageSpied(base, NOW);
    expect(createReadStreamSpy).toHaveBeenCalledTimes(1);

    // Push the file's mtime outside the 7-day window so it drops out of the
    // candidate set on the next collect.
    const longAgo = new Date(NOW.getTime() - 30 * 24 * 60 * 60_000);
    utimesSync(path, longAgo, longAgo);

    await collectUsageSpied(base, NOW);
    // Still 1 — the file is no longer a candidate at all, so it is neither
    // memo-hit NOR re-read; it's simply excluded from this collect.
    expect(createReadStreamSpy).toHaveBeenCalledTimes(1);

    // Bring it back into the window with a fresh mtime: since its memo entry
    // was evicted while it was out of the candidate set, this must be a full
    // re-read (not a stale hit against the evicted entry).
    utimesSync(path, NOW, NOW);
    await collectUsageSpied(base, NOW);
    expect(createReadStreamSpy).toHaveBeenCalledTimes(2);
  });

  it("keeps totals correct across a shared message id when the first file ages out of the window (never silently persists cross-file dedup)", async () => {
    const { collectUsage: collectUsageSpied, resetUsageMemo: reset } = await loadWithReadSpy();
    reset();
    const base = makeTmpBase();
    const pathA = join(base, "-proj-a", "a.jsonl");

    // File A and file B both carry an assistant line for the SAME message id
    // (this happens for real: a compacted/continued session can re-emit an
    // earlier message's line into a new transcript file). First collect: A
    // is read first (alphabetical dir order), wins the id, B's copy is
    // suppressed as the cross-file duplicate.
    writeTranscript(
      base,
      "-proj-a",
      "a.jsonl",
      [assistantLine("msg_shared", "2026-07-06T17:00:00.000Z", { input_tokens: 10, output_tokens: 20 })],
      NOW
    );
    writeTranscript(
      base,
      "-proj-b",
      "b.jsonl",
      [assistantLine("msg_shared", "2026-07-06T17:00:00.000Z", { input_tokens: 10, output_tokens: 20 })],
      NOW
    );

    const first = await collectUsageSpied(base, NOW);
    expect(first.last5h).toEqual({ inputTokens: 10, outputTokens: 20, totalTokens: 30, cacheReadTokens: 0 });

    // Now push A's mtime out of the 7-day window so A drops out of the
    // candidate set entirely. B is still in-window and still carries
    // msg_shared. A naive implementation that persists cross-file dedup
    // (marks msg_shared "seen" forever once A wins it) would keep
    // suppressing it from B here, undercounting. The correct behaviour
    // rebuilds dedup from the candidate set every time, so B's copy of
    // msg_shared is now counted (A is gone, nothing else claims the id).
    const longAgo = new Date(NOW.getTime() - 30 * 24 * 60 * 60_000);
    utimesSync(pathA, longAgo, longAgo);

    const second = await collectUsageSpied(base, NOW);
    expect(second.last5h).toEqual({ inputTokens: 10, outputTokens: 20, totalTokens: 30, cacheReadTokens: 0 });
  });

  it("runs the work once for two concurrent collectUsage calls (single-flight)", async () => {
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

    const [first, second] = await Promise.all([collectUsageSpied(base, NOW), collectUsageSpied(base, NOW)]);

    expect(createReadStreamSpy).toHaveBeenCalledTimes(1);
    expect(first).toEqual(second);
  });
});
