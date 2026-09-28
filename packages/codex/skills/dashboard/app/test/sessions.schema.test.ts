import { makeTmpBase } from "./sessions.fixture";
import { describe, it, expect } from "vitest";
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { collectLoops } from "../src/lib/collect/sessions";

describe("collectLoops schema ownership", () => {
  it("ignores missing, legacy, future, string and malformed schema records", () => {
    const base = makeTmpBase();
    for (const [index, schema] of [undefined, 1, 2, 4, "3", null].entries()) {
      const dir = join(base, "project", `session-${index}`);
      mkdirSync(dir, { recursive: true });
      writeFileSync(join(dir, "progress.json"), JSON.stringify({ schema_version: schema, status: "complete", work_units: { one: { status: "done" } } }));
    }
    expect(collectLoops(base)).toEqual([]);
  });

  it("counts declared work units independently of graph node success", () => {
    const base = makeTmpBase();
    const dir = join(base, "project", "session");
    mkdirSync(dir, { recursive: true });
    writeFileSync(join(dir, "progress.json"), JSON.stringify({ schema_version: 3, status: "in-progress", work_units: { one: { status: "pending" } }, graph: { nodes: { "U3[1]": { status: "done" }, "U4[1]": { status: "done" } } } }));
    expect(collectLoops(base)[0]).toMatchObject({ workUnitsDone: 0, workUnitsTotal: 1 });
  });
});
