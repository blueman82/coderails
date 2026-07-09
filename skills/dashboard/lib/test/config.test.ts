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
      repos: [], wikiPaths: [], memoryPaths: [], buttons: [baseButton],
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
      repos: [], wikiPaths: [], memoryPaths: [],
      buttons: [baseButton, { ...baseButton }],
    });
    expect(() => loadConfig(path)).toThrow(ConfigError);
  });

  it("throws ConfigError on an unknown profile", () => {
    const path = writeConfig({
      repos: [], wikiPaths: [], memoryPaths: [],
      buttons: [{ ...baseButton, profile: "godmode" }],
    });
    expect(() => loadConfig(path)).toThrow(ConfigError);
  });

  it("throws ConfigError when profile is bypass but bypassPermissions is not true", () => {
    const path = writeConfig({
      repos: [], wikiPaths: [], memoryPaths: [],
      buttons: [{ ...baseButton, profile: "bypass" }],
    });
    expect(() => loadConfig(path)).toThrow(ConfigError);
  });

  it("throws ConfigError on a relative cwd", () => {
    const path = writeConfig({
      repos: [], wikiPaths: [], memoryPaths: [],
      buttons: [{ ...baseButton, cwd: "relative/path" }],
    });
    expect(() => loadConfig(path)).toThrow(ConfigError);
  });

  it("loads a valid routines section alongside buttons", () => {
    const path = writeConfig({
      repos: [], wikiPaths: [], memoryPaths: [], buttons: [baseButton],
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
      repos: [], wikiPaths: [], memoryPaths: [], buttons: [baseButton],
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
      repos: [], wikiPaths: [], memoryPaths: [], buttons: [baseButton],
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
      repos: [], wikiPaths: [], memoryPaths: [], buttons: [baseButton],
      routines: [routine, { ...routine }],
    });
    expect(() => loadConfig(path)).toThrow(ConfigError);
  });

  it("throws ConfigError when expectedArtifact.maxAgeSeconds is not a positive number", () => {
    const path = writeConfig({
      repos: [], wikiPaths: [], memoryPaths: [], buttons: [baseButton],
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
      repos: [], wikiPaths: [], memoryPaths: [], buttons: [baseButton],
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
      repos: [], wikiPaths: [], memoryPaths: [], buttons: [baseButton],
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
      repos: [], wikiPaths: [], memoryPaths: [], buttons: [baseButton],
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
      repos: [], wikiPaths: [], memoryPaths: [], buttons: [baseButton],
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
      repos: [], wikiPaths: [], memoryPaths: [], buttons: [baseButton],
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

  it("loads all five buttons and all four routines", () => {
    const config = loadConfig(EXAMPLE_CONFIG_PATH);
    expect(config.buttons.map((b) => b.name)).toEqual([
      "wiki-lint",
      "sync-docs-weekly",
      "memory-consolidation-weekly",
      "ask",
      "loop-retro-promotion",
    ]);
    expect(config.routines?.map((r) => r.name)).toEqual([
      "wiki-lint",
      "sync-docs-weekly",
      "memory-consolidation-weekly",
      "loop-retro-promotion-weekly",
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
});
