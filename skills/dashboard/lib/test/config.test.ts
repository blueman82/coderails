import { describe, it, expect } from "vitest";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { loadConfig, ConfigError } from "../src/config";

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..", "..");
const EXAMPLE_CONFIG_PATH = join(REPO_ROOT, "examples", "dashboard-config.json");

function writeConfig(obj: unknown): string {
  const dir = mkdtempSync(join(tmpdir(), "dashboard-config-test-"));
  const path = join(dir, "config.json");
  writeFileSync(path, JSON.stringify(obj));
  return path;
}

const baseButton = {
  name: "wiki-lint",
  label: "WIKI LINT",
  command: "/coderails:wiki-lint",
  cwd: "/Users/harrison/Github/coderails",
  profile: "read-only",
};

describe("loadConfig", () => {
  it("loads a minimal valid config with no routines", () => {
    const path = writeConfig({
      repos: [], wikiPaths: [], buttons: [baseButton],
    });
    const config = loadConfig(path);
    expect(config.buttons).toHaveLength(1);
    expect(config.routines).toBeUndefined();
  });

  it("throws ConfigError when the file does not exist", () => {
    expect(() => loadConfig("/nonexistent/path/config.json")).toThrow(ConfigError);
  });

  it("throws ConfigError on malformed JSON", () => {
    const dir = mkdtempSync(join(tmpdir(), "dashboard-config-test-"));
    const path = join(dir, "config.json");
    writeFileSync(path, "{not json");
    expect(() => loadConfig(path)).toThrow(ConfigError);
  });

  it("throws ConfigError on a duplicate button name", () => {
    const path = writeConfig({
      repos: [], wikiPaths: [],
      buttons: [baseButton, { ...baseButton }],
    });
    expect(() => loadConfig(path)).toThrow(ConfigError);
  });

  it("throws ConfigError on an unknown profile", () => {
    const path = writeConfig({
      repos: [], wikiPaths: [],
      buttons: [{ ...baseButton, profile: "godmode" }],
    });
    expect(() => loadConfig(path)).toThrow(ConfigError);
  });

  it("throws ConfigError when profile is bypass but bypassPermissions is not true", () => {
    const path = writeConfig({
      repos: [], wikiPaths: [],
      buttons: [{ ...baseButton, profile: "bypass" }],
    });
    expect(() => loadConfig(path)).toThrow(ConfigError);
  });

  it("throws ConfigError on a relative cwd", () => {
    const path = writeConfig({
      repos: [], wikiPaths: [],
      buttons: [{ ...baseButton, cwd: "relative/path" }],
    });
    expect(() => loadConfig(path)).toThrow(ConfigError);
  });

  it("loads a valid routines section alongside buttons", () => {
    const path = writeConfig({
      repos: [], wikiPaths: [], buttons: [baseButton],
      routines: [
        {
          name: "wiki-lint-nightly",
          skillCommand: "/coderails:wiki-lint",
          cadence: "0 3 * * *",
          expectedArtifact: {
            artifactPath: "{vault}/log.md",
            maxAgeSeconds: 129600,
            predicate: { kind: "contains", marker: "## [{date}] lint" },
          },
          escalation: ["notification", "vault-note"],
        },
      ],
    });
    const config = loadConfig(path);
    expect(config.routines).toHaveLength(1);
    expect(config.routines?.[0].name).toBe("wiki-lint-nightly");
  });

  it("throws ConfigError when a routine has neither skillCommand nor buttonRef", () => {
    const path = writeConfig({
      repos: [], wikiPaths: [], buttons: [baseButton],
      routines: [
        {
          name: "broken-routine",
          cadence: "0 3 * * *",
          expectedArtifact: {
            artifactPath: "{vault}/log.md",
            maxAgeSeconds: 100,
            predicate: { kind: "exists" },
          },
          escalation: ["notification"],
        },
      ],
    });
    expect(() => loadConfig(path)).toThrow(ConfigError);
  });

  it("throws ConfigError when a routine's buttonRef does not match any button name", () => {
    const path = writeConfig({
      repos: [], wikiPaths: [], buttons: [baseButton],
      routines: [
        {
          name: "orphan-ref",
          buttonRef: "does-not-exist",
          cadence: "0 3 * * *",
          expectedArtifact: {
            artifactPath: "{vault}/log.md",
            maxAgeSeconds: 100,
            predicate: { kind: "exists" },
          },
          escalation: ["notification"],
        },
      ],
    });
    expect(() => loadConfig(path)).toThrow(ConfigError);
  });

  it("throws ConfigError on a duplicate routine name", () => {
    const routine = {
      name: "dup",
      skillCommand: "/coderails:wiki-lint",
      cadence: "0 3 * * *",
      expectedArtifact: {
        artifactPath: "{vault}/log.md",
        maxAgeSeconds: 100,
        predicate: { kind: "exists" },
      },
      escalation: ["notification"],
    };
    const path = writeConfig({
      repos: [], wikiPaths: [], buttons: [baseButton],
      routines: [routine, { ...routine }],
    });
    expect(() => loadConfig(path)).toThrow(ConfigError);
  });

  it("throws ConfigError when expectedArtifact.maxAgeSeconds is not a positive number", () => {
    const path = writeConfig({
      repos: [], wikiPaths: [], buttons: [baseButton],
      routines: [
        {
          name: "bad-maxage",
          skillCommand: "/coderails:wiki-lint",
          cadence: "0 3 * * *",
          expectedArtifact: {
            artifactPath: "{vault}/log.md",
            maxAgeSeconds: -1,
            predicate: { kind: "exists" },
          },
          escalation: ["notification"],
        },
      ],
    });
    expect(() => loadConfig(path)).toThrow(ConfigError);
  });

  it("throws ConfigError on an unknown predicate kind", () => {
    const path = writeConfig({
      repos: [], wikiPaths: [], buttons: [baseButton],
      routines: [
        {
          name: "bad-predicate",
          skillCommand: "/coderails:wiki-lint",
          cadence: "0 3 * * *",
          expectedArtifact: {
            artifactPath: "{vault}/log.md",
            maxAgeSeconds: 100,
            predicate: { kind: "regex-match" },
          },
          escalation: ["notification"],
        },
      ],
    });
    expect(() => loadConfig(path)).toThrow(ConfigError);
  });

  it("throws ConfigError on an unknown escalation channel", () => {
    const path = writeConfig({
      repos: [], wikiPaths: [], buttons: [baseButton],
      routines: [
        {
          name: "bad-escalation",
          skillCommand: "/coderails:wiki-lint",
          cadence: "0 3 * * *",
          expectedArtifact: {
            artifactPath: "{vault}/log.md",
            maxAgeSeconds: 100,
            predicate: { kind: "exists" },
          },
          escalation: ["notification", "carrier-pigeon"],
        },
      ],
    });
    expect(() => loadConfig(path)).toThrow(ConfigError);
  });

  it("throws ConfigError when a routine has a relative foreignSkillPath", () => {
    const path = writeConfig({
      repos: [], wikiPaths: [], buttons: [baseButton],
      routines: [
        {
          name: "relative-foreign-skill",
          skillCommand: "/coderails:wiki-lint",
          cadence: "0 3 * * *",
          expectedArtifact: {
            artifactPath: "{vault}/log.md",
            maxAgeSeconds: 100,
            predicate: { kind: "exists" },
          },
          escalation: ["notification"],
          foreignSkillPath: "relative/skill/path",
        },
      ],
    });
    expect(() => loadConfig(path)).toThrow(ConfigError);
  });

  it("loads a routine with a valid absolute foreignSkillPath", () => {
    const path = writeConfig({
      repos: [], wikiPaths: [], buttons: [baseButton],
      routines: [
        {
          name: "absolute-foreign-skill",
          skillCommand: "/coderails:wiki-lint",
          cadence: "0 3 * * *",
          expectedArtifact: {
            artifactPath: "{vault}/log.md",
            maxAgeSeconds: 100,
            predicate: { kind: "exists" },
          },
          escalation: ["notification"],
          foreignSkillPath: "/Users/harrison/Github/other-repo/skill",
        },
      ],
    });
    const config = loadConfig(path);
    expect(config.routines?.[0].foreignSkillPath).toBe("/Users/harrison/Github/other-repo/skill");
  });

  it("throws ConfigError when expectedArtifact.artifactPath is empty", () => {
    const path = writeConfig({
      repos: [], wikiPaths: [], buttons: [baseButton],
      routines: [
        {
          name: "empty-artifact-path",
          skillCommand: "/coderails:wiki-lint",
          cadence: "0 3 * * *",
          expectedArtifact: {
            artifactPath: "",
            maxAgeSeconds: 100,
            predicate: { kind: "exists" },
          },
          escalation: ["notification"],
        },
      ],
    });
    expect(() => loadConfig(path)).toThrow(ConfigError);
  });
});

