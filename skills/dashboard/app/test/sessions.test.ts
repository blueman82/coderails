import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync, utimesSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { collectSessions, collectLoops } from "../src/lib/collect/sessions";

const LOOP_FIXTURES = join(__dirname, "fixtures/projects/loops");

const tmpDirs: string[] = [];

function makeTmpBase(): string {
  const dir = mkdtempSync(join(tmpdir(), "dashboard-sessions-test-"));
  tmpDirs.push(dir);
  return dir;
}

// Creates <base>/<slug>/<file> with its mtime set to `now - ageMs`.
function writeSessionFile(base: string, slug: string, ageMs: number, now: number): void {
  const dir = join(base, slug);
  mkdirSync(dir, { recursive: true });
  const file = join(dir, "session.jsonl");
  writeFileSync(file, "{}\n");
  const mtime = new Date(now - ageMs);
  utimesSync(file, mtime, mtime);
}

afterEach(() => {
  for (const dir of tmpDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("collectSessions", () => {
  const NOW = Date.parse("2026-07-06T12:00:00Z");

  it("classifies a project touched moments ago as active", () => {
    const base = makeTmpBase();
    writeSessionFile(base, "-fresh-project", 0, NOW);
    const sessions = collectSessions(base, NOW);
    expect(sessions).toEqual([{ project: "-fresh-project", lastActivity: NOW, state: "active" }]);
  });

  it("treats 4m59s old as still active (boundary just under 5m)", () => {
    const base = makeTmpBase();
    const ageMs = 4 * 60_000 + 59_000;
    writeSessionFile(base, "-boundary-active", ageMs, NOW);
    const sessions = collectSessions(base, NOW);
    expect(sessions[0].state).toBe("active");
  });

  it("treats exactly 5m old as idle (boundary at 5m)", () => {
    const base = makeTmpBase();
    const ageMs = 5 * 60_000;
    writeSessionFile(base, "-boundary-idle", ageMs, NOW);
    const sessions = collectSessions(base, NOW);
    expect(sessions[0].state).toBe("idle");
  });

  it("treats just-under-60m old as idle", () => {
    const base = makeTmpBase();
    const ageMs = 60 * 60_000 - 1000;
    writeSessionFile(base, "-idle-project", ageMs, NOW);
    const sessions = collectSessions(base, NOW);
    expect(sessions[0].state).toBe("idle");
  });

  it("treats exactly 60m old as stalled (boundary at 60m)", () => {
    const base = makeTmpBase();
    const ageMs = 60 * 60_000;
    writeSessionFile(base, "-boundary-stalled", ageMs, NOW);
    const sessions = collectSessions(base, NOW);
    expect(sessions[0].state).toBe("stalled");
  });

  it("treats a project untouched for hours as stalled", () => {
    const base = makeTmpBase();
    writeSessionFile(base, "-stalled-project", 3 * 60 * 60_000, NOW);
    const sessions = collectSessions(base, NOW);
    expect(sessions[0].state).toBe("stalled");
  });

  it("returns an empty array for a missing base dir rather than throwing", () => {
    const sessions = collectSessions(join(tmpdir(), "does-not-exist-sessions-base"), NOW);
    expect(sessions).toEqual([]);
  });

  it("collects multiple projects independently", () => {
    const base = makeTmpBase();
    writeSessionFile(base, "-fresh-project", 0, NOW);
    writeSessionFile(base, "-stalled-project", 3 * 60 * 60_000, NOW);
    const sessions = collectSessions(base, NOW);
    const byProject = Object.fromEntries(sessions.map((s) => [s.project, s.state]));
    expect(byProject).toEqual({ "-fresh-project": "active", "-stalled-project": "stalled" });
  });

  it("excludes dotdirs like .git and .DS_Store from results", () => {
    const base = makeTmpBase();
    writeSessionFile(base, "-fresh-project", 0, NOW);
    writeSessionFile(base, ".git", 0, NOW);
    writeSessionFile(base, ".DS_Store", 0, NOW);
    const sessions = collectSessions(base, NOW);
    expect(sessions.map((s) => s.project)).toEqual(["-fresh-project"]);
  });
});

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

  it("parses legacy array-form work_units and reports evalsFrozen false with no sibling evals.json", () => {
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
        { key: "backup", done: true, inFlight: false },
        { key: "rewrite", done: true, inFlight: false },
        { key: "force-push", done: false, inFlight: true },
      ],
      decisions: [],
    });
  });

  it("degrades a malformed progress.json to a visible entry with zero units and evalsFrozen false, never throws", () => {
    const loops = collectLoops(LOOP_FIXTURES);
    const loop = loops.find((l) => l.slug === "-work-project-malformed");
    expect(loop).toBeDefined();
    expect(loop).toMatchObject({
      slug: "-work-project-malformed",
      workUnitsDone: 0,
      workUnitsTotal: 0,
      evalsFrozen: false,
      units: [],
    });
  });

  it("fails open to zero units for a legacy progress.json with no work_units key at all", () => {
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
    writeFileSync(join(dir, "progress.json"), JSON.stringify({ status: "in-progress", session_id: "S10", work_units: {} }));
    const loops = collectLoops(base);
    expect(loops[0].title).toBe("-unnamed-project");
  });

  it("falls back to the slug for title when progress.json's loop field is blank", () => {
    const base = makeTmpBase();
    const dir = join(base, "-blank-loop-project", "S11");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({ status: "in-progress", session_id: "S11", loop: "   ", work_units: {} })
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
      JSON.stringify({ status: "in-progress", session_id: "S12", loop: 42, work_units: {} })
    );
    const loops = collectLoops(base);
    expect(loops[0].title).toBe("-nonstring-loop-project");
  });

  it("falls back to authorising_prompt_raw's first 80 chars (trimmed, ellipsis) for title when loop is null", () => {
    const loops = collectLoops(LOOP_FIXTURES);
    const loop = loops.find((l) => l.slug === "-work-project-authprompt");
    expect(loop?.title).toBe(
      "Read memory file `project_loop_hardening_handoff.md` for full context. Two syste…"
    );
  });

  it("uses authorising_prompt_raw verbatim (no ellipsis) when it is 80 chars or shorter", () => {
    const base = makeTmpBase();
    const dir = join(base, "-short-prompt-project", "S13");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({
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

  it("parses keyed units carrying description, desc-alias, and pr (fixture (a): description+pr)", () => {
    const loops = collectLoops(LOOP_FIXTURES);
    const loop = loops.find((l) => l.slug === "-work-project-described");
    expect(loop?.units).toEqual([
      { key: "wu1-done", done: true, inFlight: false, description: "F1: first unit, done and described.", pr: 17 },
      { key: "wu2-inprogress", done: false, inFlight: true, description: "F2: second unit, in flight.", pr: 18 },
      { key: "wu3-doing", done: false, inFlight: true, description: "F3: third unit, uses the desc alias and the doing status." },
      { key: "wu4-pending", done: false, inFlight: false },
    ]);
  });

  it("omits description when both description and desc are absent or blank, and omits pr when not a number", () => {
    const base = makeTmpBase();
    const dir = join(base, "-blank-desc-project", "S14");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({
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
      { key: "wu-blank", done: false, inFlight: false },
      { key: "wu-none", done: false, inFlight: false },
    ]);
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
    writeFileSync(file, JSON.stringify({ status: "in-progress", session_id: "S16", work_units: {} }));
    const mtime = new Date("2026-07-02T00:00:00Z");
    utimesSync(file, mtime, mtime);
    const loops = collectLoops(base);
    expect(loops[0].lastUpdatedMs).toBe(mtime.getTime());
  });

  it("reports evalsFrozen true for a tier-0 exemption verdict with a grading stamp", () => {
    const base = makeTmpBase();
    const dir = join(base, "-tier0-project", "S5");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({ status: "complete", session_id: "S5", completed_marker: 1, work_units: { wu1: { status: "done" } } })
    );
    writeFileSync(
      join(dir, "evals.json"),
      JSON.stringify({
        scope: "loop",
        tier: 0,
        tier_justification: "docs-only loop, no runtime behaviour",
        grading: { by: "post_evals.sh grade-loop", checksum: "abc123" },
      })
    );
    const loops = collectLoops(base);
    expect(loops[0].evalsFrozen).toBe(true);
  });

  it("reports evalsFrozen false for a tier-0 exemption whose result is explicitly NO-GO (NO-GO takes precedence over the tier-0 exemption)", () => {
    const base = makeTmpBase();
    const dir = join(base, "-tier0-nogo-project", "S5b");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({ status: "complete", session_id: "S5b", completed_marker: 1, work_units: { unit1: { status: "done" } } })
    );
    writeFileSync(
      join(dir, "evals.json"),
      JSON.stringify({
        scope: "loop",
        result: "NO-GO",
        tier: 0,
        tier_justification: "docs-only loop, no runtime behaviour",
        grading: { by: "post_evals.sh grade-loop", checksum: "abc123" },
      })
    );
    const loops = collectLoops(base);
    expect(loops[0].evalsFrozen).toBe(false);
  });

  it("reports evalsFrozen false for a justified NO-GO verdict", () => {
    const base = makeTmpBase();
    const dir = join(base, "-nogo-project", "S6");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({ status: "complete", session_id: "S6", completed_marker: 1, work_units: { wu1: { status: "done" } } })
    );
    writeFileSync(
      join(dir, "evals.json"),
      JSON.stringify({ scope: "loop", result: "NO-GO", tier: 1, tier_justification: "2 work-units, no irreversible surface" })
    );
    const loops = collectLoops(base);
    expect(loops[0].evalsFrozen).toBe(false);
  });

  it("reports evalsFrozen false when evals.json is GO but tier_justification is blank (unjustified)", () => {
    const base = makeTmpBase();
    const dir = join(base, "-unjustified-project", "S7");
    mkdirSync(dir, { recursive: true });
    writeFileSync(
      join(dir, "progress.json"),
      JSON.stringify({ status: "complete", session_id: "S7", completed_marker: 1, work_units: { wu1: { status: "done" } } })
    );
    writeFileSync(
      join(dir, "evals.json"),
      JSON.stringify({ scope: "loop", result: "GO", tier: 1, tier_justification: "" })
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
      JSON.stringify({ status: "complete", session_id: "S7b", completed_marker: 1, work_units: { unit1: { status: "done" } } })
    );
    writeFileSync(
      join(dir, "evals.json"),
      JSON.stringify({ scope: "loop", result: "GO", tier: 1, tier_justification: "2 work-units, no irreversible surface" })
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
      JSON.stringify({ status: "complete", session_id: "S7c", completed_marker: 1, work_units: { unit1: { status: "done" } } })
    );
    writeFileSync(
      join(dir, "evals.json"),
      JSON.stringify({
        scope: "loop",
        result: "GO",
        tier: 1,
        tier_justification: "2 work-units, no irreversible surface",
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
      JSON.stringify({ status: "complete", session_id: "S7d", completed_marker: 1, work_units: { unit1: { status: "done" } } })
    );
    writeFileSync(
      join(dir, "evals.json"),
      JSON.stringify({
        scope: "loop",
        result: "GO",
        tier: 1,
        tier_justification: "2 work-units, no irreversible surface",
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
      JSON.stringify({ status: "complete", session_id: "S8", completed_marker: 1, work_units: { wu1: { status: "done" } } })
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
        JSON.stringify({ status: "complete", session_id: "S1", work_units: {} })
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
      JSON.stringify({ status: "in-progress", session_id: "S21", work_units: {} })
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
      JSON.stringify({ status: "in-progress", session_id: "S22", work_units: {}, decisions_absorbed: "not-an-array" })
    );

    const dirB = join(base, "-decisions-badentries-project", "S23");
    mkdirSync(dirB, { recursive: true });
    writeFileSync(
      join(dirB, "progress.json"),
      JSON.stringify({
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
