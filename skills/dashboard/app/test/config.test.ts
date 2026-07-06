import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadConfig, ConfigError } from "../src/lib/config";

const tmpDirs: string[] = [];

function writeConfig(contents: unknown): string {
  const dir = mkdtempSync(join(tmpdir(), "dashboard-config-test-"));
  tmpDirs.push(dir);
  const path = join(dir, "config.json");
  writeFileSync(path, JSON.stringify(contents));
  return path;
}

afterEach(() => {
  for (const dir of tmpDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

const validConfig = {
  repos: ["blueman82/coderails"],
  wikiPaths: ["/Users/harrison/Github/coderails-wiki"],
  memoryPaths: ["/Users/harrison/.claude/projects/-Users-harrison-Github-coderails/memory"],
  buttons: [
    {
      name: "wiki-lint",
      label: "WIKI LINT",
      command: "/coderails:wiki-lint",
      cwd: "/Users/harrison/Github/coderails",
      profile: "standard",
    },
  ],
};

describe("loadConfig", () => {
  it("parses a valid config", () => {
    const path = writeConfig(validConfig);
    const config = loadConfig(path);
    expect(config).toEqual(validConfig);
  });

  it("throws ConfigError naming the path when the file is missing", () => {
    const missingPath = join(tmpdir(), "does-not-exist-dashboard-config.json");
    expect(() => loadConfig(missingPath)).toThrow(ConfigError);
    expect(() => loadConfig(missingPath)).toThrow(missingPath);
  });

  it("throws when button names are duplicated", () => {
    const path = writeConfig({
      ...validConfig,
      buttons: [
        validConfig.buttons[0],
        { ...validConfig.buttons[0] },
      ],
    });
    expect(() => loadConfig(path)).toThrow(ConfigError);
    expect(() => loadConfig(path)).toThrow(/name/i);
  });

  it("throws when profile is 'bypass' without bypassPermissions: true", () => {
    const path = writeConfig({
      ...validConfig,
      buttons: [
        {
          ...validConfig.buttons[0],
          name: "bypass-button",
          profile: "bypass",
        },
      ],
    });
    expect(() => loadConfig(path)).toThrow(ConfigError);
    expect(() => loadConfig(path)).toThrow(/bypassPermissions/);
  });

  it("throws when a button's cwd is relative", () => {
    const path = writeConfig({
      ...validConfig,
      buttons: [
        {
          ...validConfig.buttons[0],
          cwd: "relative/path",
        },
      ],
    });
    expect(() => loadConfig(path)).toThrow(ConfigError);
    expect(() => loadConfig(path)).toThrow(/cwd/i);
  });

  it("throws when a button's profile is unknown", () => {
    const path = writeConfig({
      ...validConfig,
      buttons: [
        {
          ...validConfig.buttons[0],
          profile: "admin",
        },
      ],
    });
    expect(() => loadConfig(path)).toThrow(ConfigError);
    expect(() => loadConfig(path)).toThrow(/profile/i);
  });
});
