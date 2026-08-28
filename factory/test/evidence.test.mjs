import assert from "node:assert/strict";
import { test } from "node:test";
import { safeEvidence } from "../lib/evidence.mjs";

test("keeps safe evidence structure and metadata while redacting provider leaves", () => {
  assert.deepEqual(safeEvidence({
    runId: "run-1", order: 4, type: "tool_result", source: "provider", timestamp: "2026-08-27T10:00:00Z",
    payload: { token: "abc", details: ["secret", { path: "/private" }] },
  }), {
    runId: "run-1", order: 4, type: "tool_result", source: "provider", timestamp: "2026-08-27T10:00:00Z", redacted: true,
    payload: { token: "[redacted]", details: ["[redacted]", { path: "[redacted]" }] },
  });
});
