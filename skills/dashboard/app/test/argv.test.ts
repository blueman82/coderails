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

  it("merges input into a single prompt string after a '--' end-of-options sentinel, so the CLI's single positional prompt argument carries both (the CLI never merges two separate positionals — confirmed empirically, see comment above)", () => {
    const argv = buildArgv(button({ profile: "standard" }), "extra context here");
    expect(argv).toEqual(["-p", "--", "/coderails:wiki-lint extra context here"]);
  });

  it("still separates command from input with a space rather than string concatenation", () => {
    const argv = buildArgv(button({ profile: "standard" }), "; rm -rf /");
    expect(argv).toEqual(["-p", "--", "/coderails:wiki-lint ; rm -rf /"]);
  });

  it("places the '--' sentinel and merged prompt after profile flags for a read-only-profile button", () => {
    const argv = buildArgv(button({ profile: "read-only" }), "note");
    expect(argv).toEqual([
      "-p",
      "--allowedTools",
      ...READ_ONLY_ALLOWED_TOOLS,
      "--",
      "/coderails:wiki-lint note",
    ]);
  });

  it("uses input alone as the prompt when the button's command is empty (free-text ask button)", () => {
    const argv = buildArgv(button({ profile: "standard", command: "" }), "what does this codebase do?");
    expect(argv).toEqual(["-p", "--", "what does this codebase do?"]);
  });

  it("rejects input that starts with '-' (flag smuggling) by throwing", () => {
    expect(() => buildArgv(button({ profile: "standard" }), "--dangerously-skip-permissions")).toThrow();
    expect(() => buildArgv(button({ profile: "standard" }), "-p")).toThrow();
  });

  it("rejects an empty command with no input by throwing, rather than spawning an empty prompt", () => {
    expect(() => buildArgv(button({ profile: "standard", command: "" }))).toThrow();
  });

  it("rejects a whitespace-only command with no input by throwing", () => {
    expect(() => buildArgv(button({ profile: "standard", command: "   " }))).toThrow();
  });

  it("rejects empty input when the command is also empty, rather than spawning an empty prompt", () => {
    expect(() => buildArgv(button({ profile: "standard", command: "" }), "")).toThrow();
  });

  it("rejects whitespace-only input when the command is also empty or whitespace-only", () => {
    expect(() => buildArgv(button({ profile: "standard", command: "" }), "   ")).toThrow();
    expect(() => buildArgv(button({ profile: "standard", command: "   " }), "   ")).toThrow();
  });

  it("does not insert a '--' sentinel when there is no input", () => {
    const argv = buildArgv(button({ profile: "standard" }));
    expect(argv).toEqual(["-p", "/coderails:wiki-lint"]);
    expect(argv).not.toContain("--");
  });

  it("returns a fresh array on each call (no shared mutable state)", () => {
    const a = buildArgv(button({ profile: "read-only" }));
    a.push("mutated");
    const b = buildArgv(button({ profile: "read-only" }));
    expect(b).not.toContain("mutated");
  });
});
