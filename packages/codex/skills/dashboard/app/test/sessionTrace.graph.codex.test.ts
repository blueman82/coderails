import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { fixture } from "./sessionTraceFixture";
import { readCodexTracePage } from "../src/lib/collect/sessionTrace";
import { nativeEvent, type Dispatch, type NativeSource, type Row } from "../src/lib/collect/codexTraceNative";

describe("Codex graph node names", () => {
  it("names a native graph dispatch from its canonical task identity", () => {
    const row: Row = { type: "response_item", timestamp: "2026-09-28T12:00:00Z",
      payload: { type: "function_call", name: "spawn_agent", call_id: "call-one", arguments: "{}" } };
    const source: NativeSource = { path: "parent", id: "parent", text: "", rows: [row], ordinals: [0],
      fingerprint: "", cursor: "", errors: [] };
    const dispatch: Dispatch = { callId: "call-one",
      task: `loop_worker_${Buffer.from("loop").toString("hex")}_${Buffer.from("U3[1]").toString("hex")}`,
      childId: "child-one", nickname: null, path: null, role: null, ordinal: 0 };
    const event = nativeEvent("parent", source, 0, row, "orchestrator", null, dispatch, null);
    expect(event.attributes).toMatchObject({ "coderails.node.id": "U3[1]",
      "coderails.node.name": "Builder", "coderails.node.lane_code": "A-1" });
  });

  it("keeps readable names and lane codes on graph records without replacing node IDs", async () => {
    const { deps } = await fixture();
    deps.graphRoot = join(deps.cacheRoot, "graph-state");
    await mkdir(deps.graphRoot, { recursive: true });
    const progress = {
      schema_version: 3,
      session_id: "parent",
      loop_id: "loop",
      graph: {
        hard_stop: { node: "U3[1]", reason: "Synthetic reason" },
        nodes: {
          "U3[1]": {
            retry: { attempts: 1 },
            evidence: [{ kind: "codex_agent", attempt: 1, wave_id: "wave-1", spawn_call_id: "call-one",
              agent_thread_id: "child-one", task_complete_turn_id: "turn-one" }],
          },
        },
      },
    };
    await writeFile(join(deps.graphRoot, "progress.json"), JSON.stringify(progress));

    const page = await readCodexTracePage("parent", null, 50, deps);
    for (const name of ["graph_node", "graph_retry", "graph_evidence", "graph_hard_stop"]) {
      const event = page.events.find((item) => item.name === name);
      expect(event?.attributes).toMatchObject({
        "coderails.node.id": "U3[1]",
        "coderails.node.name": "Builder",
        "coderails.node.lane_code": "A-1",
      });
    }
  });
});
