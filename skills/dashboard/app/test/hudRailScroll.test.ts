import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

// Regression test for the owner-reported bug: at normal desktop viewport heights
// (i.e. outside the `max-width: 1100px` and `max-height: 760px` fallback breakpoints,
// which intentionally switch to whole-page scroll instead — see hud.css), the left and
// right rails clipped overflowing content with no scrollbar and no way to scroll it.
// `.hud-rail` is a grid item in a fixed-height (`1fr`) row, so it must own its own
// overflow-y: auto scrolling for that content to be reachable at all.
const css = readFileSync(join(__dirname, "../src/styles/hud.css"), "utf8");

function baseRailRule(source: string): string {
  const match = source.match(/\.hud-rail\s*\{[^}]*\}/);
  if (!match) throw new Error("base .hud-rail rule not found in hud.css");
  return match[0];
}

describe("hud.css rail scrolling", () => {
  it("makes the base .hud-rail rule vertically scrollable, not clipped", () => {
    const rule = baseRailRule(css);
    expect(rule).toMatch(/overflow-y:\s*auto/);
  });

  it("does not clip the base .hud-rail rule with overflow: hidden (negative control)", () => {
    const rule = baseRailRule(css);
    expect(rule).not.toMatch(/overflow:\s*hidden/);
  });

  it("gives the rail scrollbar a visible, HUD-themed thumb (not the invisible default)", () => {
    expect(css).toMatch(/\.hud-rail::-webkit-scrollbar-thumb\s*\{[^}]*background-color:\s*var\(--rose-dim\)/);
    expect(css).toMatch(/\.hud-rail\s*\{[^}]*scrollbar-color:\s*var\(--rose-dim\)/);
  });
});
