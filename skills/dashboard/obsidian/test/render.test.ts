import { describe, it, expect } from "vitest";
import { renderCommandCentre } from "../src/render";
import type { CommandCentreSnapshot } from "../src/render";

function emptySnapshot(): CommandCentreSnapshot {
  return {
    metrics: null,
    activity: [],
    buttons: [],
  };
}

describe("renderCommandCentre — empty state", () => {
  it("renders the shell empty-state hint when no metrics note exists", () => {
    const el = renderCommandCentre(emptySnapshot());
    const hint = el.querySelector(".cc-terminal-hint");
    expect(hint).not.toBeNull();
    expect(hint!.textContent).toContain("dashboard-runs/_metrics.json");
  });

  it("does not render stat cards when metrics is null", () => {
    const el = renderCommandCentre(emptySnapshot());
    expect(el.querySelectorAll(".cc-stat-card").length).toBe(0);
  });

  it("renders an empty-state message in the activity feed when there is no activity", () => {
    const el = renderCommandCentre(emptySnapshot());
    const feed = el.querySelector(".cc-activity-feed");
    expect(feed!.textContent).toContain("no activity yet");
  });
});

describe("renderCommandCentre — metrics", () => {
  it("renders stat cards from a present metrics snapshot", () => {
    const snapshot: CommandCentreSnapshot = {
      metrics: {
        tokenBurnPercent: 38,
        tokenBurnUsed: 760400,
        tokenBurnCap: 2000000,
        openPrs: 3,
        activeSessions: 2,
        hooksFired: 142,
        lintFindings: 3,
        latestMerge: null,
      },
      activity: [],
      buttons: [],
    };
    const el = renderCommandCentre(snapshot);
    const cards = el.querySelectorAll(".cc-stat-card");
    expect(cards.length).toBe(4);
    expect(el.querySelector(".cc-hero-percent")!.textContent).toContain("38%");
  });

  it("renders the latest-merge banner when present", () => {
    const snapshot: CommandCentreSnapshot = {
      metrics: {
        tokenBurnPercent: 10,
        tokenBurnUsed: 1,
        tokenBurnCap: 2,
        openPrs: 0,
        activeSessions: 0,
        hooksFired: 0,
        lintFindings: 0,
        latestMerge: { title: "coderails #5 — task-evals wiring", prCount: 5, testCount: 22, tier: "P0" },
      },
      activity: [],
      buttons: [],
    };
    const el = renderCommandCentre(snapshot);
    const banner = el.querySelector(".cc-merge-banner");
    expect(banner).not.toBeNull();
    expect(banner!.textContent).toContain("coderails #5 — task-evals wiring");
    expect(banner!.textContent).toContain("5 PRS");
    expect(banner!.textContent).toContain("22 TESTS");
  });

  it("omits the latest-merge banner when metrics has no latestMerge", () => {
    const snapshot: CommandCentreSnapshot = {
      metrics: {
        tokenBurnPercent: 10,
        tokenBurnUsed: 1,
        tokenBurnCap: 2,
        openPrs: 0,
        activeSessions: 0,
        hooksFired: 0,
        lintFindings: 0,
        latestMerge: null,
      },
      activity: [],
      buttons: [],
    };
    const el = renderCommandCentre(snapshot);
    expect(el.querySelector(".cc-merge-banner")).toBeNull();
  });
});

