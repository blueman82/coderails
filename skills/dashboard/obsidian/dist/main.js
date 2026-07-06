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
var import_node_child_process = require("node:child_process");
var import_node_fs = require("node:fs");
var import_node_crypto = require("node:crypto");
var import_node_os = require("node:os");
var import_node_path = require("node:path");

// src/render.ts
var CHIP_CLASS_BY_STATUS = {
  pass: "cc-chip-pass",
  fail: "cc-chip-fail",
  "needs-review": "cc-chip-needs-review",
  // "done"/"failed"/"running" are the run-note frontmatter statuses a
  // Task 13 button press writes (see exec.ts) — an unresolved run reads as
  // "running" until execFile's callback flips the note to done/failed.
  done: "cc-chip-pass",
  failed: "cc-chip-fail",
  running: "cc-chip-running"
};
function chipClassFor(status) {
  return CHIP_CLASS_BY_STATUS[status] ?? "cc-chip-pending";
}
function chipTextFor(status) {
  return status === "running" ? "\u23F3" : status;
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
      const item = el("div", "cc-cmd-item");
      const btn = el("button", "cc-cmd-btn", button.label);
      btn.setAttribute("data-button-name", button.name);
      item.appendChild(btn);
      if (button.inputAllowed) {
        const input = document.createElement("input");
        input.className = "cc-cmd-input";
        input.type = "text";
        input.placeholder = "input\u2026";
        input.setAttribute("data-button-name", button.name);
        item.appendChild(input);
        const error = el("span", "cc-cmd-input-error");
        error.setAttribute("data-button-name", button.name);
        item.appendChild(error);
      }
      grid.appendChild(item);
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
      const chip = el("span", `cc-status-chip ${chipClassFor(item.status)}`, chipTextFor(item.status));
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
function renderErrorRow(feed, message) {
  const row = el("div", "cc-activity-row-error", message);
  feed.insertBefore(row, feed.firstChild);
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
var PERMISSION_PROFILES = ["read-only", "standard", "bypass"];
function isValidButton(button) {
  return typeof button.name === "string" && typeof button.label === "string" && typeof button.command === "string" && typeof button.cwd === "string" && typeof button.profile === "string" && PERMISSION_PROFILES.includes(button.profile) && (button.inputAllowed === void 0 || typeof button.inputAllowed === "boolean") && // Same safety declaration the app's loadConfig requires (skills/dashboard/app/src/lib/config.ts):
  // a "bypass" profile button must explicitly opt in via bypassPermissions: true in the JSON,
  // independent of whatever buildArgv itself does with the profile.
  (button.profile !== "bypass" || button.bypassPermissions === true);
}
function parseDashboardConfig(raw) {
  try {
    const data = JSON.parse(raw);
    if (!Array.isArray(data.buttons)) return { buttons: [] };
    const buttons = [];
    for (const button of data.buttons) {
      if (!isValidButton(button)) continue;
      buttons.push({
        name: button.name,
        label: button.label,
        command: button.command,
        cwd: button.cwd,
        profile: button.profile,
        ...button.inputAllowed !== void 0 ? { inputAllowed: button.inputAllowed } : {}
      });
    }
    return { buttons };
  } catch {
    return { buttons: [] };
  }
}

// ../app/src/lib/argv.ts
var READ_ONLY_ALLOWED_TOOLS = ["Read", "Grep", "Glob"];
function buildArgv(btn, input) {
  const argv = ["-p", btn.command];
  if (btn.profile === "read-only") {
    argv.push("--allowedTools", ...READ_ONLY_ALLOWED_TOOLS);
  } else if (btn.profile === "bypass") {
    argv.push("--dangerously-skip-permissions");
  }
  if (input !== void 0) {
    if (input.startsWith("-")) {
      throw new Error(`buildArgv: input must not start with '-' (got: ${input})`);
    }
    argv.push("--", input);
  }
  return argv;
}

// src/exec.ts
var QUEUE_DIR = "queue";
var RUNS_FOLDER = "dashboard-runs";
function isoDate(ms) {
  return new Date(ms).toISOString().slice(0, 10);
}
function runNotePath(button, requestedAt) {
  return `${RUNS_FOLDER}/${isoDate(requestedAt)}-${button}.md`;
}
function runningFrontmatter(button, profile, startedAt) {
  return [
    "---",
    "status: running",
    `button: ${button}`,
    `profile: ${profile}`,
    `startedAt: ${new Date(startedAt).toISOString()}`,
    "---",
    "",
    `Running \`${button}\`...`,
    ""
  ].join("\n");
}
function finalFrontmatter(button, profile, startedAt, endedAt, exitCode, output) {
  const status = exitCode === 0 ? "done" : "failed";
  return [
    "---",
    `status: ${status}`,
    `button: ${button}`,
    `profile: ${profile}`,
    `startedAt: ${new Date(startedAt).toISOString()}`,
    `endedAt: ${new Date(endedAt).toISOString()}`,
    `exitCode: ${exitCode}`,
    `duration: ${endedAt - startedAt}ms`,
    "---",
    "",
    "```",
    output,
    "```",
    ""
  ].join("\n");
}
async function pressButton(deps, buttons, name, input) {
  const button = buttons.find((b) => b.name === name);
  if (!button) {
    return { ok: false, reason: "undeclared" };
  }
  if (input !== void 0 && input.startsWith("-")) {
    return { ok: false, reason: "invalid-input" };
  }
  if (deps.findUnresolvedRun(button.name)) {
    return { ok: false, reason: "unresolved" };
  }
  const argv = buildArgv(button, input);
  const runId = deps.randomRunId();
  const requestedAt = deps.now();
  const intent = {
    button: button.name,
    ...input !== void 0 ? { input } : {},
    requestedAt,
    source: "obsidian"
  };
  deps.mkdirIntentDir(QUEUE_DIR);
  deps.writeIntentFile(`${QUEUE_DIR}/${runId}.json`, JSON.stringify(intent));
  const notePath = runNotePath(button.name, requestedAt);
  await deps.createRunNote(notePath, runningFrontmatter(button.name, button.profile, requestedAt));
  await new Promise((resolve) => {
    deps.execFile("claude", argv, { cwd: button.cwd }, (error, stdout, stderr) => {
      const endedAt = deps.now();
      const errorCode = error?.code;
      const exitCode = !error ? 0 : typeof errorCode === "number" ? errorCode : 1;
      void deps.modifyRunNote(
        notePath,
        finalFrontmatter(button.name, button.profile, requestedAt, endedAt, exitCode, stdout + stderr)
      ).finally(resolve);
    });
  });
  return { ok: true, runId, notePath };
}

// src/main.ts
var DASHBOARD_RUNS_FOLDER = "dashboard-runs";
var METRICS_NOTE_PATH = `${DASHBOARD_RUNS_FOLDER}/_metrics.json`;
var DASHBOARD_CONFIG_PATH = (0, import_node_path.join)((0, import_node_os.homedir)(), ".claude", "coderails-dashboard.json");
var DASHBOARD_DIR = (0, import_node_path.join)((0, import_node_os.homedir)(), ".claude", "coderails-dashboard");
var QUEUE_DIR2 = (0, import_node_path.join)(DASHBOARD_DIR, "queue");
function firstBodyLine(content) {
  const withoutFrontmatter = content.replace(/^---\n[\s\S]*?\n---\n/, "");
  const line = withoutFrontmatter.split("\n").map((l) => l.trim()).find((l) => l.length > 0);
  return line ?? "";
}
function formatTime(mtimeMs) {
  return new Date(mtimeMs).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}
var CommandCentrePlugin = class extends import_obsidian.Plugin {
  constructor() {
    super(...arguments);
    // Live containers for every rendered ```agentic-os``` block, so a vault
    // "modify" event under dashboard-runs/ (a run note flipping from running
    // to done/failed — see exec.ts) can re-render each one in place. Obsidian
    // calls the code-block processor again on its own note-reload path, but
    // NOT when a note is edited by code rather than by the user in that pane
    // — this registration is what makes the feed flip without the user
    // having to reopen the note.
    this.containers = /* @__PURE__ */ new Set();
  }
  async onload() {
    this.registerMarkdownCodeBlockProcessor(
      "agentic-os",
      async (_source, el2, ctx) => {
        await this.renderInto(el2);
        this.containers.add(el2);
        const child = new import_obsidian.MarkdownRenderChild(el2);
        child.register(() => this.containers.delete(el2));
        ctx.addChild(child);
      }
    );
    this.registerEvent(
      this.app.vault.on("modify", (file) => {
        if (file instanceof import_obsidian.TFile && file.path.startsWith(`${DASHBOARD_RUNS_FOLDER}/`)) {
          void this.rerenderAll();
        }
      })
    );
  }
  async rerenderAll() {
    for (const container of this.containers) {
      container.empty();
      await this.renderInto(container);
    }
  }
  async renderInto(container) {
    const snapshot = await this.buildSnapshot();
    const root = renderCommandCentre(snapshot);
    container.appendChild(root);
    this.wireButtons(root, snapshot.buttons);
  }
  wireButtons(root, buttons) {
    const feed = root.querySelector(".cc-activity-feed");
    root.querySelectorAll(".cc-cmd-btn").forEach((btn) => {
      const name = btn.getAttribute("data-button-name");
      if (!name) return;
      this.registerDomEvent(btn, "click", () => {
        void this.handlePress(root, feed, buttons, name);
      });
    });
  }
  async handlePress(root, feed, buttons, name) {
    const input = root.querySelector(`.cc-cmd-input[data-button-name="${name}"]`);
    const errorText = root.querySelector(`.cc-cmd-input-error[data-button-name="${name}"]`);
    const rawInput = input?.value.trim();
    const value = rawInput ? rawInput : void 0;
    if (errorText) errorText.textContent = "";
    if (value !== void 0 && value.startsWith("-")) {
      if (errorText) errorText.textContent = "input must not start with '-'";
      return;
    }
    const result = await pressButton(this.execDeps(), buttons, name, value);
    if (result.ok) return;
    if (!feed) return;
    const message = result.reason === "undeclared" ? `unknown button: ${name}` : result.reason === "unresolved" ? `${name}: previous run still in progress` : `${name}: invalid input`;
    renderErrorRow(feed, message);
  }
  execDeps() {
    const vault = this.app.vault;
    return {
      mkdirIntentDir: () => (0, import_node_fs.mkdirSync)(QUEUE_DIR2, { recursive: true, mode: 448 }),
      writeIntentFile: (path, data) => (0, import_node_fs.writeFileSync)((0, import_node_path.join)(DASHBOARD_DIR, path), data),
      findUnresolvedRun: (button) => this.findUnresolvedRun(button),
      createRunNote: async (path, content) => {
        const existing = vault.getAbstractFileByPath(path);
        if (existing instanceof import_obsidian.TFile) {
          await vault.modify(existing, content);
        } else {
          await vault.create(path, content);
        }
      },
      modifyRunNote: async (path, content) => {
        const file = vault.getAbstractFileByPath(path);
        if (file instanceof import_obsidian.TFile) await vault.modify(file, content);
      },
      execFile: (command, args, options, callback) => (0, import_node_child_process.execFile)(command, args, options, (error, stdout, stderr) => callback(error, stdout, stderr)),
      now: () => Date.now(),
      randomRunId: () => (0, import_node_crypto.randomBytes)(8).toString("hex")
    };
  }
  findUnresolvedRun(button) {
    const folder = this.app.vault.getAbstractFileByPath(DASHBOARD_RUNS_FOLDER);
    if (!(folder instanceof import_obsidian.TFolder)) return null;
    for (const child of folder.children) {
      if (!(child instanceof import_obsidian.TFile) || child.extension !== "md") continue;
      const cache = this.app.metadataCache.getFileCache(child);
      const frontmatter = cache?.frontmatter;
      if (frontmatter?.status === "running" && frontmatter?.button === button) {
        return { notePath: child.path };
      }
    }
    return null;
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
