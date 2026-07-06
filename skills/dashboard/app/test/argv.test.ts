import { describe, it, expect } from "vitest";
import { buildArgv, READ_ONLY_ALLOWED_TOOLS } from "../src/lib/argv";
import type { ButtonDef } from "../src/lib/config";

function button(overrides: Partial<ButtonDef> = {}): ButtonDef {
  return {
    name: "wiki-lint",
    label: "WIKI LINT",
    command: "/coderails:wiki-lint",
    cwd: "/Users/harrison/Github/coderails",
    profile: "standard",
    ...overrides,
  };
}

describe("buildArgv", () => {
  it("builds a bare -p argv for a standard-profile button", () => {
    const argv = buildArgv(button({ profile: "standard" }));
    expect(argv).toEqual(["-p", "/coderails:wiki-lint"]);
  });

  it("appends --allowedTools with the read-only set for a read-only-profile button", () => {
    const argv = buildArgv(button({ profile: "read-only" }));
    expect(argv).toEqual([
      "-p",
      "/coderails:wiki-lint",
      "--allowedTools",
      ...READ_ONLY_ALLOWED_TOOLS,
    ]);
  });

  it("appends --dangerously-skip-permissions for a bypass-profile button", () => {
    const argv = buildArgv(button({ profile: "bypass", bypassPermissions: true }));
    expect(argv).toEqual([
      "-p",
      "/coderails:wiki-lint",
      "--dangerously-skip-permissions",
    ]);
  });

  it("appends input as exactly one trailing argv element for a standard-profile button", () => {
    const argv = buildArgv(button({ profile: "standard" }), "extra context here");
    expect(argv).toEqual(["-p", "/coderails:wiki-lint", "extra context here"]);
  });

  it("never concatenates input into the command string", () => {
    const argv = buildArgv(button({ profile: "standard" }), "; rm -rf /");
    expect(argv[1]).toBe("/coderails:wiki-lint");
    expect(argv).toContain("; rm -rf /");
    expect(argv.some((a) => a.includes("/coderails:wiki-lint; rm -rf /"))).toBe(false);
  });

  it("places input after profile flags for a read-only-profile button", () => {
    const argv = buildArgv(button({ profile: "read-only" }), "note");
    expect(argv).toEqual([
      "-p",
      "/coderails:wiki-lint",
      "--allowedTools",
      ...READ_ONLY_ALLOWED_TOOLS,
      "note",
    ]);
  });

  it("returns a fresh array on each call (no shared mutable state)", () => {
    const a = buildArgv(button({ profile: "read-only" }));
    a.push("mutated");
    const b = buildArgv(button({ profile: "read-only" }));
    expect(b).not.toContain("mutated");
  });
});
