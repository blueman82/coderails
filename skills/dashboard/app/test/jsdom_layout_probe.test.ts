// @vitest-environment jsdom
import { describe, it, expect } from "vitest";

describe("jsdom layout probe", () => {
  it("checks if jsdom computes real scrollWidth/clientWidth", () => {
    const pre = document.createElement("pre");
    pre.style.width = "100px";
    pre.style.whiteSpace = "pre";
    pre.textContent = "a".repeat(1000);
    document.body.appendChild(pre);
    // eslint-disable-next-line no-console
    console.log("scrollWidth:", pre.scrollWidth, "clientWidth:", pre.clientWidth);
    expect(true).toBe(true);
  });
});
