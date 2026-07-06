import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { parseDashboardConfig } from "../src/config";

const FIXTURE_PATH = join(__dirname, "fixtures", "dashboard-config.json");

describe("parseDashboardConfig", () => {
  it("parses buttons from the shared DashboardConfig fixture into full ButtonDef[]", () => {
    const raw = readFileSync(FIXTURE_PATH, "utf-8");
    const config = parseDashboardConfig(raw);
    expect(config.buttons).toEqual([
      {
        name: "wiki-lint",
        label: "WIKI LINT",
        command: "/coderails:wiki-lint",
        cwd: "/Users/harrison/Github/coderails",
        profile: "standard",
      },
      {
        name: "sync-docs",
        label: "SYNC DOCS",
        command: "/coderails:sync-docs",
        cwd: "/Users/harrison/Github/coderails",
        profile: "read-only",
      },
    ]);
  });

  it("returns an empty button list for malformed JSON rather than throwing", () => {
    const config = parseDashboardConfig("not valid json{{{");
    expect(config.buttons).toEqual([]);
  });

  it("carries inputAllowed through when declared", () => {
    const raw = JSON.stringify({
      buttons: [
        {
          name: "ask",
          label: "ASK",
          command: "/coderails:ask",
          cwd: "/Users/harrison/Github/coderails",
          profile: "standard",
          inputAllowed: true,
        },
      ],
    });
    const config = parseDashboardConfig(raw);
    expect(config.buttons[0].inputAllowed).toBe(true);
  });

  it("drops a bypass-profile button missing the bypassPermissions: true safety declaration", () => {
    const raw = JSON.stringify({
      buttons: [
        {
          name: "danger",
          label: "DANGER",
          command: "/coderails:danger",
          cwd: "/Users/harrison/Github/coderails",
          profile: "bypass",
        },
        {
          name: "danger-ok",
          label: "DANGER OK",
          command: "/coderails:danger-ok",
          cwd: "/Users/harrison/Github/coderails",
          profile: "bypass",
          bypassPermissions: true,
        },
      ],
    });
    const config = parseDashboardConfig(raw);
    expect(config.buttons.map((b) => b.name)).toEqual(["danger-ok"]);
  });

  it("drops a button missing a required field (command) rather than passing it through malformed", () => {
    const raw = JSON.stringify({
      buttons: [
        { name: "broken", label: "BROKEN", cwd: "/x", profile: "standard" },
        {
          name: "ok",
          label: "OK",
          command: "/coderails:ok",
          cwd: "/Users/harrison/Github/coderails",
          profile: "standard",
        },
      ],
    });
    const config = parseDashboardConfig(raw);
    expect(config.buttons.map((b) => b.name)).toEqual(["ok"]);
  });
});
