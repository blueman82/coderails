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
});
