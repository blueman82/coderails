"use strict";
var __defProp = Object.defineProperty;
var __getOwnPropDesc = Object.getOwnPropertyDescriptor;
var __getOwnPropNames = Object.getOwnPropertyNames;
var __hasOwnProp = Object.prototype.hasOwnProperty;
var __export = (target, all) => {
  for (var name in all)
    __defProp(target, name, { get: all[name], enumerable: true });
};
var __copyProps = (to, from, except, desc) => {
  if (from && typeof from === "object" || typeof from === "function") {
    for (let key of __getOwnPropNames(from))
      if (!__hasOwnProp.call(to, key) && key !== except)
        __defProp(to, key, { get: () => from[key], enumerable: !(desc = __getOwnPropDesc(from, key)) || desc.enumerable });
  }
  return to;
};
var __toCommonJS = (mod) => __copyProps(__defProp({}, "__esModule", { value: true }), mod);

// src/main.ts
var main_exports = {};
__export(main_exports, {
  default: () => CommandCentrePlugin
});
module.exports = __toCommonJS(main_exports);
var import_obsidian = require("obsidian");
var import_node_fs = require("node:fs");
var import_node_os = require("node:os");
var import_node_path = require("node:path");

// src/render.ts
var CHIP_CLASS_BY_STATUS = {
  pass: "cc-chip-pass",
  fail: "cc-chip-fail",
  "needs-review": "cc-chip-needs-review"
};
function chipClassFor(status) {
  return CHIP_CLASS_BY_STATUS[status] ?? "cc-chip-pending";
}
function el(tag, className, text) {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== void 0) node.textContent = text;
  return node;
}
function renderMetricsPanel(container, metrics) {
  if (!metrics) {
    const hint = el(
      "div",
      "cc-terminal-hint",
      "no dashboard-runs/_metrics.json in this vault \u2014 run PULL METRICS to populate it"
    );
    container.appendChild(hint);
    return;
  }
  const hero = el("div", "cc-hero-panel");
  hero.appendChild(el("div", "cc-hero-percent", `${metrics.tokenBurnPercent}%`));
  hero.appendChild(
    el(
      "div",
      "cc-hero-gauge",
      `${metrics.tokenBurnUsed.toLocaleString()} / ${metrics.tokenBurnCap.toLocaleString()}`
    )
  );
  container.appendChild(hero);
  const grid = el("div", "cc-stat-grid");
  const stats = [
    ["OPEN PRS", metrics.openPrs],
    ["ACTIVE SESSIONS", metrics.activeSessions],
    ["HOOKS FIRED", metrics.hooksFired],
    ["LINT FINDINGS", metrics.lintFindings]
  ];
  for (const [label, value] of stats) {
    const card = el("div", "cc-stat-card");
    card.appendChild(el("div", "cc-stat-label", label));
    card.appendChild(el("div", "cc-stat-num", String(value)));
    grid.appendChild(card);
  }
  container.appendChild(grid);
  if (metrics.latestMerge) {
    const merge = metrics.latestMerge;
    const banner = el("div", "cc-merge-banner");
    banner.appendChild(el("div", "cc-merge-title", merge.title));
    banner.appendChild(
      el(
        "div",
        "cc-merge-stats",
        `${merge.prCount} PRS ${merge.testCount} TESTS TIER ${merge.tier}`
      )
    );
    container.appendChild(banner);
  }
}
function renderCommandGrid(container, buttons) {
  const grid = el("div", "cc-command-grid");
  if (buttons.length === 0) {
    grid.appendChild(el("div", "cc-command-grid-empty", "no commands declared \u2014 add buttons[] to ~/.claude/coderails-dashboard.json"));
  } else {
    for (const button of buttons) {
      const btn = el("button", "cc-cmd-btn", button.label);
      btn.setAttribute("data-button-name", button.name);
      grid.appendChild(btn);
    }
  }
  container.appendChild(grid);
}
function renderActivityFeed(container, activity) {
  const feed = el("div", "cc-activity-feed");
  if (activity.length === 0) {
    feed.appendChild(el("div", "cc-activity-empty", "no activity yet"));
  } else {
    for (const item of activity) {
      const row = el("div", "cc-activity-row");
      const chip = el("span", `cc-status-chip ${chipClassFor(item.status)}`, item.status);
      const text = el("span", "cc-activity-text", item.title);
      const link = el("a", "cc-activity-link", item.notePath);
      link.setAttribute("data-note-path", item.notePath);
      const time = el("span", "cc-activity-time", item.time);
      row.appendChild(chip);
      row.appendChild(text);
      row.appendChild(link);
      row.appendChild(time);
      feed.appendChild(row);
    }
  }
  container.appendChild(feed);
}
function renderCommandCentre(snapshot) {
  const root = el("div", "cc-root");
  const header = el("div", "cc-header");
  header.appendChild(el("span", "cc-header-glyph", "\u2301"));
  header.appendChild(el("span", "cc-header-title", "AGENTIC OS \xB7 CODERAILS"));
  header.appendChild(el("span", "cc-live-badge", "LIVE"));
  root.appendChild(header);
  renderMetricsPanel(root, snapshot.metrics);
  const commandsLabel = el("div", "cc-section-label", "COMMANDS");
  root.appendChild(commandsLabel);
  renderCommandGrid(root, snapshot.buttons);
  const activityLabel = el("div", "cc-section-label", "ACTIVITY FEED");
  root.appendChild(activityLabel);
  renderActivityFeed(root, snapshot.activity);
  const footer = el("div", "cc-footer");
  footer.appendChild(el("span", "cc-footer-text", "runner online"));
  footer.appendChild(el("span", "cc-cursor-block"));
  root.appendChild(footer);
  return root;
}

