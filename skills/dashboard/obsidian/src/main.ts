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
      (_source: string, el: HTMLElement, _ctx: MarkdownPostProcessorContext) => {
        const snapshot = this.buildSnapshot();
        el.appendChild(renderCommandCentre(snapshot));
      }
    );
  }

  private buildSnapshot(): CommandCentreSnapshot {
    return {
      metrics: this.readMetrics(),
      activity: this.readActivity(),
      buttons: this.readButtons(),
    };
  }

  private readMetrics(): Metrics | null {
    const file = this.app.vault.getAbstractFileByPath(METRICS_NOTE_PATH);
    if (!(file instanceof TFile)) return null;

    try {
      const raw = this.app.vault.cachedRead
        ? undefined
        : undefined;
      // Obsidian's vault reads are async; the code-block processor callback
      // is sync, so metrics/activity are read from the metadata cache and
      // adapter's synchronous read where available, falling back to null
      // rather than blocking render on a promise.
      const content = (this.app.vault.adapter as unknown as { readSync?: (p: string) => string })
        .readSync?.(file.path);
      if (!content) return null;
      return JSON.parse(content) as Metrics;
    } catch {
      return null;
    }
  }

  private readActivity(): ActivityItem[] {
    const folder = this.app.vault.getAbstractFileByPath(DASHBOARD_RUNS_FOLDER);
    if (!(folder instanceof TFolder)) return [];

    const entries: ActivityItem[] = [];
    for (const child of folder.children) {
      if (!(child instanceof TFile) || child.extension !== "md") continue;

      const cache = this.app.metadataCache.getFileCache(child);
      const status = (cache?.frontmatter?.status as string) ?? "pending";

      const content = (this.app.vault.adapter as unknown as { readSync?: (p: string) => string })
        .readSync?.(child.path);
      const summary = content ? firstBodyLine(content) : child.basename;

      entries.push({
        title: summary,
        status,
        time: formatTime(child.stat.mtime),
        notePath: child.path,
      });
    }

    entries.sort((a, b) => {
      const fileA = folder.children.find((c) => c instanceof TFile && c.path === a.notePath) as TFile;
      const fileB = folder.children.find((c) => c instanceof TFile && c.path === b.notePath) as TFile;
      return fileB.stat.mtime - fileA.stat.mtime;
    });

    return entries;
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
