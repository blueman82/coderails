import { expect, it } from "vitest";
import { readCodexTracePage } from "../src/lib/collect/sessionTrace";
import { fixture } from "./sessionTraceFixture";

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
