import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";

// Regression test for the owner-reported bug: the run-output modal (RunOutputOverlay.tsx,
// rendered inside a .hud-markdown container) did not wrap long lines — fenced code blocks and
// long unbroken tokens inside `.hud-markdown pre` overflowed the modal horizontally instead of
// wrapping.
//
// jsdom has no layout engine (verified: scrollWidth and clientWidth both read back as 0 for an
// element with an explicit width and overflowing content), so a DOM-rendered assertion that a
// <pre> actually wraps is not possible here. This test instead pins the CSS declarations that
// cause wrapping directly in the stylesheet source, mirroring hudRailScroll.test.ts. Whether a
// long line visibly wraps in a real browser still needs checking against the live rendered page —
// that is out of reach for this test file and must be verified separately.
const css = readFileSync(join(__dirname, "../src/styles/hud.css"), "utf8");

function markdownPreRule(source: string): string {
  // Anchored so it can't match the sibling `.hud-markdown pre code { ... }` rule below it
  // (that selector has "code" before the brace, so `pre\s*\{` doesn't match it).
  const match = source.match(/\.hud-markdown pre\s*\{[^}]*\}/);
  if (!match) throw new Error(".hud-markdown pre rule not found in hud.css");
  return match[0];
}

describe("hud.css .hud-markdown pre wrapping", () => {
  it("wraps long lines instead of only relying on horizontal scroll", () => {
    const rule = markdownPreRule(css);
    expect(rule).toMatch(/white-space:\s*pre-wrap/);
    expect(rule).toMatch(/overflow-wrap:\s*anywhere/);
    expect(rule).toMatch(/word-break:\s*break-word/);
  });

  it("keeps overflow-x: auto as a harmless fallback for anything that still can't wrap", () => {
    const rule = markdownPreRule(css);
    expect(rule).toMatch(/overflow-x:\s*auto/);
  });
});