// src/config.ts
function parseDashboardConfig(raw) {
  try {
    const data = JSON.parse(raw);
    if (!Array.isArray(data.buttons)) return { buttons: [] };
    const buttons = [];
    for (const button of data.buttons) {
      if (typeof button.name === "string" && typeof button.label === "string") {
        buttons.push({ name: button.name, label: button.label });
      }
    }
    return { buttons };
  } catch {
    return { buttons: [] };
  }
}

// src/main.ts
var DASHBOARD_RUNS_FOLDER = "dashboard-runs";
var METRICS_NOTE_PATH = `${DASHBOARD_RUNS_FOLDER}/_metrics.json`;
var DASHBOARD_CONFIG_PATH = (0, import_node_path.join)((0, import_node_os.homedir)(), ".claude", "coderails-dashboard.json");
function firstBodyLine(content) {
  const withoutFrontmatter = content.replace(/^---\n[\s\S]*?\n---\n/, "");
  const line = withoutFrontmatter.split("\n").map((l) => l.trim()).find((l) => l.length > 0);
  return line ?? "";
}
function formatTime(mtimeMs) {
  return new Date(mtimeMs).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
var CommandCentrePlugin = class extends import_obsidian.Plugin {
  async onload() {
    this.registerMarkdownCodeBlockProcessor(
      "agentic-os",
      async (_source, el2, _ctx) => {
        const snapshot = await this.buildSnapshot();
        el2.appendChild(renderCommandCentre(snapshot));
      }
    );
  }
  async buildSnapshot() {
    const [metrics, activity] = await Promise.all([this.readMetrics(), this.readActivity()]);
    return {
      metrics,
      activity,
      buttons: this.readButtons()
    };
  }
  async readMetrics() {
    const file = this.app.vault.getAbstractFileByPath(METRICS_NOTE_PATH);
    if (!(file instanceof import_obsidian.TFile)) return null;
    try {
      const content = await this.app.vault.cachedRead(file);
      return JSON.parse(content);
    } catch {
      return null;
    }
  }
  async readActivity() {
    const folder = this.app.vault.getAbstractFileByPath(DASHBOARD_RUNS_FOLDER);
    if (!(folder instanceof import_obsidian.TFolder)) return [];
    const files = folder.children.filter(
      (child) => child instanceof import_obsidian.TFile && child.extension === "md"
    );
    const entries = await Promise.all(
      files.map(async (file) => {
        const cache = this.app.metadataCache.getFileCache(file);
        const status = cache?.frontmatter?.status ?? "pending";
        const content = await this.app.vault.cachedRead(file);
        return {
          item: {
            title: firstBodyLine(content) || file.basename,
            status,
            time: formatTime(file.stat.mtime),
            notePath: file.path
          },
          mtime: file.stat.mtime
        };
      })
    );
    entries.sort((a, b) => b.mtime - a.mtime);
    return entries.map((e) => e.item);
  }
  readButtons() {
    try {
      const raw = (0, import_node_fs.readFileSync)(DASHBOARD_CONFIG_PATH, "utf-8");
      return parseDashboardConfig(raw).buttons;
    } catch {
      return [];
    }
  }
};
