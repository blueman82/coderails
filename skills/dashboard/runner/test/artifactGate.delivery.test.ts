import { dir } from "./artifactGate.fixture";
import { describe, it, expect } from "vitest";
import { writeFileSync } from "node:fs";
import { join } from "node:path";
import { checkArtifact } from "../src/artifactGate.ts";
import type { ExpectedArtifact } from "@coderails/dashboard-lib";

describe("checkArtifact", () => {

  const ctx = { date: "2026-07-06", runId: "abc123", vault: "" };

  // ---- last-marker predicate (defect 3: same-date-append false-green) ----
  // The per-date run log holds MANY runs appended in sequence. A whole-file
  // `contains` check false-passes an ABORTED run whenever an EARLIER run that
  // day already wrote the success marker — the stale line is still in the file.
  // The `last-marker` predicate keys on the LAST terminal marker so the most
  // recent run's outcome wins. These cases pin that behaviour.
  const lastMarker: ExpectedArtifact["predicate"] = {
    kind: "last-marker",
    success: "run=ok",
    failures: ["abort=", "refused="],
  };

  // ---- loop-retro-promotion-weekly last-marker gate (append-log false-green,
  // same defect class as defect 3 above, closed for this routine's own
  // markers: run=ok / delivery=started / abort=) ----
  //
  // loop-retro-promotion-weekly has four terminal states (SKILL.md): (a)
  // dormant predicate-unmet stop (now writes run=ok), (b) delivery completes
  // through merge (writes run=ok after merge), (c) manifest abort on a
  // zero-lesson diff (writes abort=), and (d) delivery enters but dies before
  // merge — e.g. push/review/post-review/post-evals/merge fails (leaves
  // delivery=started, the last thing written at §4 entry, as the final
  // line). (d) is the gap the old `exists` predicate silently false-greened:
  // the log file existed (from a PRIOR successful run's run=ok), so `exists`
  // read PASSED even though the run in progress never finished. This lock
  // uses this routine's own predicate shape, distinct from the docs-sync
  // `lastMarker` const above (whose failures are ["abort=","refused="] and do
  // not include "delivery=started").
  const lrpLastMarker: ExpectedArtifact["predicate"] = {
    kind: "last-marker",
    success: "run=ok",
    failures: ["abort=", "delivery=started"],
  };
  it("does not flag a plain within-vault path as escaping", () => {
    const path = join(dir, "sub", "report.md");
    const artifact: ExpectedArtifact = {
      artifactPath: "{vault}/sub/report.md",
      maxAgeSeconds: 3600,
      predicate: { kind: "exists" },
    };
    // File missing is fine here — only checking that the escape-check itself
    // doesn't misfire and mask the real "does not exist" reason.
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.reason).toMatch(/does not exist/i);
    void path;
  });

  it("loop-retro-promotion: dormant-stop-only log ending in run=ok reads passed (state a)", () => {
    const path = join(dir, "promotion-runs.log");
    writeFileSync(
      path,
      "2026-07-17T09:00:00Z predicate=unmet retros=4 lifecycle=0 decay=0\n2026-07-17T09:00:01Z run=ok\n"
    );
    const artifact: ExpectedArtifact = { artifactPath: path, maxAgeSeconds: 691200, predicate: lrpLastMarker };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(true);
    expect(result.reason).toMatch(/success/i);
  });

  it("loop-retro-promotion: log ending in run=ok after a prior delivery=started reads passed (completed delivery, state b)", () => {
    const path = join(dir, "promotion-runs.log");
    writeFileSync(
      path,
      [
        "2026-07-10T09:00:00Z predicate=met retros=12 lifecycle=1 decay=1",
        "2026-07-10T09:00:01Z delivery=started",
        "2026-07-10T09:05:00Z run=ok",
        "",
      ].join("\n")
    );
    const artifact: ExpectedArtifact = { artifactPath: path, maxAgeSeconds: 691200, predicate: lrpLastMarker };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(true);
    expect(result.reason).toMatch(/success/i);
  });

  // THE CRITICAL (d)-CASE FIXTURE. A prior run finished cleanly (run=ok), then
  // a LATER run enters delivery (delivery=started) and dies before reaching
  // merge — no further terminal marker is ever appended. Under `exists`, the
  // file is present (from the old run=ok) so the gate false-greens the
  // interrupted delivery. Under last-marker, delivery=started is the LAST
  // terminal marker, so the gate must read NOT passed — it must not inherit
  // the stale earlier run=ok.
  it("loop-retro-promotion: log ending in delivery=started (with a prior run=ok) reads NOT passed — interrupted delivery, state d", () => {
    const path = join(dir, "promotion-runs.log");
    writeFileSync(
      path,
      [
        "2026-07-10T09:00:00Z predicate=met retros=12 lifecycle=1 decay=1",
        "2026-07-10T09:05:00Z run=ok",
        "2026-07-17T09:00:00Z predicate=met retros=13 lifecycle=1 decay=1",
        "2026-07-17T09:00:01Z delivery=started",
        "",
      ].join("\n")
    );
    const artifact: ExpectedArtifact = { artifactPath: path, maxAgeSeconds: 691200, predicate: lrpLastMarker };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(false);
    expect(result.reason).toMatch(/failure/i);

    // Discrimination proof (SO-26): the SAME fixture file, read under the OLD
    // `exists` predicate this routine used before this fix, reads PASSED —
    // the false-green this lock closes. If this assertion ever failed (i.e.
    // `exists` also failed on a present file), the "regression" this test
    // locks would not be a regression at all.
    const staleShapeArtifact: ExpectedArtifact = {
      artifactPath: path,
      maxAgeSeconds: 691200,
      predicate: { kind: "exists" },
    };
    const staleResult = checkArtifact(staleShapeArtifact, { ...ctx, vault: dir });
    expect(staleResult.passed).toBe(true);
  });

  // SKILL.md now writes `delivery=started` at §1's predicate=met determination
  // (before §2 Mining), not at §4 Delivery's entry — so it's the fail-safe
  // in-progress marker for the WHOLE met-path (mining + drafting + delivery),
  // not delivery alone. The gate doesn't care where in the routine the marker
  // was written, only that it's the LAST terminal marker in the log — so this
  // fixture (delivery=started immediately after predicate=met, with NO
  // delivery-stage lines at all) proves a death during Mining or Drafting
  // reads RED exactly like a death during Delivery does (state d above).
  it("loop-retro-promotion: log ending in delivery=started right after predicate=met (no delivery steps) reads NOT passed — death during mining/drafting", () => {
    const path = join(dir, "promotion-runs.log");
    writeFileSync(
      path,
      [
        "2026-07-10T09:00:00Z predicate=met retros=12 lifecycle=1 decay=1",
        "2026-07-10T09:05:00Z run=ok",
        "2026-07-17T09:00:00Z predicate=met retros=13 lifecycle=1 decay=1",
        "2026-07-17T09:00:01Z delivery=started",
        "",
      ].join("\n")
    );
    const artifact: ExpectedArtifact = { artifactPath: path, maxAgeSeconds: 691200, predicate: lrpLastMarker };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(false);
    expect(result.reason).toMatch(/failure/i);
  });

  it("loop-retro-promotion: log ending in abort= (with a prior run=ok) reads NOT passed — manifest abort, state c", () => {
    const path = join(dir, "promotion-runs.log");
    writeFileSync(
      path,
      [
        "2026-07-10T09:00:00Z predicate=met retros=12 lifecycle=1 decay=1",
        "2026-07-10T09:05:00Z run=ok",
        "2026-07-17T09:00:00Z predicate=met retros=13 lifecycle=1 decay=1",
        "2026-07-17T09:00:01Z delivery=started",
        "2026-07-17T09:01:00Z abort=empty-diff-zero-lessons",
        "",
      ].join("\n")
    );
    const artifact: ExpectedArtifact = { artifactPath: path, maxAgeSeconds: 691200, predicate: lrpLastMarker };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(false);
    expect(result.reason).toMatch(/failure/i);

    // Discrimination proof (SO-26), mirrored: same fixture under the OLD
    // `exists` predicate reads PASSED — `exists` false-greens this case too.
    const staleShapeArtifact: ExpectedArtifact = {
      artifactPath: path,
      maxAgeSeconds: 691200,
      predicate: { kind: "exists" },
    };
    const staleResult = checkArtifact(staleShapeArtifact, { ...ctx, vault: dir });
    expect(staleResult.passed).toBe(true);
  });
});
