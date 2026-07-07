import { MarkdownRenderChild, Plugin, TFile, TFolder, MarkdownPostProcessorContext } from "obsidian";
import { execFile as execFileReal } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { randomBytes } from "node:crypto";
import { homedir } from "node:os";
import { join } from "node:path";
import { renderCommandCentre, renderErrorRow } from "./render";
import type { ActivityItem, ButtonItem, CommandCentreSnapshot, Metrics } from "./render";
import { parseDashboardConfig } from "./config";
import { pressButton } from "./exec";
import type { ExecDeps, UnresolvedRun } from "./exec";
import { writeRunNote } from "./notes";
// styles.css lives at the plugin root (not imported here) — Obsidian loads
// a plugin's styles.css automatically alongside main.js and manifest.json.

const DASHBOARD_RUNS_FOLDER = "dashboard-runs";
// Raw JSON read from the vault, not a markdown note (hence FILE, not NOTE).
const METRICS_FILE_PATH = `${DASHBOARD_RUNS_FOLDER}/_metrics.json`;
const DASHBOARD_CONFIG_PATH = join(homedir(), ".claude", "coderails-dashboard.json");
const DASHBOARD_DIR = join(homedir(), ".claude", "coderails-dashboard");
const QUEUE_DIR = join(DASHBOARD_DIR, "queue");

function firstBodyLine(content: string): string {
  // Strip the frontmatter block (--- ... ---) before taking the first
  // non-blank line, so the summary is the note's prose, not YAML.
  const withoutFrontmatter = content.replace(/^---\n[\s\S]*?\n---\n/, "");
  const line = withoutFrontmatter
    .split("\n")
    .map((l) => l.trim())
    .find((l) => l.length > 0);
  return line ?? "";
}

