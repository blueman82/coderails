import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { parseDashboardConfig } from "../src/config";

const FIXTURE_PATH = join(__dirname, "fixtures", "dashboard-config.json");

describe("parseDashboardConfig", () => {
  it("parses buttons from the shared DashboardConfig fixture into ButtonItem[]", () => {
    const raw = readFileSync(FIXTURE_PATH, "utf-8");
    const config = parseDashboardConfig(raw);
    expect(config.buttons).toEqual([
      { name: "wiki-lint", label: "WIKI LINT" },
      { name: "sync-docs", label: "SYNC DOCS" },
    ]);
  });

  it("returns an empty button list for malformed JSON rather than throwing", () => {
    const config = parseDashboardConfig("not valid json{{{");
    expect(config.buttons).toEqual([]);
  });
});
