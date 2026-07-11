import { describe, it, expect } from "vitest";
import { readFileSync } from "fs";
import { projectAssistantText } from "../src/lib/streamJson";
import os from "os";

describe("sanity against real fixture logs", () => {
  it("ca01962c69681a03.log projects to the result field text", () => {
    const raw = readFileSync(`${os.homedir()}/.claude/coderails-dashboard/runs/ca01962c69681a03.log`, "utf-8");
    const projected = projectAssistantText(raw);
    console.log("--- ca01 projected ---\n", projected.slice(0, 300));
    expect(projected).not.toBe(raw);
    expect(projected.length).toBeGreaterThan(0);
  });

  it("c17d360fd50a9316.log projects to the result field text", () => {
    const raw = readFileSync(`${os.homedir()}/.claude/coderails-dashboard/runs/c17d360fd50a9316.log`, "utf-8");
    const projected = projectAssistantText(raw);
    console.log("--- c17d projected (first 300 chars) ---\n", projected.slice(0, 300));
    console.log("--- raw length vs projected length ---", raw.length, projected.length);
    expect(projected).not.toBe(raw);
    expect(projected.length).toBeGreaterThan(0);
  });
});
