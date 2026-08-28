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
      graph: { state: "waiting", message: "Waiting for the native Coderails graph…" },
      evidence: [{ runId: "run-1", order: 1, type: "message", source: "provider", timestamp: "2026-08-27T10:00:00Z", redacted: false, payload: '{"text":"secret"}' }],
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

test("updates a run only from its observed native progress record", () => {
  const store = createRunStore();
  store.create({ id: "run-1", projectId: "coderails", provider: "codex", prompt: "test" });
  store.setProgress("run-1", { graph: { nodes: { check: { status: "running" } }, edges: [], joins: {} } });
  assert.equal(store.snapshot().selectedRun.graph.state, "ready");
  assert.equal(store.snapshot().selectedRun.graph.nodes[0].id, "check");
});
