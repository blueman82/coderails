import { makeTmpBase } from "./sessions.fixture";
import { describe, it, expect } from "vitest";
import { mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { collectLoops } from "../src/lib/collect/sessions";

describe("collectLoops", () => {

  it("reports evalsFrozen false for a justified NO-GO verdict", () => {
    const base = makeTmpBase();
    const dir = join(base, "-nogo-project", "S6");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({ schema_version: 3, status: "complete", session_id: "S6", completed_marker: 1, work_units: { wu1: { status: "done" } } })
    );
    writeFileSync(
      join(dir, "evals.json"),
      JSON.stringify({ scope: "loop", result: "NO-GO", verification_level: 1, verification_justification: "2 work-units, no irreversible surface" })
    );
    const loops = collectLoops(base);
    expect(loops[0].evalsFrozen).toBe(false);
  });

  it("reports evalsFrozen false when evals.json is GO but verification_justification is blank (unjustified)", () => {
    const base = makeTmpBase();
    const dir = join(base, "-unjustified-project", "S7");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({ schema_version: 3, status: "complete", session_id: "S7", completed_marker: 1, work_units: { wu1: { status: "done" } } })
    );
    writeFileSync(
      join(dir, "evals.json"),
      JSON.stringify({ scope: "loop", result: "GO", verification_level: 1, verification_justification: "" })
    );
    const loops = collectLoops(base);
    expect(loops[0].evalsFrozen).toBe(false);
  });

  it("reports evalsFrozen false for an otherwise-valid GO verdict missing the grading stamp (mirrors the hook's UNSTAMPED check)", () => {
    const base = makeTmpBase();
    const dir = join(base, "-unstamped-project", "S7b");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({ schema_version: 3, status: "complete", session_id: "S7b", completed_marker: 1, work_units: { unit1: { status: "done" } } })
    );
    writeFileSync(
      join(dir, "evals.json"),
      JSON.stringify({ scope: "loop", result: "GO", verification_level: 1, verification_justification: "2 work-units, no irreversible surface" })
    );
    const loops = collectLoops(base);
    expect(loops[0].evalsFrozen).toBe(false);
  });

  it("reports evalsFrozen false for a GO verdict whose grading stamp has a checksum but no by field (partial stamp)", () => {
    const base = makeTmpBase();
    const dir = join(base, "-partialstamp-noby-project", "S7c");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({ schema_version: 3, status: "complete", session_id: "S7c", completed_marker: 1, work_units: { unit1: { status: "done" } } })
    );
    writeFileSync(
      join(dir, "evals.json"),
      JSON.stringify({
        scope: "loop",
        result: "GO",
        verification_level: 1,
        verification_justification: "2 work-units, no irreversible surface",
        grading: { checksum: "abc123" },
      })
    );
    const loops = collectLoops(base);
    expect(loops[0].evalsFrozen).toBe(false);
  });

  it("reports evalsFrozen false for a GO verdict whose grading stamp has empty-string by and checksum", () => {
    const base = makeTmpBase();
    const dir = join(base, "-partialstamp-empty-project", "S7d");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({ schema_version: 3, status: "complete", session_id: "S7d", completed_marker: 1, work_units: { unit1: { status: "done" } } })
    );
    writeFileSync(
      join(dir, "evals.json"),
      JSON.stringify({
        scope: "loop",
        result: "GO",
        verification_level: 1,
        verification_justification: "2 work-units, no irreversible surface",
        grading: { by: "", checksum: "" },
      })
    );
    const loops = collectLoops(base);
    expect(loops[0].evalsFrozen).toBe(false);
  });

  it("ignores a sibling evals.json with the wrong scope (pr, not loop)", () => {
    const base = makeTmpBase();
    const dir = join(base, "-wrongscope-project", "S8");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({ schema_version: 3, status: "complete", session_id: "S8", completed_marker: 1, work_units: { wu1: { status: "done" } } })
    );
    writeFileSync(join(dir, "evals.json"), JSON.stringify({ scope: "pr", result: "GO" }));
    const loops = collectLoops(base);
    expect(loops[0].evalsFrozen).toBe(false);
  });

  it("returns an empty array for a missing base dir rather than throwing", () => {
    const loops = collectLoops(join(tmpdir(), "does-not-exist-loops-base"));
    expect(loops).toEqual([]);
  });

  it("excludes dotdirs like .git and .DS_Store from results", () => {
    const base = makeTmpBase();
    for (const slug of [".git", ".DS_Store"]) {
      const dir = join(base, slug, "S1");
      mkdirSync(dir, { recursive: true });
      writeFileSync(
        join(dir, "progress.json"),
        JSON.stringify({ schema_version: 3, status: "complete", session_id: "S1", work_units: {} })
      );
    }
    const loops = collectLoops(base);
    expect(loops).toEqual([]);
  });

  it("surfaces the last 5 decisions_absorbed entries, newest first, formatted as phase: decision", () => {
    const base = makeTmpBase();
    const dir = join(base, "-decisions-project", "S20");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({
        schema_version: 3,
        status: "in-progress",
        session_id: "S20",
        work_units: {},
        decisions_absorbed: [
          { phase: "2.5", decision: "one" },
          { phase: "2.6", decision: "two" },
          { phase: "5", decision: "three" },
          { phase: "6", decision: "four" },
          { phase: "13", decision: "five" },
          { phase: "13", decision: "six" },
          { phase: "13", decision: "seven" },
        ],
      })
    );
    const loops = collectLoops(base);
    expect(loops[0].decisions).toEqual([
      "13: seven",
      "13: six",
      "13: five",
      "6: four",
      "5: three",
    ]);
  });

  it("reports an empty decisions array when decisions_absorbed is absent (predates the field)", () => {
    const base = makeTmpBase();
    const dir = join(base, "-nodecisions-project", "S21");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({ schema_version: 3, status: "in-progress", session_id: "S21", work_units: {} })
    );
    const loops = collectLoops(base);
    expect(loops[0].decisions).toEqual([]);
  });

  it("tolerates a malformed decisions_absorbed (non-array, or entries missing keys) by skipping rather than throwing", () => {
    const base = makeTmpBase();
    const dirA = join(base, "-decisions-notarray-project", "S22");
    mkdirSync(dirA, { recursive: true });
    writeFileSync(
      join(dirA, "progress.json"),
      JSON.stringify({ schema_version: 3, status: "in-progress", session_id: "S22", work_units: {}, decisions_absorbed: "not-an-array" })
    );

    const dirB = join(base, "-decisions-badentries-project", "S23");
    mkdirSync(dirB, { recursive: true });
    writeFileSync(
      join(dirB, "progress.json"),
      JSON.stringify({
        schema_version: 3,
        status: "in-progress",
        session_id: "S23",
        work_units: {},
        decisions_absorbed: [{ phase: "2.5" }, { decision: "orphan" }, "not-a-record", { phase: "6", decision: "kept" }],
      })
    );

    const loops = collectLoops(base);
    expect(loops.find((l) => l.slug === "-decisions-notarray-project")?.decisions).toEqual([]);
    expect(loops.find((l) => l.slug === "-decisions-badentries-project")?.decisions).toEqual(["6: kept"]);
  });
});
