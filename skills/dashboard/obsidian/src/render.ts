// Pure vault-state-in, DOM-out renderer for the coderails command centre.
// No Obsidian API calls here — main.ts adapts vault reads into a
// CommandCentreSnapshot and hands it to renderCommandCentre, which is why
// this module is testable with plain DOM (jsdom) and no Obsidian mock.

export interface LatestMerge {
  title: string;
  prCount: number;
  testCount: number;
  tier: string;
}

export interface Metrics {
  tokenBurnPercent: number;
  tokenBurnUsed: number;
  tokenBurnCap: number;
  openPrs: number;
  activeSessions: number;
  hooksFired: number;
  lintFindings: number;
  latestMerge: LatestMerge | null;
}

export type ActivityStatus = "pass" | "fail" | "needs-review" | string;

export interface ActivityItem {
  title: string;
  status: ActivityStatus;
  time: string;
  notePath: string;
}

export type PermissionProfile = "read-only" | "standard" | "bypass";

export interface ButtonItem {
  name: string;
  label: string;
  command: string;
  cwd: string;
  profile: PermissionProfile;
  inputAllowed?: boolean;
}

export interface CommandCentreSnapshot {
  metrics: Metrics | null;
  activity: ActivityItem[];
  buttons: ButtonItem[];
}

const CHIP_CLASS_BY_STATUS: Record<string, string> = {
  pass: "cc-chip-pass",
  fail: "cc-chip-fail",
  "needs-review": "cc-chip-needs-review",
  // "done"/"failed"/"running" are the run-note frontmatter statuses a
  // Task 13 button press writes (see exec.ts) — an unresolved run reads as
  // "running" until execFile's callback flips the note to done/failed.
  done: "cc-chip-pass",
  failed: "cc-chip-fail",
  running: "cc-chip-running",
};

function chipClassFor(status: ActivityStatus): string {
  return CHIP_CLASS_BY_STATUS[status] ?? "cc-chip-pending";
}

function chipTextFor(status: ActivityStatus): string {
  return status === "running" ? "⏳" : status;
}

function el(tag: string, className: string, text?: string): HTMLElement {
  const node = document.createElement(tag);
  node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function renderMetricsPanel(container: HTMLElement, metrics: Metrics | null): void {
  if (!metrics) {
    const hint = el(
      "div",
      "cc-terminal-hint",
      "no dashboard-runs/_metrics.json in this vault — run PULL METRICS to populate it"
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
  const stats: Array<[string, number]> = [
    ["OPEN PRS", metrics.openPrs],
    ["ACTIVE SESSIONS", metrics.activeSessions],
    ["HOOKS FIRED", metrics.hooksFired],
    ["LINT FINDINGS", metrics.lintFindings],
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

function renderCommandGrid(container: HTMLElement, buttons: ButtonItem[]): void {
  const grid = el("div", "cc-command-grid");
  if (buttons.length === 0) {
    grid.appendChild(el("div", "cc-command-grid-empty", "no commands declared — add buttons[] to ~/.claude/coderails-dashboard.json"));
  } else {
    for (const button of buttons) {
      const btn = el("button", "cc-cmd-btn", button.label);
      btn.setAttribute("data-button-name", button.name);
      grid.appendChild(btn);
    }
  }
  container.appendChild(grid);
}

function renderActivityFeed(container: HTMLElement, activity: ActivityItem[]): void {
  const feed = el("div", "cc-activity-feed");
  if (activity.length === 0) {
    feed.appendChild(el("div", "cc-activity-empty", "no activity yet"));
  } else {
    // Caller is the source of truth for ordering (newest first); this
    // renderer does not re-sort.
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

// Called by main.ts's click handler after a rejected press (undeclared
// button, unresolved previous run, or invalid input) — prepended so the
// most recent rejection is the first thing the user sees, without
// disturbing the vault-derived rows already rendered.
export function renderErrorRow(feed: Element, message: string): void {
  const row = el("div", "cc-activity-row-error", message);
  feed.insertBefore(row, feed.firstChild);
}

export function renderCommandCentre(snapshot: CommandCentreSnapshot): HTMLElement {
  const root = el("div", "cc-root");

  const header = el("div", "cc-header");
  header.appendChild(el("span", "cc-header-glyph", "⌁"));
  header.appendChild(el("span", "cc-header-title", "AGENTIC OS · CODERAILS"));
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
