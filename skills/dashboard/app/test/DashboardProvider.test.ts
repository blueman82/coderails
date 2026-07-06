import { describe, it, expect } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { DashboardProvider, useDashboardContext } from "../src/components/DashboardProvider";

// Renders (SSR, no jsdom needed — react-dom/server works in plain Node)
// two sibling consumers under one DashboardProvider and asserts they see the
// exact same state object reference. This is the property the Task 9b
// post-review fix is about: one useDashboardState() call inside the
// provider, not one per panel — if each consumer read its own hook
// instance, two independently-created state objects would never be
// reference-equal even if their contents matched.
describe("DashboardProvider", () => {
  it("gives every consumer the same state object reference (one shared hook instance)", () => {
    const seen: unknown[] = [];

    function Consumer() {
      seen.push(useDashboardContext());
      return null;
    }

    renderToStaticMarkup(
      createElement(DashboardProvider, null, createElement(Consumer), createElement(Consumer))
    );

    expect(seen).toHaveLength(2);
    expect(seen[0]).toBe(seen[1]);
  });

  it("a consumer outside any provider falls back to the same initialDashboardState reference", () => {
    // Guards against the fallback default silently diverging into "its own state" —
    // it must be the one shared constant, not a fresh object per call.
    let a: unknown;
    let b: unknown;

    function ConsumerA() {
      a = useDashboardContext();
      return null;
    }
    function ConsumerB() {
      b = useDashboardContext();
      return null;
    }

    renderToStaticMarkup(createElement(ConsumerA));
    renderToStaticMarkup(createElement(ConsumerB));

    expect(a).toBe(b);
  });
});
