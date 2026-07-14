import { describe, it, expect } from "vitest";
import { readMarkerVersions } from "../src/lib/collect/markerVersions";
import { parseGates, collectPrGates } from "../src/lib/collect/prGates";
import type { DashboardConfig } from "../src/lib/config";

const versions = readMarkerVersions();
if (!versions.eval || !versions.review) {
  throw new Error(
    "Could not read marker versions from scripts/lib/{eval,review}-artifact.sh — fixtures cannot be built"
  );
}
const EVAL_VER = versions.eval;
const REVIEW_VER = versions.review;

function evalMarker(pr: number, headSha: string, result: "GO" | "NO-GO", tier: number): string {
  return `<!-- coderails-eval-summary ${EVAL_VER} pr=${pr} head_sha=${headSha} result=${result} tier=${tier} -->`;
}

function reviewMarker(pr: number, headSha: string): string {
  return `<!-- coderails-review-summary ${REVIEW_VER} pr=${pr} head_sha=${headSha} -->`;
}

function comment(body: string): { body: string } {
  return { body };
}

const HEAD_SHA = "86176fc95917ac604cedae9fed139df7b5ee8017";
const OLD_SHA = "3b4be2f0000000000000000000000000000000";

function prJson(overrides: Partial<{ number: number; title: string; headRefOid: string }> = {}) {
  return {
    number: 4,
    title: "task evals/wu4 wiring",
    headRefOid: HEAD_SHA,
    ...overrides,
  };
}

