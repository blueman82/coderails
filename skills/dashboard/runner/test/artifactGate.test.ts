import { describe, it, expect } from "vitest";
import { resolveArtifactPath } from "../src/artifactGate.ts";

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
