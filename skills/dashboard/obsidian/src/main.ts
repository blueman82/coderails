import { Plugin, TFile, TFolder, MarkdownPostProcessorContext } from "obsidian";
import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { renderCommandCentre } from "./render";
import type { ActivityItem, ButtonItem, CommandCentreSnapshot, Metrics } from "./render";
import { parseDashboardConfig } from "./config";
import "./styles.css";

const DASHBOARD_RUNS_FOLDER = "dashboard-runs";
const METRICS_NOTE_PATH = `${DASHBOARD_RUNS_FOLDER}/_metrics.json`;
const DASHBOARD_CONFIG_PATH = join(homedir(), ".claude", "coderails-dashboard.json");

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
  async onload(): Promise<void> {
    this.registerMarkdownCodeBlockProcessor(
      "agentic-os",
      async (_source: string, el: HTMLElement, _ctx: MarkdownPostProcessorContext) => {
        const snapshot = await this.buildSnapshot();
        el.appendChild(renderCommandCentre(snapshot));
      }
    );
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
