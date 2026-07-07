import { describe, it, expect } from "vitest";
import { writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadConfig, ConfigError } from "../src/config";

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
