import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

// Regression test for the Context Trend panel overflowing at narrow viewports.
// `.hud-trend-value` is `white-space: nowrap` inside a flex row, and the value is a long
// string by construction ("med 243K/turn · iqr 149K–326K"), so nowrap gives each row a hard
// minimum width. Under the `max-width: 1100px` breakpoint `.hud-stage` collapses to a single
// column, which makes the left rail viewport-width — so a narrow viewport drives the rail
// below that minimum, `.hud-trend-fill` (the flex:1 leader line) collapses to 0, and the
// value overflows the rail.
//
// The override that fixes this is ordering-sensitive, which is what these tests exist to pin.
// A media query contributes NO specificity, so the base `.hud-trend-value` rule and the
// narrow-viewport override are both (0,1,0) and the later one in source order wins. The
// override therefore has to sit AFTER the base rule. Placed in the earlier
// `max-width: 1100px` block (where the structurally identical `.hud-status-line` fix lives,
// which gets away with it only because ITS base rule is above that block), the override loses
// to the base rule, the computed value stays `nowrap` at every width, and the fix silently
// does nothing while still reading as present in the diff.
//
// jsdom has no layout engine and does not evaluate @media blocks at all, so asserting the
// rendered wrap here is not possible — mirroring the note in hudMarkdownWrap.test.ts. These
// tests pin the declarations and, critically, their relative source order. Whether the value
// visibly wraps in a real browser is verified separately against the running dashboard.
const css = readFileSync(join(__dirname, "../src/styles/hud.css"), "utf8");

// Byte offset of the base (top-level, unnested) `.hud-trend-value` rule. Anchored to the
// start of a line so it cannot match the indented copy nested inside a media query.
function baseValueRuleIndex(source: string): number {
  const match = source.match(/^\.hud-trend-value\s*\{[^}]*\}/m);
  if (!match || match.index === undefined) throw new Error("base .hud-trend-value rule not found in hud.css");
  return match.index;
}

function baseValueRule(source: string): string {
  const match = source.match(/^\.hud-trend-value\s*\{[^}]*\}/m);
  if (!match) throw new Error("base .hud-trend-value rule not found in hud.css");
  return match[0];
}

// Byte offset of the `.hud-trend-value` override nested inside a max-width: 1100px block.
// Indentation is what distinguishes it from the base rule above.
function overrideValueRuleIndex(source: string): number {
  const match = source.match(/^\s+\.hud-trend-value\s*\{[^}]*white-space:\s*normal[^}]*\}/m);
  if (!match || match.index === undefined) {
    throw new Error("narrow-viewport .hud-trend-value override not found in hud.css");
  }
  return match.index;
}

describe("hud.css Context Trend narrow-viewport width robustness", () => {
  it("wraps the value below the 1100px breakpoint so the row has no hard minimum width", () => {
    const match = css.match(/^\s+\.hud-trend-value\s*\{[^}]*\}/m);
    if (!match) throw new Error("narrow-viewport .hud-trend-value override not found in hud.css");
    expect(match[0]).toMatch(/white-space:\s*normal/);
    // Lets the value shrink as a flex child rather than holding its content width.
    expect(match[0]).toMatch(/min-width:\s*0/);
  });

  it("lets the row wrap so the value takes its own line instead of a sliver beside the label", () => {
    const match = css.match(/^\s+\.hud-trend-row\s*\{[^}]*\}/m);
    if (!match) throw new Error("narrow-viewport .hud-trend-row override not found in hud.css");
    expect(match[0]).toMatch(/flex-wrap:\s*wrap/);
  });

  it("keeps the leader line drawn instead of letting it collapse to zero width", () => {
    const match = css.match(/^\s+\.hud-trend-fill\s*\{[^}]*\}/m);
    if (!match) throw new Error("narrow-viewport .hud-trend-fill override not found in hud.css");
    expect(match[0]).toMatch(/min-width:\s*\d/);
  });

  // The load-bearing assertion. This is the one that fails if the override is moved back into
  // the earlier max-width: 1100px block, which is where it was first written and where it was
  // a silent no-op.
  it("declares the narrow-viewport override AFTER the base rule, so it wins the cascade", () => {
    expect(overrideValueRuleIndex(css)).toBeGreaterThan(baseValueRuleIndex(css));
  });

  // Negative control for the ordering assertion above: prove the check is capable of failing.
  // Reversing the two rules in a copy of the source must flip the comparison. Without this,
  // an ordering assertion that always passed would be indistinguishable from a correct one.
  it("ordering check can fail (negative control)", () => {
    const base = baseValueRule(css);
    const overrideMatch = css.match(/^\s+\.hud-trend-value\s*\{[^}]*white-space:\s*normal[^}]*\}/m);
    if (!overrideMatch) throw new Error("narrow-viewport .hud-trend-value override not found in hud.css");
    // Build a source where the ONLY narrow-viewport override sits above the base rule:
    // insert an indented copy before the base rule, and drop the real one further down.
    // The ordering check must then report the override as earlier, not later.
    const indentedCopy = overrideMatch[0].replace(/^\n?/, "");
    const broken = css.replace(overrideMatch[0], "").replace(base, `${indentedCopy}\n${base}`);
    expect(overrideValueRuleIndex(broken)).toBeLessThan(baseValueRuleIndex(broken));
  });

  // Desktop rendering must be untouched: the base rule keeps nowrap, so above the breakpoint
  // the value stays on one line exactly as PR #293 shipped it.
  it("leaves the base rule on nowrap so desktop rendering is unchanged", () => {
    expect(baseValueRule(css)).toMatch(/white-space:\s*nowrap/);
  });
});
