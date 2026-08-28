import assert from "node:assert/strict";
import { test } from "node:test";
import { createRunStore } from "../lib/runs.mjs";

test("Factory stores the exact prompt separately from safe evidence", () => {
  const store = createRunStore();
  store.create({ id: "run-1", projectId: "coderails", provider: "codex", prompt: "Fix the auth timeout" });
  store.appendEvidence({ runId: "run-1", order: 1, type: "message", source: "provider", timestamp: "2026-08-27T10:00:00Z", payload: { text: "secret" } });

  assert.deepEqual(store.snapshot(), {
    runs: [{ id: "run-1", projectId: "coderails", provider: "codex", status: "queued" }],
    selectedRunId: "run-1",
    selectedRun: {
      id: "run-1",
      projectId: "coderails",
      provider: "codex",
      prompt: "Fix the auth timeout",
      status: "queued",
      graph: { state: "unavailable", message: "No progress graph available" },
      evidence: [{ runId: "run-1", order: 1, type: "message", source: "provider", timestamp: "2026-08-27T10:00:00Z", redacted: true, payload: { text: "[redacted]" } }],
    },
  });
});

test("Factory rejects duplicate evidence order within a run", () => {
  const store = createRunStore();
  store.create({ id: "run-1", projectId: "coderails", provider: "claude", prompt: "Do work" });
  store.appendEvidence({ runId: "run-1", order: 1, type: "message", source: "provider", timestamp: "2026-08-27T10:00:00Z", payload: "first" });

  assert.throws(
    () => store.appendEvidence({ runId: "run-1", order: 1, type: "message", source: "provider", timestamp: "2026-08-27T10:00:01Z", payload: "second" }),
    /duplicate evidence order/,
  );
});

test("publishes run status changes for the live Factory view", () => {
  const store = createRunStore();
  const events = [];
  store.subscribe((event) => events.push(event));
  store.create({ id: "run-1", projectId: "coderails", provider: "codex", prompt: "Do work" });

  store.setStatus("run-1", "running");

  assert.deepEqual(events, [{ type: "status", runId: "run-1", status: "running" }]);
});

test("creates a server-owned demo run with a selectable graph and activity", () => {
  const store = createRunStore();
  const run = store.createDemo();
  const snapshot = store.snapshot();

  assert.equal(run.id, "demo-factory-run");
  assert.equal(snapshot.selectedRun.graph.state, "ready");
  assert.equal(snapshot.selectedRun.graph.nodes.length, 3);
  assert.ok(snapshot.selectedRun.evidence.length > 3);
});
