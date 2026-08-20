import { describe, expect, it } from "vitest";
import { buildArgv, NON_INTERACTIVE_FRAMING, withExecSubcommand } from "../src/lib/argv";
import type { ButtonDef } from "../src/lib/config";

function button(overrides: Partial<ButtonDef> = {}): ButtonDef {
  return {
    name: "wiki-lint",
    label: "WIKI LINT",
    command: "$coderails-codex:wiki-lint",
    cwd: "/tmp/coderails",
    profile: "standard",
    ...overrides,
  };
}

describe("buildArgv", () => {
  it("defaults the standard profile to the read-only sandbox", () => {
    expect(buildArgv(button())).toEqual([
      "--sandbox",
      "read-only",
      `${NON_INTERACTIVE_FRAMING} $coderails-codex:wiki-lint`,
    ]);
  });

  it("uses the current read-only sandbox flag", () => {
    expect(buildArgv(button({ profile: "read-only" }))).toEqual([
      "--sandbox",
      "read-only",
      `${NON_INTERACTIVE_FRAMING} $coderails-codex:wiki-lint`,
    ]);
  });

  it("uses the native workspace-write sandbox for write-capable runs", () => {
    expect(buildArgv(button({ profile: "auto" }))).toEqual([
      "--sandbox",
      "workspace-write",
      "-c",
      "sandbox_workspace_write.network_access=false",
      `${NON_INTERACTIVE_FRAMING} $coderails-codex:wiki-lint`,
    ]);
  });

  it("puts profile flags before the end-of-options marker when input is present", () => {
    expect(buildArgv(button({ profile: "read-only" }), "extra context")).toEqual([
      "--sandbox",
      "read-only",
      "--",
      `${NON_INTERACTIVE_FRAMING} $coderails-codex:wiki-lint extra context`,
    ]);
  });

  it("uses input alone for a free-text button", () => {
    expect(buildArgv(button({ command: "" }), "what does this repo do?")).toEqual([
      "--sandbox",
      "read-only",
      "--",
      `${NON_INTERACTIVE_FRAMING} what does this repo do?`,
    ]);
  });

  it("keeps shell-looking input inside one prompt argument", () => {
    expect(buildArgv(button(), "; rm -rf /")).toEqual([
      "--sandbox",
      "read-only",
      "--",
      `${NON_INTERACTIVE_FRAMING} $coderails-codex:wiki-lint ; rm -rf /`,
    ]);
  });

  it("rejects flag-shaped input before building argv", () => {
    expect(() => buildArgv(button(), "--sandbox")).toThrow();
    expect(() => buildArgv(button(), "  --sandbox")).toThrow();
  });

  it("rejects an empty prompt", () => {
    expect(() => buildArgv(button({ command: "" }))).toThrow();
    expect(() => buildArgv(button({ command: "   " }), "   ")).toThrow();
  });

  it("treats blank input as no input", () => {
    expect(buildArgv(button(), "   ")).toEqual(buildArgv(button()));
  });

  it("returns a fresh array", () => {
    const first = buildArgv(button({ profile: "read-only" }));
    first.push("mutated");
    expect(buildArgv(button({ profile: "read-only" }))).not.toContain("mutated");
  });
});

describe("withExecSubcommand", () => {
  it("keeps exactly one exec subcommand", () => {
    const argv = withExecSubcommand(buildArgv(button()));
    expect(argv.filter((arg) => arg === "exec")).toHaveLength(1);
    expect(withExecSubcommand(argv)).toEqual(argv);
  });
});