describe("loadConfig against the real examples/dashboard-config.json (C3)", () => {
  // Loads the actual repo file — not a synthetic fixture that merely
  // resembles it — through the actual routine-aware loadConfig() this file
  // wraps around loadBaseConfig(). Before this test, nothing in the repo
  // ever exercised examples/dashboard-config.json through a validator at
  // all: it could silently drift out of sync with config.ts's validation
  // rules (or with sweep.ts/seed.ts's expectations) and no test would catch
  // it, since it's a reference/documentation artifact, not code any
  // existing suite imports.
  it("validates without throwing", () => {
    expect(() => loadConfig(EXAMPLE_CONFIG_PATH)).not.toThrow();
  });

  it("loads all six buttons and all five routines", () => {
    const config = loadConfig(EXAMPLE_CONFIG_PATH);
    expect(config.buttons.map((b) => b.name)).toEqual([
      "wiki-lint",
      "sync-docs-weekly",
      "memory-consolidation-weekly",
      "ask",
      "loop-retro-promotion",
      "inbox-brief",
      "workflow-audit-weekly",
    ]);
    expect(config.routines?.map((r) => r.name)).toEqual([
      "wiki-lint",
      "sync-docs-weekly",
      "memory-consolidation-weekly",
      "loop-retro-promotion-weekly",
      "workflow-audit-weekly",
    ]);
  });

  it("every routine's buttonRef resolves to a real ButtonDef (matches sweep.ts's findRoutine/findButton contract)", () => {
    const config = loadConfig(EXAMPLE_CONFIG_PATH);
    const buttonNames = new Set(config.buttons.map((b) => b.name));
    for (const routine of config.routines ?? []) {
      expect(routine.buttonRef, `routine "${routine.name}" has no buttonRef`).toBeDefined();
      expect(buttonNames.has(routine.buttonRef as string), `routine "${routine.name}"'s buttonRef "${routine.buttonRef}" matches no button`).toBe(true);
    }
  });

  // A routine's gate checks a path the RUN has to write. Nothing tells the run
  // what that path is except the instruction it is handed, so a command that
  // never names the artifact leaves the filename to be guessed — and a guess
  // that misses fails the gate on every future run, not just once. Live-fire
  // 2026-07-16 caught exactly this: workflow-audit-weekly's command said only
  // "write the run note", the run chose `{date}-run.md`, the gate wanted
  // `run-{date}.md`, and the sweep went red with correct note content.
  //
  // Exempt: a routine whose skill owns the path itself (memory-consolidation
  // names it in SKILL.md; wiki-lint's `{vault}/log.md` is the lint's own
  // output). Those can't drift from a command that never mentions a path.
  //
  // loop-retro-promotion-weekly is exempt as KNOWN-BROKEN, not as compliant:
  // its gate points at a `-Users-harrison-Documents-Github-...` repo-key dir
  // that does not exist (the repo lives at ~/Github, not ~/Documents/Github),
  // while the real promotion-runs.log sits in the correct dir — so its gate
  // cannot pass regardless of what its command says. That predates this
  // routine and is out of scope here; exempting it keeps this guard honest
  // about what it does check rather than silently widening the fix.
  it("every routine whose skill does not own its artifact path has that path named in the button command", () => {
    const config = loadConfig(EXAMPLE_CONFIG_PATH);
    const SKILL_OWNS_ITS_PATH = new Set([
      "wiki-lint",
      "memory-consolidation-weekly",
      "loop-retro-promotion-weekly",
    ]);
    const byName = new Map(config.buttons.map((b) => [b.name, b]));

    for (const routine of config.routines ?? []) {
      if (SKILL_OWNS_ITS_PATH.has(routine.name)) continue;
      const command = byName.get(routine.buttonRef as string)?.command ?? "";
      // Compare on the basename template (e.g. "run-{date}.md"): the command
      // writes a ~-relative path while the gate stores it absolute.
      const basename = routine.expectedArtifact.artifactPath.split("/").pop() as string;
      expect(
        command.includes(basename),
        `routine "${routine.name}" gates on "${routine.expectedArtifact.artifactPath}" but its button command never names "${basename}" — the run has to guess the filename`,
      ).toBe(true);

      // Same bug class, other half: a `contains` gate gives the run a marker to
      // emit. If the command never states it, the run guesses the wording and
      // the gate reds out exactly as it did on the filename. Assert the marker's
      // static tail only — the two sides notate the date differently ("{date}"
      // in the gate, "<YYYY-MM-DD>" in the command prose), so the templated
      // marker never matches verbatim.
      if (routine.expectedArtifact.predicate.kind !== "contains") continue;
      const markerTail = routine.expectedArtifact.predicate.marker.split("]").pop()?.trim() ?? "";
      if (markerTail === "") continue; // marker carries no static text to pin
      expect(
        command.includes(markerTail),
        `routine "${routine.name}" gates on marker "${routine.expectedArtifact.predicate.marker}" but its button command never states "${markerTail}" — the run has to guess the marker wording`,
      ).toBe(true);
    }
  });
});
