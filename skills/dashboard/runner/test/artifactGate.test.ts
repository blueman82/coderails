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
});