describe("renderCommandCentre — activity feed ordering", () => {
  it("renders activity rows newest-first as provided by the snapshot", () => {
    const snapshot: CommandCentreSnapshot = {
      metrics: null,
      activity: [
        { title: "Wiki lint clean", status: "pass", time: "09:14", notePath: "dashboard-runs/2026-07-06-wiki-lint.md" },
        { title: "Morning report ready", status: "pass", time: "07:00", notePath: "dashboard-runs/2026-07-06-am-report.md" },
      ],
      buttons: [],
    };
    const el = renderCommandCentre(snapshot);
    const rows = el.querySelectorAll(".cc-activity-row");
    expect(rows.length).toBe(2);
    expect(rows[0].textContent).toContain("Wiki lint clean");
    expect(rows[1].textContent).toContain("Morning report ready");
  });

  it("links each activity row to its source note", () => {
    const snapshot: CommandCentreSnapshot = {
      metrics: null,
      activity: [
        { title: "Wiki lint clean", status: "pass", time: "09:14", notePath: "dashboard-runs/2026-07-06-wiki-lint.md" },
      ],
      buttons: [],
    };
    const el = renderCommandCentre(snapshot);
    const link = el.querySelector(".cc-activity-row .cc-activity-link");
    expect(link).not.toBeNull();
    expect(link!.getAttribute("data-note-path")).toBe("dashboard-runs/2026-07-06-wiki-lint.md");
  });
});

describe("renderCommandCentre — status chip mapping", () => {
  it.each([
    ["pass", "cc-chip-pass"],
    ["fail", "cc-chip-fail"],
    ["needs-review", "cc-chip-needs-review"],
    ["done", "cc-chip-pass"],
    ["failed", "cc-chip-fail"],
    ["running", "cc-chip-running"],
  ] as const)("maps status %s to chip class %s", (status, chipClass) => {
    const snapshot: CommandCentreSnapshot = {
      metrics: null,
      activity: [{ title: "Run", status, time: "now", notePath: "dashboard-runs/x.md" }],
      buttons: [],
    };
    const el = renderCommandCentre(snapshot);
    const chip = el.querySelector(".cc-status-chip");
    expect(chip!.classList.contains(chipClass)).toBe(true);
  });

  it("falls back to a pending chip for an unrecognised status", () => {
    const snapshot: CommandCentreSnapshot = {
      metrics: null,
      activity: [{ title: "Run", status: "unknown-status", time: "now", notePath: "dashboard-runs/x.md" }],
      buttons: [],
    };
    const el = renderCommandCentre(snapshot);
    const chip = el.querySelector(".cc-status-chip");
    expect(chip!.classList.contains("cc-chip-pending")).toBe(true);
  });

  it("shows an hourglass on a running row and flips away once resolved", () => {
    const running: CommandCentreSnapshot = {
      metrics: null,
      activity: [{ title: "Run", status: "running", time: "now", notePath: "dashboard-runs/x.md" }],
      buttons: [],
    };
    const runningEl = renderCommandCentre(running);
    expect(runningEl.querySelector(".cc-status-chip")!.textContent).toContain("⏳");

    const done: CommandCentreSnapshot = {
      metrics: null,
      activity: [{ title: "Run", status: "done", time: "now", notePath: "dashboard-runs/x.md" }],
      buttons: [],
    };
    const doneEl = renderCommandCentre(done);
    expect(doneEl.querySelector(".cc-status-chip")!.textContent).not.toContain("⏳");
  });
});

describe("renderCommandCentre — command grid", () => {
  it("renders one button per config-declared button, config-driven", () => {
    const snapshot: CommandCentreSnapshot = {
      metrics: null,
      activity: [],
      buttons: [
        { name: "wiki-lint", label: "WIKI LINT", command: "/coderails:wiki-lint", cwd: "/repo", profile: "standard" },
        { name: "sync-docs", label: "SYNC DOCS", command: "/coderails:sync-docs", cwd: "/repo", profile: "read-only" },
      ],
    };
    const el = renderCommandCentre(snapshot);
    const btns = el.querySelectorAll(".cc-cmd-btn");
    expect(btns.length).toBe(2);
    expect(btns[0].textContent).toContain("WIKI LINT");
    expect(btns[0].getAttribute("data-button-name")).toBe("wiki-lint");
  });

  it("renders an empty-state hint in the command grid when no buttons are declared", () => {
    const el = renderCommandCentre(emptySnapshot());
    expect(el.querySelectorAll(".cc-cmd-btn").length).toBe(0);
    expect(el.querySelector(".cc-command-grid")!.textContent).toContain("no commands declared");
  });
});
