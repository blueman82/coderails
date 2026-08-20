import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdtempSync, rmSync, writeFileSync, utimesSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { resolveArtifactPath, checkArtifact } from "../src/artifactGate.ts";
import type { ExpectedArtifact } from "@coderails/dashboard-lib";

let dir: string;

beforeEach(() => {
  dir = mkdtempSync(join(tmpdir(), "artifact-gate-test-"));
});

afterEach(() => {
  rmSync(dir, { recursive: true, force: true });
});

describe("resolveArtifactPath", () => {
  it("substitutes {date}, {runId}, and {vault} tokens", () => {
    const resolved = resolveArtifactPath("{vault}/{date}/{runId}/log.md", {
      date: "2026-07-06",
      runId: "abc123",
      vault: "/some/vault",
    });
    expect(resolved).toBe("/some/vault/2026-07-06/abc123/log.md");
  });

  it("leaves the template unchanged when it has no tokens", () => {
    const resolved = resolveArtifactPath("/fixed/path.md", {
      date: "2026-07-06", runId: "abc123", vault: "/vault",
    });
    expect(resolved).toBe("/fixed/path.md");
  });
});

describe("checkArtifact", () => {
  const ctx = { date: "2026-07-06", runId: "abc123", vault: "" };

  it("passes an 'exists' predicate when the file exists and is fresh", () => {
    const path = join(dir, "report.md");
    writeFileSync(path, "content");
    const artifact: ExpectedArtifact = {
      artifactPath: path,
      maxAgeSeconds: 3600,
      predicate: { kind: "exists" },
    };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(true);
  });

  it("fails an 'exists' predicate when the file is missing", () => {
    const artifact: ExpectedArtifact = {
      artifactPath: join(dir, "missing.md"),
      maxAgeSeconds: 3600,
      predicate: { kind: "exists" },
    };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(false);
    expect(result.reason).toMatch(/does not exist/i);
  });

  it("fails an 'exists' predicate when the file is older than maxAgeSeconds", () => {
    const path = join(dir, "stale.md");
    writeFileSync(path, "content");
    const oldTime = new Date(Date.now() - 10_000_000);
    utimesSync(path, oldTime, oldTime);
    const artifact: ExpectedArtifact = {
      artifactPath: path,
      maxAgeSeconds: 60,
      predicate: { kind: "exists" },
    };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(false);
    expect(result.reason).toMatch(/stale|too old/i);
  });

  it("passes a 'contains' predicate when the marker (with tokens substituted) is present in the file", () => {
    const path = join(dir, "log.md");
    writeFileSync(path, "## [2026-07-06] lint | found 3 issues\n");
    const artifact: ExpectedArtifact = {
      artifactPath: path,
      maxAgeSeconds: 3600,
      predicate: { kind: "contains", marker: "## [{date}] lint" },
    };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(true);
  });

  it("fails a 'contains' predicate when the marker is absent", () => {
    const path = join(dir, "log.md");
    writeFileSync(path, "## [2026-01-01] lint | old entry\n");
    const artifact: ExpectedArtifact = {
      artifactPath: path,
      maxAgeSeconds: 3600,
      predicate: { kind: "contains", marker: "## [{date}] lint" },
    };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(false);
    expect(result.reason).toMatch(/marker/i);
  });

  // These three cases pin the workflow-audit gate's END of the contract only:
  // marker present -> pass, marker absent -> fail, stale -> fail. They are
  // deliberately redundant with the generic `contains` cases above — kept as
  // executable documentation of what this routine's gate does, since the gate
  // is the half a reader is most likely to mis-model.
  //
  // What they do NOT prove, and cannot: zero-is-success itself. `checkArtifact`
  // never parses proposals_written — the `contains` branch is content.includes()
  // and nothing more, so the counter lines in these fixtures are inert (delete
  // them and the tests pass identically). The real invariant — emit the marker
  // ONLY IF the run finished cleanly AND written == attempted, including 0 == 0
  // — lives in the routine's button command prose (examples/dashboard-config.json),
  // an instruction to an LLM run that no unit test here can execute. It is
  // verified by live-fire against the installed routine, not by this file.
  it("passes a workflow-audit run note whose completion marker is present (marker-presence only — see note above)", () => {
    const path = join(dir, "run-2026-07-06.md");
    writeFileSync(
      path,
      "proposals_written: 0\nproposals_attempted: 0\n## [2026-07-06] workflow-audit complete\n"
    );
    const artifact: ExpectedArtifact = {
      artifactPath: path,
      maxAgeSeconds: 691200,
      predicate: { kind: "contains", marker: "## [{date}] workflow-audit complete" },
    };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(true);
  });

  it("fails a 'contains' predicate on a workflow-audit run note that omitted the completion marker (shortfall or crash)", () => {
    const path = join(dir, "run-2026-07-06.md");
    writeFileSync(path, "proposals_written: 2\nproposals_attempted: 3\n");
    const artifact: ExpectedArtifact = {
      artifactPath: path,
      maxAgeSeconds: 691200,
      predicate: { kind: "contains", marker: "## [{date}] workflow-audit complete" },
    };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(false);
    expect(result.reason).toMatch(/marker/i);
  });

  it("fails a 'contains' predicate on a stale workflow-audit run note even with the marker present", () => {
    const path = join(dir, "run-2026-06-20.md");
    writeFileSync(path, "proposals_written: 0\n## [2026-06-20] workflow-audit complete\n");
    const oldTime = new Date(Date.now() - 700_000_000); // > 691200s (8 days)
    utimesSync(path, oldTime, oldTime);
    const artifact: ExpectedArtifact = {
      artifactPath: path,
      maxAgeSeconds: 691200,
      predicate: { kind: "contains", marker: "## [2026-06-20] workflow-audit complete" },
    };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(false);
    expect(result.reason).toMatch(/stale|too old/i);
  });

  it("passes a 'json-field' predicate when the field matches the expected value", () => {
    const path = join(dir, "result.json");
    writeFileSync(path, JSON.stringify({ status: "green" }));
    const artifact: ExpectedArtifact = {
      artifactPath: path,
      maxAgeSeconds: 3600,
      predicate: { kind: "json-field", path: "status", value: "green" },
    };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(true);
  });

  it("fails a 'json-field' predicate when the field does not match", () => {
    const path = join(dir, "result.json");
    writeFileSync(path, JSON.stringify({ status: "red" }));
    const artifact: ExpectedArtifact = {
      artifactPath: path,
      maxAgeSeconds: 3600,
      predicate: { kind: "json-field", path: "status", value: "green" },
    };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(false);
  });

  it("fails a 'json-field' predicate when the file is not valid JSON", () => {
    const path = join(dir, "result.json");
    writeFileSync(path, "not json");
    const artifact: ExpectedArtifact = {
      artifactPath: path,
      maxAgeSeconds: 3600,
      predicate: { kind: "json-field", path: "status", value: "green" },
    };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(false);
  });

  it("negative control: a routine that exits 0 but writes nothing must fail its artifact gate", () => {
    const artifact: ExpectedArtifact = {
      artifactPath: join(dir, "never-written.md"),
      maxAgeSeconds: 3600,
      predicate: { kind: "exists" },
    };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(false);
  });

  // sync-docs-nightly's actual defect shape: an `exists` predicate accepts a
  // log whose run aborted or was refused, as long as it wrote *something*.
  // These two cases pin the `contains`/`run=ok` gate against that shape — an
  // aborted/refused run must fail, and only a run that actually reached
  // `run=ok` may pass. If checkArtifact ignored the marker and only checked
  // presence, both assertions would pass.
  it("fails a 'contains'/'run=ok' predicate on a docs-sync run log that aborted without reaching run=ok", () => {
    const path = join(dir, "run-2026-07-17.log");
    writeFileSync(path, "2026-07-17T10:00:00Z abort=duplicate-work\n2026-07-17T10:00:01Z refused=merge\n");
    const artifact: ExpectedArtifact = {
      artifactPath: path,
      maxAgeSeconds: 129600,
      predicate: { kind: "contains", marker: "run=ok" },
    };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(false);
    expect(result.reason).toMatch(/marker/i);
  });

  it("passes a 'contains'/'run=ok' predicate on a docs-sync run log that reached run=ok", () => {
    const path = join(dir, "run-2026-07-17.log");
    writeFileSync(path, "2026-07-17T10:00:00Z start\n2026-07-17T10:05:00Z run=ok\n");
    const artifact: ExpectedArtifact = {
      artifactPath: path,
      maxAgeSeconds: 129600,
      predicate: { kind: "contains", marker: "run=ok" },
    };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(true);
  });

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

  // THE RED-LOCK — the exact live defect: a green run's run=ok FOLLOWED by a
  // later same-date abort must read NOT-passed. A whole-file contains(run=ok)
  // (what #220 shipped) returns true here — that is the production false-green
  // reproduced live as run 8bedfa1c. This test fails against that implementation.
  it("last-marker: run=ok followed by a later same-date abort reads NOT passed", () => {
    const path = join(dir, "run-2026-07-17.log");
    writeFileSync(
      path,
      [
        "2026-07-17T16:11:28Z run=ok",
        "2026-07-17T16:24:27Z abort=denylisted-doc-drift detail=docs/routines.md",
        "",
      ].join("\n"),
    );
    const artifact: ExpectedArtifact = { artifactPath: path, maxAgeSeconds: 129600, predicate: lastMarker };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(false);
    expect(result.reason).toMatch(/failure/i);
  });

  it("last-marker: run=ok as the last terminal marker (trailing non-marker note after it) reads passed", () => {
    // A successful run may append a trailing non-terminal note AFTER run=ok
    // (observed: note=scope-rationale at 16:18 after run=ok at 16:11). A naive
    // last-LINE check would miss the marker; the last MARKER-SET match must win.
    const path = join(dir, "run-2026-07-17.log");
    writeFileSync(
      path,
      [
        "2026-07-17T16:11:28Z run=ok",
        "2026-07-17T16:18:50Z note=scope-rationale INSTALLATION.md-in-scope",
        "",
      ].join("\n"),
    );
    const artifact: ExpectedArtifact = { artifactPath: path, maxAgeSeconds: 129600, predicate: lastMarker };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(true);
    expect(result.reason).toMatch(/success/i);
  });

  it("last-marker: a refused= as the last terminal marker reads NOT passed", () => {
    const path = join(dir, "run-2026-07-17.log");
    writeFileSync(path, "2026-07-17T10:00:00Z run=ok\n2026-07-17T11:00:00Z refused=post-evals\n");
    const artifact: ExpectedArtifact = { artifactPath: path, maxAgeSeconds: 129600, predicate: lastMarker };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(false);
    expect(result.reason).toMatch(/refused=/);
  });

  it("last-marker: a log with no terminal marker at all reads NOT passed", () => {
    const path = join(dir, "run-2026-07-17.log");
    writeFileSync(path, "2026-07-17T10:00:00Z stage=audit drift-found\n2026-07-17T10:01:00Z stage=branch\n");
    const artifact: ExpectedArtifact = { artifactPath: path, maxAgeSeconds: 129600, predicate: lastMarker };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(false);
    expect(result.reason).toMatch(/no terminal marker/i);
  });

  it("last-marker: green-then-abort-then-green on the same date reads passed (latest run wins)", () => {
    const path = join(dir, "run-2026-07-17.log");
    writeFileSync(
      path,
      [
        "2026-07-17T09:00:00Z run=ok",
        "2026-07-17T12:00:00Z abort=denylisted-doc-drift",
        "2026-07-17T15:00:00Z run=ok",
        "",
      ].join("\n"),
    );
    const artifact: ExpectedArtifact = { artifactPath: path, maxAgeSeconds: 129600, predicate: lastMarker };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(true);
  });

  it("fails a template using {vault} whose ../ traversal resolves outside the vault root", () => {
    const outside = join(dir, "..", "outside-secret.md");
    writeFileSync(outside, "leaked");
    const artifact: ExpectedArtifact = {
      artifactPath: "{vault}/../outside-secret.md",
      maxAgeSeconds: 3600,
      predicate: { kind: "exists" },
    };
    const result = checkArtifact(artifact, { ...ctx, vault: dir });
    expect(result.passed).toBe(false);
    expect(result.reason).toMatch(/escapes/i);
    rmSync(outside, { force: true });
  });

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
