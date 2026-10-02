import { expect, it } from "vitest";
import { fixture } from "./sessionTraceFixture";
import { collectCodexSessionTrace, readCodexTracePage } from "../src/lib/collect/sessionTrace";

it("joins a roleless dispatch to native-null spawn metadata when the child top-level role is absent", async () => {
  const { deps, child, children, save } = await fixture();
  const rolelessChildMeta = { ...(children[0].payload as Record<string, unknown>) };
  delete rolelessChildMeta.agent_role;
  await save(child, [{ ...children[0], payload: rolelessChildMeta }, ...children.slice(1)]);

  const manifest = await collectCodexSessionTrace("parent", deps);
  const page = await readCodexTracePage("parent", null, 30, deps);
  const worker = page.events.find((event) => event.attributes["coderails.actor.id"] === "child-one");
  const dispatch = page.events.find((event) => event.attributes["coderails.native.call_id"] === "call-one");
  expect(manifest.complete).toBe(true);
  expect(worker).toBeDefined();
  expect(worker?.parentSpanId).toBe(dispatch?.spanId);
  expect(worker?.provenance.sourceRef.kind).toBe("codex_child_record");
});
