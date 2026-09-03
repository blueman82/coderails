import assert from "node:assert/strict";
import { test } from "node:test";
import { activityLines, cycleTheme, inspectorNode, inspectorSections, moveSelectedNode, nodeSelector, selectedNodeId, shouldShowInspector } from "../public/ui.js";

const graph = {
  state: "ready",
  nodes: [
    { id: "plan", name: "Plan", outcome: "done", readiness: "waiting", dependencies: [], join: null, retries: { attempts: 0, max: 1 }, prompt: null, activity: [], checks: [], outputs: [], attempts: [] },
    { id: "review", name: "Review", outcome: "running", readiness: "active", dependencies: ["plan"], join: { mode: "all", released: true }, retries: { attempts: 1, max: 3 }, prompt: "Review it", activity: [{ at: "2026-08-28T10:00:00Z", message: "Started" }], checks: [{ name: "Tests", outcome: "pass" }], outputs: [{ name: "Report", value: "review.md" }], attempts: [{ number: 1, outcome: "running", summary: "Started" }] },
  ],
};

test("selects an active node and exposes its evidence", () => {
  assert.equal(selectedNodeId(graph), "review");
  assert.deepEqual(inspectorNode(graph, "review"), graph.nodes[1]);
  assert.equal(inspectorNode(graph, "missing"), null);
});

test("names every inspector field and orders activity chronologically", () => {
  assert.deepEqual(inspectorSections(graph.nodes[1]), [
    ["Dependencies", "plan"], ["Join", "all · released"], ["Readiness", "active"], ["Outcome", "running"], ["Retries", "1/3"],
    ["Prompt", "Review it"], ["Activity", "10:00:00 Started"], ["Checks", "Tests: pass"], ["Outputs", "Report: review.md"], ["Attempt history", "#1 running: Started"],
  ]);
});

test("moves selection with either graph arrow key", () => {
  assert.equal(moveSelectedNode(graph, "plan", "ArrowRight"), "review");
  assert.equal(moveSelectedNode(graph, "plan", "ArrowLeft"), "review");
});

test("keeps the inspector closed after a close action", () => {
  assert.equal(shouldShowInspector(graph, "review", false), false);
  assert.equal(shouldShowInspector(graph, "review", true), true);
});

test("uses the selected node id to restore focus after closing", () => {
  assert.equal(nodeSelector("review"), '[data-node-id="review"]');
});

test("cycles the persisted display theme", () => {
  assert.equal(cycleTheme("system"), "light");
  assert.equal(cycleTheme("light"), "dark");
  assert.equal(cycleTheme("dark"), "system");
});

test("formats visible activity and notes only actual masking", () => {
  assert.deepEqual(activityLines([
    { timestamp: "2026-08-27T10:00:00Z", source: "provider", type: "provider_stdout", payload: "working", redacted: false },
    { timestamp: "2026-08-27T10:00:01Z", source: "provider", type: "provider_stdout", payload: "token=[credential masked]", redacted: true },
  ]), ["10:00:00 provider provider_stdout: working", "10:00:01 provider provider_stdout: token=[credential masked] (credential masked)"]);
  assert.deepEqual(activityLines([]), ["Waiting for Factory activity…"]);
});
