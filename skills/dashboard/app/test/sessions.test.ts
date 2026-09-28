import { makeTmpBase, writeSessionFile } from "./sessions.fixture";
import { describe, it, expect } from "vitest";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { collectSessions } from "../src/lib/collect/sessions";

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
