// Re-reads the same ~/.claude/coderails-dashboard.json shape documented by
// the web app's DashboardConfig/ButtonDef (skills/dashboard/app/src/lib/config.ts).
// This plugin only needs name/label for the read-only command grid (Task 12);
// wiring presses against profile/cwd/command is Task 13.
import type { ButtonItem } from "./render";

export interface ParsedDashboardConfig {
  buttons: ButtonItem[];
}

export function parseDashboardConfig(raw: string): ParsedDashboardConfig {
  try {
    const data = JSON.parse(raw) as { buttons?: Array<{ name?: unknown; label?: unknown }> };
    if (!Array.isArray(data.buttons)) return { buttons: [] };

    const buttons: ButtonItem[] = [];
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
