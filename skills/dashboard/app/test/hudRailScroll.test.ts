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

// Finds the `.hud-rail { ... }` block nested inside a given @media query, so the two
// breakpoint fallbacks (narrow viewports, short desktop windows) can be asserted
// independently of the base rule and of each other.
function railRuleInMediaQuery(source: string, mediaQuery: string): string {
  const mediaIndex = source.indexOf(mediaQuery);
  if (mediaIndex === -1) throw new Error(`media query "${mediaQuery}" not found in hud.css`);
  const railIndex = source.indexOf(".hud-rail {", mediaIndex);
  if (railIndex === -1) throw new Error(`.hud-rail rule not found inside "${mediaQuery}"`);
  const match = source.slice(railIndex).match(/\.hud-rail\s*\{[^}]*\}/);
  if (!match) throw new Error(`.hud-rail rule not found inside "${mediaQuery}"`);
  return match[0];
}

describe("hud.css rail scrolling", () => {
  it("makes the base .hud-rail rule vertically scrollable, not clipped", () => {
    const rule = baseRailRule(css);
    expect(rule).toMatch(/overflow-y:\s*auto/);
  });

  it("does not clip the base .hud-rail rule with overflow: hidden (negative control)", () => {
    const rule = baseRailRule(css);
    // Word-boundary anchored so a legitimate `overflow-x: hidden` on the same rule
    // (which does exist here) can't hide a stray `overflow: hidden` alongside it.
    expect(rule).not.toMatch(/(?<![\w-])overflow:\s*hidden/);
  });

  it("gives the rail scrollbar a visible, HUD-themed thumb (not the invisible default)", () => {
    expect(css).toMatch(/\.hud-rail::-webkit-scrollbar-thumb\s*\{[^}]*background-color:\s*var\(--rose-dim\)/);
    expect(css).toMatch(/\.hud-rail\s*\{[^}]*scrollbar-color:\s*var\(--rose-dim\)/);
  });

  // Narrow (max-width: 1100px) and short-desktop (max-height: 760px) viewports use a
  // different, deliberate strategy: the whole page scrolls instead of each rail scrolling
  // independently, so .hud-rail reverts to overflow: visible there. Pinned so a future
  // "fix" for this bug can't delete these overrides and silently break that fallback.
  it("keeps the narrow-viewport fallback reverting .hud-rail to overflow: visible", () => {
    const rule = railRuleInMediaQuery(css, "@media (max-width: 1100px)");
    expect(rule).toMatch(/overflow:\s*visible/);
  });

  it("keeps the short-desktop fallback reverting .hud-rail to overflow: visible", () => {
    const rule = railRuleInMediaQuery(css, "@media (max-height: 760px)");
    expect(rule).toMatch(/overflow:\s*visible/);
  });
});
