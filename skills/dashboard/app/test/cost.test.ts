import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { collectLoopCost } from "../src/lib/collect/cost";

const tmpDirs: string[] = [];

function makeTmpBase(): string {
  const dir = mkdtempSync(join(tmpdir(), "dashboard-cost-test-"));
  tmpDirs.push(dir);
  return dir;
}

// Creates <base>/<slug>/<sessionId>/ with a progress.json (created field) and
// an optional sibling retro.json (cost field) — mirrors the real
// ~/.claude/agentic-loop/<repo-key>/<slug>/<sessionId>/ tree collectLoops
// already walks.
function writeLoopDir(
  base: string,
  slug: string,
  sessionId: string,
  opts: { created?: string; cost?: Record<string, unknown>; noRetro?: boolean; progressCreated?: string }
): void {
  const dir = join(base, slug, sessionId);
  mkdirSync(dir, { recursive: true });
  writeFileSync(join(dir, "progress.json"), JSON.stringify({ created: opts.progressCreated ?? opts.created }));
  if (!opts.noRetro) {
    writeFileSync(
      join(dir, "retro.json"),
      JSON.stringify({ created: opts.created, cost: opts.cost ?? {} })
    );
  }
}

afterEach(() => {
  for (const dir of tmpDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("collectLoopCost", () => {
  it("sums frozen USD and tokens for loops created within the rolling 7-day window", () => {
    const now = new Date("2026-07-15T12:00:00Z");
    const base = makeTmpBase();
    writeLoopDir(base, "-proj", "sess-1", {
      created: "2026-07-14T10:00:00Z",
      cost: { total_usd_estimate: 1.5, total_tokens: 100_000, prices_as_of: "2026-07-01" },
    });
    writeLoopDir(base, "-proj", "sess-2", {
      created: "2026-07-10T10:00:00Z",
      cost: { total_usd_estimate: 2.25, total_tokens: 50_000, prices_as_of: "2026-07-01" },
    });
    // Outside the rolling 7-day window (8 days ago).
    writeLoopDir(base, "-proj", "sess-3", {
      created: "2026-07-07T10:00:00Z",
      cost: { total_usd_estimate: 100, total_tokens: 9_999_999, prices_as_of: "2026-07-01" },
    });

    const result = collectLoopCost(base, now);
    expect(result.week.usd).toBeCloseTo(3.75);
    expect(result.week.tokens).toBe(150_000);
  });

  it("sums frozen USD for loops created within the current calendar month, excluding last month even if within 30 days", () => {
    const now = new Date("2026-07-15T12:00:00Z");
    const base = makeTmpBase();
    writeLoopDir(base, "-proj", "sess-this-month", {
      created: "2026-07-02T10:00:00Z",
      cost: { total_usd_estimate: 4, total_tokens: 10_000, prices_as_of: "2026-07-01" },
    });
    // Last calendar month, but well within a rolling 30-day window — must be
    // excluded from "this month" since the boundary is calendar-month, not
    // 30 days.
    writeLoopDir(base, "-proj", "sess-last-month", {
      created: "2026-06-20T10:00:00Z",
      cost: { total_usd_estimate: 10, total_tokens: 20_000, prices_as_of: "2026-06-01" },
    });

    const result = collectLoopCost(base, now);
    expect(result.month.usd).toBeCloseTo(4);
    expect(result.month.tokens).toBe(10_000);
  });

  it("excludes a loop dir with no retro.json (incomplete loop) without crashing", () => {
    const now = new Date("2026-07-15T12:00:00Z");
    const base = makeTmpBase();
    writeLoopDir(base, "-proj", "sess-done", {
      created: "2026-07-14T10:00:00Z",
      cost: { total_usd_estimate: 1, total_tokens: 1_000, prices_as_of: "2026-07-01" },
    });
    writeLoopDir(base, "-proj", "sess-incomplete", { noRetro: true, progressCreated: "2026-07-14T10:00:00Z" });

    const result = collectLoopCost(base, now);
    expect(result.week.usd).toBeCloseTo(1);
    expect(result.week.tokens).toBe(1_000);
  });

  it("treats an empty cost object {} (fail-open) as contributing 0 without crashing", () => {
    const now = new Date("2026-07-15T12:00:00Z");
    const base = makeTmpBase();
    writeLoopDir(base, "-proj", "sess-empty-cost", { created: "2026-07-14T10:00:00Z", cost: {} });

    const result = collectLoopCost(base, now);
    expect(result.week.usd).toBe(0);
    expect(result.week.tokens).toBe(0);
    expect(result.month.usd).toBe(0);
  });

  it("returns null (no-data, not $0) for a missing base dir rather than throwing", () => {
    const now = new Date("2026-07-15T12:00:00Z");
    const result = collectLoopCost(join(tmpdir(), "does-not-exist-cost-base"), now);
    expect(result.week.usd).toBeNull();
    expect(result.week.tokens).toBeNull();
    expect(result.month.usd).toBeNull();
    expect(result.month.tokens).toBeNull();
  });

  it("returns null (no-data) for a window with zero completed loops, distinct from a real $0 spend", () => {
    const now = new Date("2026-07-15T12:00:00Z");
    const base = makeTmpBase();
    // Only a loop outside the week window — week bucket has zero contributing
    // loops and must read as null, not 0.
    writeLoopDir(base, "-proj", "sess-old", {
      created: "2026-06-01T10:00:00Z",
      cost: { total_usd_estimate: 1, total_tokens: 100, prices_as_of: "2026-06-01" },
    });

    const result = collectLoopCost(base, now);
    expect(result.week.usd).toBeNull();
    expect(result.week.tokens).toBeNull();
  });

  it("falls back to progress.json's created field when retro.json has no created timestamp", () => {
    const now = new Date("2026-07-15T12:00:00Z");
    const base = makeTmpBase();
    const dir = join(base, "-proj", "sess-fallback");
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "progress.json"), JSON.stringify({ created: "2026-07-14T10:00:00Z" }));
    writeFileSync(
      join(dir, "retro.json"),
      JSON.stringify({ cost: { total_usd_estimate: 5, total_tokens: 500, prices_as_of: "2026-07-01" } })
    );

    const result = collectLoopCost(base, now);
    expect(result.week.usd).toBeCloseTo(5);
  });

  it("derives a shared prices_as_of when every summed loop agrees, otherwise omits it", () => {
    const now = new Date("2026-07-15T12:00:00Z");
    const base = makeTmpBase();
    writeLoopDir(base, "-proj", "sess-a", {
      created: "2026-07-14T10:00:00Z",
      cost: { total_usd_estimate: 1, total_tokens: 100, prices_as_of: "2026-07-01" },
    });
    writeLoopDir(base, "-proj", "sess-b", {
      created: "2026-07-13T10:00:00Z",
      cost: { total_usd_estimate: 1, total_tokens: 100, prices_as_of: "2026-07-01" },
    });
    const agreeing = collectLoopCost(base, now);
    expect(agreeing.week.pricesAsOf).toBe("2026-07-01");

    const base2 = makeTmpBase();
    writeLoopDir(base2, "-proj", "sess-a", {
      created: "2026-07-14T10:00:00Z",
      cost: { total_usd_estimate: 1, total_tokens: 100, prices_as_of: "2026-07-01" },
    });
    writeLoopDir(base2, "-proj", "sess-b", {
      created: "2026-07-13T10:00:00Z",
      cost: { total_usd_estimate: 1, total_tokens: 100, prices_as_of: "2026-06-15" },
    });
    const disagreeing = collectLoopCost(base2, now);
    expect(disagreeing.week.pricesAsOf).toBeUndefined();
  });

  it("excludes dotdirs like .git from results", () => {
    const now = new Date("2026-07-15T12:00:00Z");
    const base = makeTmpBase();
    mkdirSync(join(base, ".git"), { recursive: true });
    writeLoopDir(base, "-proj", "sess-1", {
      created: "2026-07-14T10:00:00Z",
      cost: { total_usd_estimate: 1, total_tokens: 100, prices_as_of: "2026-07-01" },
    });

    const result = collectLoopCost(base, now);
    expect(result.week.usd).toBeCloseTo(1);
  });
});
