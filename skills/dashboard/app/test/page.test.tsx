import { describe, it, expect, vi } from "vitest";
import type { DashboardConfig } from "../src/lib/config";

// Seam test for page.tsx's server-side wiring: Home() must feed
// visibleButtons(config) into DeckButton[] props, not config.buttons
// directly. Mocking loadConfig (not visibleButtons — importActual keeps
// the real filter) means a regression that reverts page.tsx:31 back to
// `config.buttons.map(...)` fails this test even though config.test.ts's
// visibleButtons unit tests stay green.
vi.mock("@/lib/runlog", () => ({
  getRunToken: () => "test-token",
}));

vi.mock("@/lib/config", async () => {
  const actual = await vi.importActual<typeof import("../src/lib/config")>(
    "../src/lib/config"
  );
  const config: DashboardConfig = {
    repos: [],
    wikiPaths: [],
    memoryPaths: [],
    buttons: [
      {
        name: "visible-button",
        label: "VISIBLE",
        command: "/coderails:visible",
        cwd: "/tmp",
        profile: "standard",
      },
      {
        name: "hidden-button",
        label: "HIDDEN",
        command: "/coderails:hidden",
        cwd: "/tmp",
        profile: "standard",
        hidden: true,
      },
    ],
  };
  return {
    ...actual,
    loadConfig: () => config,
  };
});

describe("Home", () => {
  it("feeds visibleButtons(config) into DashboardApp's buttons prop, excluding hidden buttons", async () => {
    const { default: Home } = await import("../src/app/page");
    const element = Home();
    const names = element.props.buttons.map(
      (b: { name: string }) => b.name
    );
    expect(names).toEqual(["visible-button"]);
  });
});
