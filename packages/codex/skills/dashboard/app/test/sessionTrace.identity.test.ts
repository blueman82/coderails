import { expect, it } from "vitest";
import { collectCodexSessionTrace, readCodexTracePage } from "../src/lib/collect/sessionTrace";
import { fixture } from "./sessionTraceFixture";

it("names the native worker from its bound graph job and keeps its child identity", async () => {
  const { deps } = await fixture();
  const page = await readCodexTracePage("parent", null, 30, deps);
  const worker = page.events.find((event) => event.attributes["coderails.actor.id"] === "child-one")!;
  expect(worker.attributes).toMatchObject({ "coderails.actor.id": "child-one", "coderails.actor.name": "Builder",
    "coderails.node.id": "U3[1]" });
  expect(worker.parentSpanId).toBe(page.events.find((event) => event.attributes["coderails.native.call_id"] === "call-one")?.spanId);
});

it("uses a validated native task name when no role or nickname exists", async () => {
  const { deps, parent, child, rows, children, save } = await fixture();
  const call = rows[1].payload as Record<string, unknown>;
  const activity = rows[2].payload as Record<string, unknown>;
  const meta = children[0].payload as Record<string, unknown>;
  const subagent = (meta.source as Record<string, unknown>).subagent as Record<string, unknown>;
  await save(parent, [rows[0], { ...rows[1], payload: { ...call,
    arguments: JSON.stringify({ task_name: "worker_a", message: "Sensitive prompt" }) } },
    { ...rows[2], payload: { ...activity, item: { type: "SubAgentActivity", kind: "started",
      id: "call-one", agent_thread_id: "child-one", agent_path: "/root/worker_a" } } }, rows[3]]);
  await save(child, [{ ...children[0], payload: { ...meta, agent_path: "/root/worker_a",
    source: { subagent: { ...subagent, thread_spawn: { ...(subagent.thread_spawn as object), agent_path: "/root/worker_a" } } } } }, ...children.slice(1)]);
  const page = await readCodexTracePage("parent", null, 30, deps);
  expect(page.events.find((event) => event.attributes["coderails.actor.id"] === "child-one")?.attributes["coderails.actor.name"]).toBe("Worker A");
});

it.each([
  ["Map Scout", "Map Scout"], ["Signal Reader", "Signal Reader"],
  ["North Alpha Beta Gamma", "North Alpha Beta Gamma"], ["One Two Three Four Five", "Worker"],
  ["Map  Scout", "Worker"], ["<img src=x onerror=alert(1)>\n\u0007", "Worker"],
])("checks the recorded native nickname %j while keeping child identity", async (nickname, expected) => {
  const { deps, parent, child, rows, children, save } = await fixture();
  const taskName = "loop_worker_55335b315d_a2";
  const legacy = { type: "event_msg", payload: { item: { type: "CollabAgentToolCall", tool: "spawn_agent",
    status: "completed", id: "legacy", prompt: `CODERAILS_GRAPH_TASK=${taskName}\nSensitive prompt`,
    receiver_thread_ids: ["child-one"], receiver_agents: [{ thread_id: "child-one",
      agent_role: "worker", agent_nickname: nickname }] } } };
  await save(parent, [rows[0], legacy]);
  const meta = children[0].payload as Record<string, unknown>;
  const subagent = (meta.source as Record<string, unknown>).subagent as Record<string, unknown>;
  await save(child, [{ ...children[0], payload: { ...meta, agent_role: "worker", agent_nickname: nickname,
    agent_path: null, source: { subagent: { ...subagent, thread_spawn: { parent_thread_id: "parent",
      depth: 1, agent_role: "worker", agent_nickname: nickname, agent_path: null } } } } }, ...children.slice(1)]);
  const page = await readCodexTracePage("parent", null, 30, deps);
  const worker = page.events.find((event) => event.attributes["coderails.actor.id"] === "child-one")!;
  expect(worker.attributes["coderails.actor.name"]).toBe(expected);
  expect(worker.parentSpanId).toBe(page.events.find((event) =>
    event.attributes["coderails.child.id"] === "child-one" && event.attributes["coderails.actor.kind"] === "orchestrator")?.spanId);
  expect(JSON.stringify(page)).not.toContain("<img");
});

