import { LOOP_FIXTURES, makeTmpBase } from "./sessions.fixture";
import { describe, it, expect } from "vitest";
import { mkdirSync, writeFileSync, utimesSync } from "node:fs";
import { join } from "node:path";
import { collectLoops } from "../src/lib/collect/sessions";

describe("collectLoops", () => {

  it("parses work_units (object form) and a passing sibling evals.json into a frozen, done-counted loop", () => {
    const loops = collectLoops(LOOP_FIXTURES);
    const loop = loops.find((l) => l.slug === "-work-project");
    expect(loop).toEqual({
      slug: "-work-project",
      title: "-work-project",
      sessionId: "S1",
      status: "complete",
      workUnitsDone: 2,
      workUnitsTotal: 3,
      evalsFrozen: true,
      lastUpdatedMs: expect.any(Number),
      units: [
        { key: "wu1", status: "done" },
        { key: "wu2", status: "done" },
        { key: "wu3", status: "in-flight" },
      ],
      decisions: [],
    });
  });

  it("parses array-form work_units and reports evalsFrozen false with no sibling evals.json", () => {
    const loops = collectLoops(LOOP_FIXTURES);
    const loop = loops.find((l) => l.slug === "-work-project-legacy");
    expect(loop).toEqual({
      slug: "-work-project-legacy",
      title: "-work-project-legacy",
      sessionId: "S2",
      status: "complete",
      workUnitsDone: 2,
      workUnitsTotal: 3,
      evalsFrozen: false,
      lastUpdatedMs: expect.any(Number),
      units: [
        { key: "backup", status: "done" },
        { key: "rewrite", status: "done" },
        { key: "force-push", status: "in-flight" },
      ],
      decisions: [],
    });
  });

  it("ignores malformed progress.json without inventing a visible current loop", () => {
    const loops = collectLoops(LOOP_FIXTURES);
    const loop = loops.find((l) => l.slug === "-work-project-malformed");
    expect(loop).toBeUndefined();
  });

  it("reports zero units for a current progress.json with no work_units key at all", () => {
    const loops = collectLoops(LOOP_FIXTURES);
    const loop = loops.find((l) => l.slug === "-work-project-nounits");
    expect(loop).toMatchObject({
      slug: "-work-project-nounits",
      sessionId: "S4",
      status: "complete",
      workUnitsDone: 0,
      workUnitsTotal: 0,
      evalsFrozen: false,
      units: [],
    });
  });

  it("uses progress.json's loop field as the human-readable title when present", () => {
    const base = makeTmpBase();
    const dir = join(base, "-named-project", "S9");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({
        schema_version: 3,
        status: "in-progress",
        session_id: "S9",
        loop: "observability-dashboard (sub-project 1 of agentic-os evolution)",
        work_units: {},
      })
    );
    const loops = collectLoops(base);
    expect(loops[0].title).toBe("observability-dashboard (sub-project 1 of agentic-os evolution)");
  });

  it("falls back to the slug for title when progress.json has no loop field and no authorising_prompt_raw", () => {
    const base = makeTmpBase();
    const dir = join(base, "-unnamed-project", "S10");
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "progress.json"), JSON.stringify({ schema_version: 3, status: "in-progress", session_id: "S10", work_units: {} }));
    const loops = collectLoops(base);
    expect(loops[0].title).toBe("-unnamed-project");
  });

  it("falls back to the slug for title when progress.json's loop field is blank", () => {
    const base = makeTmpBase();
    const dir = join(base, "-blank-loop-project", "S11");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({ schema_version: 3, status: "in-progress", session_id: "S11", loop: "   ", work_units: {} })
    );
    const loops = collectLoops(base);
    expect(loops[0].title).toBe("-blank-loop-project");
  });

  it("falls back to the slug for title when progress.json's loop field is not a string", () => {
    const base = makeTmpBase();
    const dir = join(base, "-nonstring-loop-project", "S12");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({ schema_version: 3, status: "in-progress", session_id: "S12", loop: 42, work_units: {} })
    );
    const loops = collectLoops(base);
    expect(loops[0].title).toBe("-nonstring-loop-project");
  });

  it("falls back to authorising_prompt_raw's full verbatim text (no truncation) for title when loop is null", () => {
    const loops = collectLoops(LOOP_FIXTURES);
    const loop = loops.find((l) => l.slug === "-work-project-authprompt");
    expect(loop?.title).toBe(
      "Read memory file `project_loop_hardening_handoff.md` for full context. Two systemic hardening findings from the observability-dashboard build that need addressing before the next release ships to users."
    );
  });

  it("uses authorising_prompt_raw verbatim when it is 80 chars or shorter", () => {
    const base = makeTmpBase();
    const dir = join(base, "-short-prompt-project", "S13");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({
        schema_version: 3,
        status: "in-progress",
        session_id: "S13",
        loop: null,
        authorising_prompt_raw: "  Fix the flaky test.  ",
        work_units: {},
      })
    );
    const loops = collectLoops(base);
    expect(loops[0].title).toBe("Fix the flaky test.");
  });

  it("uses the loop field over authorising_prompt_raw when both are non-blank (precedence)", () => {
    const base = makeTmpBase();
    const dir = join(base, "-both-title-project", "S18");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({
        schema_version: 3,
        status: "in-progress",
        session_id: "S18",
        loop: "loop wins",
        authorising_prompt_raw: "authorising_prompt_raw loses",
        work_units: {},
      })
    );
    const loops = collectLoops(base);
    expect(loops[0].title).toBe("loop wins");
  });

  it("parses keyed units carrying description, desc-alias, and pr (fixture (a): description+pr)", () => {
    const loops = collectLoops(LOOP_FIXTURES);
    const loop = loops.find((l) => l.slug === "-work-project-described");
    expect(loop?.units).toEqual([
      { key: "wu1-done", status: "done", description: "F1: first unit, done and described.", pr: 17 },
      { key: "wu2-inprogress", status: "in-flight", description: "F2: second unit, in flight.", pr: 18 },
      { key: "wu3-doing", status: "in-flight", description: "F3: third unit, uses the desc alias and the doing status." },
      { key: "wu4-pending", status: "pending" },
    ]);
  });

  it("omits description when both description and desc are absent or blank, and omits pr when not a number", () => {
    const base = makeTmpBase();
    const dir = join(base, "-blank-desc-project", "S14");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({
        schema_version: 3,
        status: "in-progress",
        session_id: "S14",
        work_units: {
          "wu-blank": { status: "pending", description: "   ", pr: "17" },
          "wu-none": { status: "pending" },
        },
      })
    );
    const loops = collectLoops(base);
    expect(loops[0].units).toEqual([
      { key: "wu-blank", status: "pending" },
      { key: "wu-none", status: "pending" },
    ]);
  });

  it("falls through to the desc alias when description is present but blank", () => {
    const base = makeTmpBase();
    const dir = join(base, "-blank-description-desc-fallthrough-project", "S19");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({
        schema_version: 3,
        status: "in-progress",
        session_id: "S19",
        work_units: {
          "wu-fallthrough": { status: "pending", description: "   ", desc: "desc used" },
        },
      })
    );
    const loops = collectLoops(base);
    expect(loops[0].units).toEqual([{ key: "wu-fallthrough", status: "pending", description: "desc used" }]);
  });

  it("uses description over the desc alias when both are non-blank (precedence)", () => {
    const base = makeTmpBase();
    const dir = join(base, "-both-desc-project", "S17");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({
        schema_version: 3,
        status: "in-progress",
        session_id: "S17",
        work_units: {
          "wu-both": { status: "pending", description: "description wins", desc: "desc loses" },
        },
      })
    );
    const loops = collectLoops(base);
    expect(loops[0].units).toEqual([{ key: "wu-both", status: "pending", description: "description wins" }]);
  });

  it("uses last_updated when it parses as a valid date (precedence over mtime)", () => {
    const loops = collectLoops(LOOP_FIXTURES);
    const loop = loops.find((l) => l.slug === "-work-project-described");
    expect(loop?.lastUpdatedMs).toBe(Date.parse("2026-07-13T12:00:00Z"));
  });

  it("falls back to progress.json's mtime when last_updated is invalid (fixture (e): last_updated invalid -> mtime fallback)", () => {
    const base = makeTmpBase();
    const dir = join(base, "-invalid-lastupdated-project", "S15");
    mkdirSync(dir, { recursive: true });
    const file = join(dir, "progress.json");
    writeFileSync(
      file,
      JSON.stringify({
        schema_version: 3,
        status: "in-progress",
        session_id: "S15",
        last_updated: "not-a-date",
        work_units: {},
      })
    );
    const mtime = new Date("2026-07-01T00:00:00Z");
    utimesSync(file, mtime, mtime);
    const loops = collectLoops(base);
    expect(loops[0].lastUpdatedMs).toBe(mtime.getTime());
  });

  it("falls back to progress.json's mtime when last_updated is absent entirely", () => {
    const base = makeTmpBase();
    const dir = join(base, "-no-lastupdated-project", "S16");
    mkdirSync(dir, { recursive: true });
    const file = join(dir, "progress.json");
    writeFileSync(file, JSON.stringify({ schema_version: 3, status: "in-progress", session_id: "S16", work_units: {} }));
    const mtime = new Date("2026-07-02T00:00:00Z");
    utimesSync(file, mtime, mtime);
    const loops = collectLoops(base);
    expect(loops[0].lastUpdatedMs).toBe(mtime.getTime());
  });

  it("reports evalsFrozen true for a verification_level-0 exemption verdict with a grading stamp", () => {
    const base = makeTmpBase();
    const dir = join(base, "-verification_level0-project", "S5");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({ schema_version: 3, status: "complete", session_id: "S5", completed_marker: 1, work_units: { wu1: { status: "done" } } })
    );
    writeFileSync(
      join(dir, "evals.json"),
      JSON.stringify({
        scope: "loop",
        verification_level: 0,
        verification_justification: "docs-only loop, no runtime behaviour",
        grading: { by: "post_evals.py grade-loop", checksum: "abc123" },
      })
    );
    const loops = collectLoops(base);
    expect(loops[0].evalsFrozen).toBe(true);
  });

  it("reports evalsFrozen false for a verification_level-0 exemption whose result is explicitly NO-GO (NO-GO takes precedence over the verification_level-0 exemption)", () => {
    const base = makeTmpBase();
    const dir = join(base, "-verification_level0-nogo-project", "S5b");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({ schema_version: 3, status: "complete", session_id: "S5b", completed_marker: 1, work_units: { unit1: { status: "done" } } })
    );
    writeFileSync(
      join(dir, "evals.json"),
      JSON.stringify({
        scope: "loop",
        result: "NO-GO",
        verification_level: 0,
        verification_justification: "docs-only loop, no runtime behaviour",
        grading: { by: "post_evals.py grade-loop", checksum: "abc123" },
      })
    );
    const loops = collectLoops(base);
    expect(loops[0].evalsFrozen).toBe(false);
  });
});
