import { describe, it, expect } from "vitest";
import { homedir } from "node:os";
import { join } from "node:path";
import { collectLoops } from "../src/lib/collect/sessions";

// Task 4 brief's required live check: confirm collectLoops never throws
// against the real ~/.claude/agentic-loop base on this machine. Not a
// permanent suite member — run ad hoc, remove before commit.
describe("collectLoops live check (temporary, not committed)", () => {
  it("does not throw against the real base and returns an array", () => {
    const base = join(homedir(), ".claude", "agentic-loop");
    let result;
    expect(() => {
      result = collectLoops(base);
    }).not.toThrow();
    expect(Array.isArray(result)).toBe(true);
    console.log(`live check: ${(result as unknown[]).length} loop(s) found, shape sample:`, JSON.stringify(result, null, 2).slice(0, 2000));
  });
});
