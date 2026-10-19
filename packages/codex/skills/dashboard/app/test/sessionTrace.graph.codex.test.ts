import { mkdir, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { fixture } from "./sessionTraceFixture";
import { readCodexTracePage } from "../src/lib/collect/sessionTrace";

describe("Codex graph node names", () => {
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
