import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { collectLintFindings } from "../src/lib/collect/lint";

const tmpDirs: string[] = [];

function makeTmpVault(logContents: string | null): string {
  const dir = mkdtempSync(join(tmpdir(), "dashboard-lint-test-"));
  tmpDirs.push(dir);
  if (logContents !== null) {
    writeFileSync(join(dir, "log.md"), logContents);
  }
  return dir;
}

afterEach(() => {
  for (const dir of tmpDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("collectLintFindings", () => {
  it("returns null with an unavailable note when no vault path resolves", () => {
    const tile = collectLintFindings(["/nonexistent/vault/path/xyz"], new Date());
    expect(tile.key).toBe("lintFindings");
    expect(tile.value).toBeNull();
    expect(tile.note).toMatch(/unavailable/i);
  });

  it("returns null with an unavailable note when the vault dir exists but has no log.md", () => {
    const vault = makeTmpVault(null);
    const tile = collectLintFindings([vault], new Date());
    expect(tile.value).toBeNull();
    expect(tile.note).toMatch(/unavailable/i);
  });

  it("returns null with an unavailable note when no vault paths are given", () => {
    const tile = collectLintFindings([], new Date());
    expect(tile.value).toBeNull();
    expect(tile.note).toMatch(/unavailable/i);
  });

  it("surfaces recency in days since the most recent lint entry when only prose is present", () => {
    const vault = makeTmpVault("## [2026-07-22] lint | clean, no defects found\n");
    const tile = collectLintFindings([vault], new Date("2026-07-24T00:00:00Z"));
    expect(tile.value).not.toBeNull();
    expect(tile.value).toMatch(/2/);
  });

  it("does not scrape a findings count out of prose numbers", () => {
    const vault = makeTmpVault(
      "## [2026-07-22] lint | found 999 orphan links and 456 contradictions across 200 pages\n"
    );
    const tile = collectLintFindings([vault], new Date("2026-07-22T00:00:00Z"));
    const value = String(tile.value);
    expect(value).not.toMatch(/999|456|200/);
  });

  it("selects the newest entry by date, not by file position", () => {
    const vault = makeTmpVault(
      "## [2026-07-22] lint | newest but appears FIRST\n\n## [2020-01-01] lint | oldest but appears LAST\n"
    );
    const tile = collectLintFindings([vault], new Date("2026-07-23T00:00:00Z"));
    // Recency from the real newest date (2026-07-22 -> 1 day), not the
    // out-of-order last line (2020-01-01 -> ~6 years).
    expect(String(tile.value)).toMatch(/1/);
    expect(String(tile.value)).not.toMatch(/year/i);
  });

  it("prefers a structured findings-count record when present over the date fallback", () => {
    const vault = makeTmpVault(
      "## [2026-07-22] lint | clean\n<!-- lint-findings: 3 -->\n"
    );
    const tile = collectLintFindings([vault], new Date("2026-07-22T00:00:00Z"));
    expect(tile.value).toBe("3");
  });

  it("falls back to date-based recency when no structured record is present", () => {
    const vault = makeTmpVault("## [2026-07-22] lint | prose only, no structure\n");
    const tile = collectLintFindings([vault], new Date("2026-07-22T00:00:00Z"));
    expect(tile.value).not.toBeNull();
  });

  it("never renders a negative day count for a lint entry dated in the future", () => {
    // A future-dated heading (clock skew, hand-edited log, timezone edge) must
    // not surface as e.g. "-3d since last lint" — that reads as nonsense to
    // anyone looking at the tile.
    const vault = makeTmpVault("## [2026-07-25] lint | prose only, no structure\n");
    const tile = collectLintFindings([vault], new Date("2026-07-22T00:00:00Z"));
    expect(String(tile.value)).not.toMatch(/-\d/);
  });

  it("prefers the MOST RECENT run's structured record, not the first one appended to the file", () => {
    // wiki-lint's Step 5 appends — so across multiple runs, the newest
    // structured record is the LAST one in the file, not the first. A
    // first-match regex would silently keep reporting an old count forever.
    const vault = makeTmpVault(
      "## [2026-07-10] lint | old run\n<!-- lint-findings: 7 -->\n\n" +
        "## [2026-07-22] lint | latest run\n<!-- lint-findings: 2 -->\n"
    );
    const tile = collectLintFindings([vault], new Date("2026-07-22T00:00:00Z"));
    expect(tile.value).toBe("2");
  });

  it("on a same-date tie, surfaces the record from a LATER same-date entry, not the first", () => {
    // Multiple lint runs on the same day are normal, not an edge case (the
    // real vault log has four same-date headings on 2026-07-22). A strict
    // ">" comparison keeps the FIRST entry encountered on a date tie and
    // never advances to a later same-date entry, so a structured record
    // written by the 2nd/3rd/4th run of the day was silently never surfaced.
    const vault = makeTmpVault(
      "## [2026-07-22] lint | first run of the day, no record\n\n" +
        "## [2026-07-22] lint | second run of the day, has a record\n<!-- lint-findings: 1 -->\n"
    );
    const tile = collectLintFindings([vault], new Date("2026-07-22T00:00:00Z"));
    expect(tile.value).toBe("1");
  });

  it("on a same-date tie, a later entry WITHOUT a record wins over an earlier one WITH a record", () => {
    // wiki-lint's Step 5 makes the structured record mandatory on every run
    // (even "0" on a clean pass) — so a same-date entry legitimately missing
    // one is not "the count is just elsewhere", it's the newest run's own
    // state. Shadowing it with an older sibling's stale count would be
    // dishonest: strictly the last same-date entry wins, record or not.
    const vault = makeTmpVault(
      "## [2026-07-22] lint | first run of the day, has a record\n<!-- lint-findings: 5 -->\n\n" +
        "## [2026-07-22] lint | second run of the day, no record\n"
    );
    const tile = collectLintFindings([vault], new Date("2026-07-22T00:00:00Z"));
    expect(tile.value).not.toBe("5");
    expect(String(tile.value)).toMatch(/since last lint/);
  });
});