it("decodes a canonical retry attempt without creating a graph parent join", async () => {
  const { deps, parent, child, rows, children, save } = await fixture();
  const taskName = "loop_worker_6c6f6f70_55335b315d_a2";
  const call = rows[1].payload as Record<string, unknown>;
  const activity = rows[2].payload as Record<string, unknown>;
  const childMeta = children[0].payload as Record<string, unknown>;
  const subagent = (childMeta.source as Record<string, unknown>).subagent as Record<string, unknown>;
  await save(parent, [rows[0], { ...rows[1], payload: { ...call, arguments: JSON.stringify({ task_name: taskName, message: "Sensitive prompt" }) } },
    { ...rows[2], payload: { ...activity, item: { type: "SubAgentActivity", kind: "started", id: "call-one", agent_thread_id: "child-one", agent_path: `/root/${taskName}` } } }, rows[3]]);
  await save(child, [{ ...children[0], payload: { ...childMeta, agent_path: `/root/${taskName}`,
    source: { subagent: { ...subagent, thread_spawn: { ...(subagent.thread_spawn as object), agent_path: `/root/${taskName}` } } } } }, ...children.slice(1)]);
  const page = await readCodexTracePage("parent", null, 30, deps);
  const dispatch = page.events.find((event) => event.attributes["coderails.native.call_id"] === "call-one");
  expect(dispatch?.attributes).toMatchObject({ "coderails.loop.id": "loop", "coderails.node.id": "U3[1]", "coderails.attempt": 2 });
  expect(dispatch?.parentSpanId).toBeNull();
  expect(page.events.some((event) => event.name === "graph_node")).toBe(false);
});

it("keeps a legacy retry dispatch and its child without claiming a graph identity", async () => {
  const { deps, parent, child, rows, children, save } = await fixture();
  const taskName = "loop_worker_55335b315d_a2";
  const legacy = { type: "event_msg", payload: { item: { type: "CollabAgentToolCall", tool: "spawn_agent", status: "completed",
    id: "legacy-retry", prompt: `CODERAILS_GRAPH_TASK=${taskName}\nSensitive prompt`, receiver_thread_ids: ["child-one"],
    receiver_agents: [{ thread_id: "child-one", agent_role: "worker", agent_nickname: "Nick" }] } } };
  await save(parent, [rows[0], legacy]);
  const meta = children[0].payload as Record<string, unknown>;
  const subagent = (meta.source as Record<string, unknown>).subagent as Record<string, unknown>;
  await save(child, [{ ...children[0], payload: { ...meta, agent_role: "worker", agent_nickname: "Nick", agent_path: null,
    source: { subagent: { ...subagent, thread_spawn: { parent_thread_id: "parent", depth: 1, agent_role: "worker", agent_nickname: "Nick", agent_path: null } } } } }, ...children.slice(1)]);
  const manifest = await collectCodexSessionTrace("parent", deps);
  const page = await readCodexTracePage("parent", null, 30, deps);
  const dispatch = page.events.find((event) => event.attributes["coderails.child.id"] === "child-one" &&
    event.attributes["coderails.actor.kind"] === "orchestrator");
  const worker = page.events.find((event) => event.attributes["coderails.actor.id"] === "child-one");
  expect(manifest.complete).toBe(true);
  expect(dispatch?.attributes["coderails.child.id"]).toBe("child-one");
  expect(worker?.parentSpanId).toBe(dispatch?.spanId);
  expect(worker?.attributes["coderails.actor.name"]).toBe("Nick");
  for (const event of [dispatch, worker]) {
    expect(event?.attributes["coderails.loop.id"]).toBeUndefined();
    expect(event?.attributes["coderails.node.id"]).toBeUndefined();
    expect(event?.attributes["coderails.attempt"]).toBeUndefined();
  }
  expect(page.events.some((event) => event.name === "graph_node")).toBe(false);
});

it("marks a completed legacy spawn with unsupported task evidence incomplete", async () => {
  const { deps, parent, rows, save } = await fixture();
  const unsupported = { type: "event_msg", payload: { item: { type: "CollabAgentToolCall", tool: "spawn_agent", status: "completed",
    id: "unsupported-legacy", prompt: "CODERAILS_GRAPH_TASK=loop_worker_zz_a2\nSensitive prompt", receiver_thread_ids: ["child-one"],
    receiver_agents: [{ thread_id: "child-one", agent_role: "worker", agent_nickname: "Nick" }] } } };
  await save(parent, [rows[0], unsupported]);
  const manifest = await collectCodexSessionTrace("parent", deps);
  expect(manifest.complete).toBe(false);
  expect(manifest.errors.join(" ")).toMatch(/unsupported legacy spawn/i);
});