function formatTime(mtimeMs: number): string {
  return new Date(mtimeMs).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

export default class CommandCentrePlugin extends Plugin {
  // Live containers for every rendered ```agentic-os``` block, so a vault
  // "modify" event under dashboard-runs/ (a run note flipping from running
  // to done/failed — see exec.ts) can re-render each one in place. Obsidian
  // calls the code-block processor again on its own note-reload path, but
  // NOT when a note is edited by code rather than by the user in that pane
  // — this registration is what makes the feed flip without the user
  // having to reopen the note.
  private containers = new Set<HTMLElement>();

  async onload(): Promise<void> {
    this.registerMarkdownCodeBlockProcessor(
      "agentic-os",
      async (_source: string, el: HTMLElement, ctx: MarkdownPostProcessorContext) => {
        await this.renderInto(el);
        this.containers.add(el);
        const child = new MarkdownRenderChild(el);
        child.register(() => this.containers.delete(el));
        ctx.addChild(child);
      }
    );

    this.registerEvent(
      this.app.vault.on("modify", (file) => {
        if (file instanceof TFile && file.path.startsWith(`${DASHBOARD_RUNS_FOLDER}/`)) {
          void this.rerenderAll();
        }
      })
    );
  }

  private async rerenderAll(): Promise<void> {
    for (const container of this.containers) {
      container.empty();
      await this.renderInto(container);
    }
  }

  private async renderInto(container: HTMLElement): Promise<void> {
    const snapshot = await this.buildSnapshot();
    const root = renderCommandCentre(snapshot);
    container.appendChild(root);
    this.wireButtons(root, snapshot.buttons);
  }

  private wireButtons(root: HTMLElement, buttons: ButtonItem[]): void {
    const feed = root.querySelector(".cc-activity-feed");
    root.querySelectorAll<HTMLButtonElement>(".cc-cmd-btn").forEach((btn) => {
      const name = btn.getAttribute("data-button-name");
      if (!name) return;

      this.registerDomEvent(btn, "click", () => {
        void this.handlePress(root, feed, buttons, name);
      });
    });
  }

  private async handlePress(
    root: HTMLElement,
    feed: Element | null,
    buttons: ButtonItem[],
    name: string
  ): Promise<void> {
    const input = root.querySelector<HTMLInputElement>(`.cc-cmd-input[data-button-name="${name}"]`);
    const errorText = root.querySelector<HTMLElement>(`.cc-cmd-input-error[data-button-name="${name}"]`);
    const rawInput = input?.value.trim();
    const value = rawInput ? rawInput : undefined;

    if (errorText) errorText.textContent = "";

    if (value !== undefined && value.startsWith("-")) {
      if (errorText) errorText.textContent = "input must not start with '-'";
      return;
    }

    const result = await pressButton(this.execDeps(), buttons, name, value);
    if (result.ok) return;

    if (!feed) return;
    const message =
      result.reason === "undeclared"
        ? `unknown button: ${name}`
        : result.reason === "unresolved"
          ? `${name}: previous run still in progress`
          : `${name}: invalid input`;
    renderErrorRow(feed, message);
  }

  private execDeps(): ExecDeps {
    const vault = this.app.vault;
    return {
      mkdirIntentDir: () => mkdirSync(QUEUE_DIR, { recursive: true, mode: 0o700 }),
      writeIntentFile: (path, data) => writeFileSync(join(DASHBOARD_DIR, path), data),
      findUnresolvedRun: (button) => this.findUnresolvedRun(button),
      createRunNote: async (path, content) => {
        // dashboard-runs/<date>-<button>.md is stable per button per day (per
        // the brief) — a second resolved run for the same button on the same
        // day overwrites rather than colliding on vault.create's throw-if-
        // exists. findUnresolvedRun already blocks a second *concurrent*
        // press, so this only ever fires after the prior run resolved.
        await writeRunNote(
          {
            exists: (p) => vault.getAbstractFileByPath(p) instanceof TFile,
            create: (p, c) => vault.create(p, c).then(() => undefined),
            modify: (p, c) => {
              const file = vault.getAbstractFileByPath(p);
              return file instanceof TFile ? vault.modify(file, c) : Promise.resolve();
            },
          },
          path,
          content
        );
      },
      modifyRunNote: async (path, content) => {
        const file = vault.getAbstractFileByPath(path);
        if (file instanceof TFile) await vault.modify(file, content);
      },
      execFile: (command, args, options, callback) =>
        execFileReal(command, args, options, (error, stdout, stderr) => callback(error, stdout, stderr)),
      now: () => Date.now(),
      randomRunId: () => randomBytes(8).toString("hex"),
    };
  }

  private findUnresolvedRun(button: string): UnresolvedRun | null {
    const folder = this.app.vault.getAbstractFileByPath(DASHBOARD_RUNS_FOLDER);
    if (!(folder instanceof TFolder)) return null;

    for (const child of folder.children) {
      if (!(child instanceof TFile) || child.extension !== "md") continue;
      const cache = this.app.metadataCache.getFileCache(child);
      const frontmatter = cache?.frontmatter;
      if (frontmatter?.status === "running" && frontmatter?.button === button) {
        return { notePath: child.path };
      }
    }
    return null;
  }

  private async buildSnapshot(): Promise<CommandCentreSnapshot> {
    const [metrics, activity] = await Promise.all([this.readMetrics(), this.readActivity()]);
    return {
      metrics,
      activity,
      buttons: this.readButtons(),
    };
  }

  private async readMetrics(): Promise<Metrics | null> {
    const file = this.app.vault.getAbstractFileByPath(METRICS_NOTE_PATH);
    if (!(file instanceof TFile)) return null;

    try {
      const content = await this.app.vault.cachedRead(file);
      return JSON.parse(content) as Metrics;
    } catch {
      return null;
    }
  }

  private async readActivity(): Promise<ActivityItem[]> {
    const folder = this.app.vault.getAbstractFileByPath(DASHBOARD_RUNS_FOLDER);
    if (!(folder instanceof TFolder)) return [];

    const files = folder.children.filter(
      (child): child is TFile => child instanceof TFile && child.extension === "md"
    );

    const entries = await Promise.all(
      files.map(async (file) => {
        const cache = this.app.metadataCache.getFileCache(file);
        const status = (cache?.frontmatter?.status as string) ?? "pending";
        const content = await this.app.vault.cachedRead(file);
        return {
          item: {
            title: firstBodyLine(content) || file.basename,
            status,
            time: formatTime(file.stat.mtime),
            notePath: file.path,
          } satisfies ActivityItem,
          mtime: file.stat.mtime,
        };
      })
    );

    // Newest-first, matching the mockup's activity feed ordering.
    entries.sort((a, b) => b.mtime - a.mtime);
    return entries.map((e) => e.item);
  }

  private readButtons(): ButtonItem[] {
    try {
      const raw = readFileSync(DASHBOARD_CONFIG_PATH, "utf-8");
      return parseDashboardConfig(raw).buttons;
    } catch {
      return [];
    }
  }
}
