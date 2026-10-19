import { describe, expect, it } from "vitest";
import { describeNode, nodeAttributes } from "../src/lib/collect/nodeDisplay";

describe("graph node display names", () => {
  it("names fixed, dynamic, and unit nodes while keeping the stable ID", () => {
    expect(describeNode("S-2")?.display).toBe("Initializer [S-2]");
    expect(describeNode("S2.7d[1]")?.jobName).toBe("Freezer");
    expect(describeNode("U3[15]")?.display).toBe("Builder · C-3 [U3[15]]");
    expect(nodeAttributes("U3[15]")).toEqual({ "coderails.node.id": "U3[15]",
      "coderails.node.name": "Builder", "coderails.node.lane_code": "C-3" });
  });

  it("does not name unknown or malformed IDs", () => {
    expect(describeNode("C3")).toBeNull();
    expect(describeNode("S2.7d[bad]")).toBeNull();
    expect(describeNode("U3[0]")).toBeNull();
  });
});