describe("parseGates", () => {
  it("reports review present and evals pass, state merge-ready when both markers match the current head SHA", () => {
    const gate = parseGates(prJson(), [
      comment(evalMarker(4, HEAD_SHA, "GO", 1)),
      comment(reviewMarker(4, HEAD_SHA)),
    ]);
    expect(gate).toEqual({
      repo: "",
      number: 4,
      title: "task evals/wu4 wiring",
      headSha: HEAD_SHA,
      review: "present",
      evals: "pass",
      tier: "1",
      state: "merge-ready",
    });
  });

  it("reports evals fail when the eval marker's result is NO-GO", () => {
    const gate = parseGates(prJson(), [
      comment(evalMarker(4, HEAD_SHA, "NO-GO", 1)),
      comment(reviewMarker(4, HEAD_SHA)),
    ]);
    expect(gate.evals).toBe("fail");
    expect(gate.state).toBe("blocked");
  });

  it("marks evals stale when the eval marker's head_sha is older than the PR's current headRefOid", () => {
    const gate = parseGates(prJson(), [
      comment(evalMarker(4, OLD_SHA, "GO", 1)),
      comment(reviewMarker(4, HEAD_SHA)),
    ]);
    expect(gate.evals).toBe("stale");
    expect(gate.state).toBe("stale");
  });

  it("marks review stale when the review marker's head_sha is older than the PR's current headRefOid", () => {
    const gate = parseGates(prJson(), [
      comment(evalMarker(4, HEAD_SHA, "GO", 1)),
      comment(reviewMarker(4, OLD_SHA)),
    ]);
    expect(gate.review).toBe("stale");
    expect(gate.state).toBe("stale");
  });

  it("reports both missing and state blocked when there are no marker comments at all", () => {
    const gate = parseGates(prJson(), []);
    expect(gate.review).toBe("missing");
    expect(gate.evals).toBe("missing");
    expect(gate.state).toBe("blocked");
    expect(gate.tier).toBeUndefined();
  });

  it("reports review missing when only an eval marker is present", () => {
    const gate = parseGates(prJson(), [comment(evalMarker(4, HEAD_SHA, "GO", 1))]);
    expect(gate.review).toBe("missing");
    expect(gate.evals).toBe("pass");
    expect(gate.state).toBe("blocked");
  });

  it("reports evals missing when only a review marker is present", () => {
    const gate = parseGates(prJson(), [comment(reviewMarker(4, HEAD_SHA))]);
    expect(gate.evals).toBe("missing");
    expect(gate.review).toBe("present");
    expect(gate.state).toBe("blocked");
  });

  it("ignores markers for a different PR number", () => {
    const gate = parseGates(prJson({ number: 4 }), [
      comment(evalMarker(9, HEAD_SHA, "GO", 1)),
      comment(reviewMarker(9, HEAD_SHA)),
    ]);
    expect(gate.review).toBe("missing");
    expect(gate.evals).toBe("missing");
  });

  it("ignores an unrelated comment body without throwing", () => {
    const gate = parseGates(prJson(), [comment("just a normal review comment, no marker here")]);
    expect(gate.review).toBe("missing");
    expect(gate.evals).toBe("missing");
  });

  it("rejects an eval marker with an out-of-range tier (shell grammar caps tier at [0-2])", () => {
    const gate = parseGates(prJson(), [
      comment(`<!-- coderails-eval-summary ${EVAL_VER} pr=4 head_sha=${HEAD_SHA} result=GO tier=99 -->`),
    ]);
    expect(gate.evals).toBe("missing");
  });

  it("rejects an eval marker with a non-vocabulary result (shell grammar allows only GO|NO-GO)", () => {
    const gate = parseGates(prJson(), [
      comment(`<!-- coderails-eval-summary ${EVAL_VER} pr=4 head_sha=${HEAD_SHA} result=MAYBE tier=1 -->`),
    ]);
    expect(gate.evals).toBe("missing");
  });

  it("rejects an eval marker embedded mid-sentence rather than alone on its own line (shell requires whole-line anchoring)", () => {
    const gate = parseGates(prJson(), [
      comment(`some preamble text ${evalMarker(4, HEAD_SHA, "GO", 1)} trailing junk`),
    ]);
    expect(gate.evals).toBe("missing");
  });

  it("rejects a review marker embedded mid-sentence rather than alone on its own line (shell requires exact line equality)", () => {
    const gate = parseGates(prJson(), [
      comment(`preamble ${reviewMarker(4, HEAD_SHA)} trailing`),
    ]);
    expect(gate.review).toBe("missing");
  });

  it("picks the newest-SHA eval marker when multiple eval markers exist for the PR", () => {
    const gate = parseGates(prJson(), [
      comment(evalMarker(4, OLD_SHA, "GO", 1)),
      comment(evalMarker(4, HEAD_SHA, "GO", 2)),
    ]);
    expect(gate.evals).toBe("pass");
    expect(gate.tier).toBe("2");
  });

  it("degrades gracefully on malformed prJson (not an object), returning missing/blocked rather than throwing", () => {
    const gate = parseGates("not-an-object", []);
    expect(gate.state).toBe("blocked");
    expect(gate.review).toBe("missing");
    expect(gate.evals).toBe("missing");
  });

  it("degrades gracefully on a non-array comments argument passed as unknown[], ignoring non-object entries", () => {
    const gate = parseGates(prJson(), [null as unknown as { body: string }, comment(reviewMarker(4, HEAD_SHA))]);
    expect(gate.review).toBe("present");
  });
});

describe("collectPrGates", () => {
  it("returns an array without throwing against this repo when gh is authenticated", async () => {
    const cfg: DashboardConfig = {
      repos: ["blueman82/coderails"],
      wikiPaths: [],
      buttons: [],
    };
    const gates = await collectPrGates(cfg);
    expect(Array.isArray(gates)).toBe(true);
  });

  it("degrades to a {repo, error} entry rather than throwing when gh cannot authenticate", async () => {
    const cfg: DashboardConfig = {
      repos: ["blueman82/coderails"],
      wikiPaths: [],
      buttons: [],
    };
    const gates = await collectPrGates(cfg, { GH_TOKEN: "garbage-token-that-is-not-valid" });
    expect(Array.isArray(gates)).toBe(true);
    expect(gates.length).toBe(1);
    expect(gates[0]).toMatchObject({ repo: "blueman82/coderails" });
    expect(typeof (gates[0] as unknown as { error: string }).error).toBe("string");
  });

  it("returns an empty array for an empty repos list", async () => {
    const cfg: DashboardConfig = { repos: [], wikiPaths: [], buttons: [] };
    const gates = await collectPrGates(cfg);
    expect(gates).toEqual([]);
  });
});
