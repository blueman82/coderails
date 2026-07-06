import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { collectHealth } from "../src/lib/collect/health";

const tmpDirs: string[] = [];

function makeTmpDisciplineLog(lines: string[]): string {
  const dir = mkdtempSync(join(tmpdir(), "dashboard-health-test-"));
  tmpDirs.push(dir);
  const path = join(dir, "discipline.log");
  writeFileSync(path, lines.join("\n") + (lines.length ? "\n" : ""));
  return path;
}

afterEach(() => {
  for (const dir of tmpDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("collectHealth", () => {
  it("always returns exactly the four documented tile keys", () => {
    const tiles = collectHealth({ disciplineLogPath: join(tmpdir(), "does-not-exist.log") });
    expect(tiles.map((t) => t.key).sort()).toEqual(
      ["hooksFired", "lintFindings", "usage5h", "usageWeek"].sort()
    );
  });

  it("reports usage5h as permanently unavailable (no reliable local source)", () => {
    const tiles = collectHealth({ disciplineLogPath: join(tmpdir(), "does-not-exist.log") });
    const tile = tiles.find((t) => t.key === "usage5h");
    expect(tile?.value).toBeNull();
    expect(tile?.note).toMatch(/^unavailable: /);
  });

  it("reports usageWeek as permanently unavailable (no reliable local source)", () => {
    const tiles = collectHealth({ disciplineLogPath: join(tmpdir(), "does-not-exist.log") });
    const tile = tiles.find((t) => t.key === "usageWeek");
    expect(tile?.value).toBeNull();
    expect(tile?.note).toMatch(/^unavailable: /);
  });

  it("reports lintFindings as permanently unavailable (no persisted wiki-lint report file)", () => {
    const tiles = collectHealth({ disciplineLogPath: join(tmpdir(), "does-not-exist.log") });
    const tile = tiles.find((t) => t.key === "lintFindings");
    expect(tile?.value).toBeNull();
    expect(tile?.note).toMatch(/^unavailable: /);
  });

  it("reports hooksFired as unavailable with a reason when the discipline log is unreadable", () => {
    const tiles = collectHealth({ disciplineLogPath: join(tmpdir(), "does-not-exist.log") });
    const tile = tiles.find((t) => t.key === "hooksFired");
    expect(tile?.value).toBeNull();
    expect(tile?.note).toMatch(/^unavailable: /);
  });

  it("counts hook invocation lines from a real discipline log", () => {
    const path = makeTmpDisciplineLog([
      "2026-07-06T15:19:45+01:00 hook=loop_stall_guard session=abc invocations=0 active=0 blocked=0",
      "2026-07-06T15:19:45+01:00 hook=confidence_labels session=abc text_len=405 attempts=0 matched=1 would_block=0",
      "2026-07-06T15:19:56+01:00 hook=verify_loop session=abc text_len=151 attempts=0 files=4 dnv_items=0 resolvable_dnv_items=0 blocked=0",
    ]);
    const tiles = collectHealth({ disciplineLogPath: path });
    const tile = tiles.find((t) => t.key === "hooksFired");
    expect(tile?.value).toBe("3");
    expect(tile?.note).toBeUndefined();
  });

  it("counts zero for an empty discipline log without throwing", () => {
    const path = makeTmpDisciplineLog([]);
    const tiles = collectHealth({ disciplineLogPath: path });
    const tile = tiles.find((t) => t.key === "hooksFired");
    expect(tile?.value).toBe("0");
  });

  it("ignores blank lines when counting hook invocations", () => {
    const path = makeTmpDisciplineLog([
      "2026-07-06T15:19:45+01:00 hook=loop_stall_guard session=abc invocations=0 active=0 blocked=0",
      "",
      "2026-07-06T15:19:56+01:00 hook=verify_loop session=abc text_len=151 attempts=0 files=4 dnv_items=0 resolvable_dnv_items=0 blocked=0",
    ]);
    const tiles = collectHealth({ disciplineLogPath: path });
    const tile = tiles.find((t) => t.key === "hooksFired");
    expect(tile?.value).toBe("2");
  });

  it("never throws even when called with no options (uses real default paths)", () => {
    expect(() => collectHealth()).not.toThrow();
  });

  describe("hooksFired scoped to today", () => {
    const TODAY = new Date("2026-07-06T18:00:00+01:00");

    it("counts only lines stamped today, excluding older-day lines and a non-timestamp line", () => {
      const path = makeTmpDisciplineLog([
        "2026-07-06T09:00:00+01:00 hook=confidence_labels session=abc matched=1 would_block=0",
        "2026-07-05T23:59:59+01:00 hook=verify_loop session=abc blocked=0",
        "2026-07-01T12:00:00+01:00 hook=loop_stall_guard session=abc blocked=0",
        "not-a-timestamp hook=weird session=abc blocked=0",
        "2026-07-06T17:30:00+01:00 hook=loop_state_guard session=abc blocked=0",
      ]);
      const tiles = collectHealth({ disciplineLogPath: path, now: TODAY });
      const tile = tiles.find((t) => t.key === "hooksFired");
      expect(tile?.value).toBe("2");
      expect(tile?.note).toBeUndefined();
    });

    it("counts a line stamped 00:00:00 today", () => {
      const path = makeTmpDisciplineLog([
        "2026-07-06T00:00:00+01:00 hook=confidence_labels session=abc blocked=0",
      ]);
      const tiles = collectHealth({ disciplineLogPath: path, now: TODAY });
      const tile = tiles.find((t) => t.key === "hooksFired");
      expect(tile?.value).toBe("1");
    });

    it("excludes a line stamped 23:59:59 yesterday", () => {
      const path = makeTmpDisciplineLog([
        "2026-07-05T23:59:59+01:00 hook=confidence_labels session=abc blocked=0",
      ]);
      const tiles = collectHealth({ disciplineLogPath: path, now: TODAY });
      const tile = tiles.find((t) => t.key === "hooksFired");
      expect(tile?.value).toBe("0");
    });

    it("excludes lines whose leading token does not parse as a timestamp (fail-honest, does not guess their day)", () => {
      const path = makeTmpDisciplineLog(["garbage line with no timestamp at all"]);
      const tiles = collectHealth({ disciplineLogPath: path, now: TODAY });
      const tile = tiles.find((t) => t.key === "hooksFired");
      expect(tile?.value).toBe("0");
    });
  });
});
