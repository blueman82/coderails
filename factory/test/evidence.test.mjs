import assert from "node:assert/strict";
import { test } from "node:test";
import { safeEvidence } from "../lib/evidence.mjs";

test("keeps readable provider evidence and masks only clear credential values", () => {
  assert.deepEqual(safeEvidence({
    runId: "run-1", order: 4, type: "tool_result", source: "provider", timestamp: "2026-08-27T10:00:00Z",
    payload: "token=abc123\nAuthorization: Bearer top-secret\nopened /private",
  }), {
    runId: "run-1", order: 4, type: "tool_result", source: "provider", timestamp: "2026-08-27T10:00:00Z", redacted: true,
    payload: "token=[credential masked]\nAuthorization: Bearer [credential masked]\nopened /private",
  });
});

test("does not claim masking when no credential form was present", () => {
  const evidence = safeEvidence({
    runId: "run-1", order: 5, type: "tool_result", source: "provider", timestamp: "2026-08-27T10:00:00Z",
    payload: "completed the focused check",
  });
  assert.equal(evidence.redacted, false);
  assert.equal(evidence.payload, "completed the focused check");
});

test("masks JSON-formatted credential values without hiding other fields", () => {
  const evidence = safeEvidence({
    runId: "run-1", order: 6, type: "tool_result", source: "provider", timestamp: "2026-08-27T10:00:00Z",
    payload: { token: "sentinel-token", message: "keep this" },
  });
  assert.equal(evidence.redacted, true);
  assert.match(evidence.payload, /"token":"\[credential masked\]"/);
  assert.match(evidence.payload, /"message":"keep this"/);
  assert.doesNotMatch(evidence.payload, /sentinel-token/);
});
