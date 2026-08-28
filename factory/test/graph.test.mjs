import assert from "node:assert/strict";
import { test } from "node:test";
import { parseProgressGraph } from "../lib/graph.mjs";

test("parses the complete named inspector state without exposing a raw graph", () => {
  const graph = parseProgressGraph({
    graph: {
      nodes: {
        plan: {
          name: "Plan work", status: "done", outcome: "done", retry: { attempts: 1, max: 3 }, evidence: ["plan.md"],
          prompt: "Make the plan", activity: [{ at: "2026-08-28T10:00:00Z", message: "Plan accepted" }],
          checks: [{ name: "Tests", outcome: "pass" }], outputs: [{ name: "Plan", value: "plan.md" }],
          attempts: [{ number: 1, outcome: "done", summary: "Plan accepted" }],
        },
        build: { name: "Build change", status: "pending", outcome: "pending", retry: { attempts: 0, max: 3 } },
      },
      edges: [{ from: "plan", to: "build" }],
      joins: { build: { mode: "all", inputs: ["plan"], released: false } },
    },
  });

  assert.deepEqual(graph, {
    state: "ready",
    nodes: [
      {
        id: "plan", name: "Plan work", dependencies: [], join: null, readiness: "waiting", outcome: "done", retries: { attempts: 1, max: 3 },
        prompt: "Make the plan", activity: [{ at: "2026-08-28T10:00:00Z", message: "Plan accepted" }],
        checks: [{ name: "Tests", outcome: "pass" }], outputs: [{ name: "Plan", value: "plan.md" }], attempts: [{ number: 1, outcome: "done", summary: "Plan accepted" }],
      },
      {
        id: "build", name: "Build change", dependencies: ["plan"], join: { mode: "all", released: false }, readiness: "ready", outcome: "pending", retries: { attempts: 0, max: 3 },
        prompt: null, activity: [], checks: [], outputs: [], attempts: [],
      },
    ],
  });
});

test("rejects malformed named inspector fields", () => {
  assert.deepEqual(parseProgressGraph({
    graph: { nodes: { plan: { activity: "not an activity list" } }, edges: [], joins: {} },
  }), { state: "malformed", message: "graph node plan activity must be an array" });
});

test("makes malformed and unavailable progress records visible", () => {
  assert.deepEqual(parseProgressGraph(null), { state: "unavailable", message: "No progress graph available" });
  assert.deepEqual(parseProgressGraph({ graph: { nodes: [] } }), { state: "malformed", message: "graph.nodes must be an object" });
  assert.deepEqual(parseProgressGraph({ graph: { nodes: { plan: null }, edges: [], joins: {} } }), { state: "malformed", message: "graph node plan is invalid" });
});
