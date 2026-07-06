// Re-reads the same ~/.claude/coderails-dashboard.json shape documented by
// the web app's DashboardConfig/ButtonDef (skills/dashboard/app/src/lib/config.ts).
// Task 12 only needed name/label for the read-only command grid; Task 13
// widens this to the fields buildArgv and exec.ts need to press a button.
import type { ButtonItem, PermissionProfile } from "./render";

const PERMISSION_PROFILES: PermissionProfile[] = ["read-only", "standard", "bypass"];

export interface ParsedDashboardConfig {
  buttons: ButtonItem[];
}

interface RawButton {
  name?: unknown;
  label?: unknown;
  command?: unknown;
  cwd?: unknown;
  profile?: unknown;
  inputAllowed?: unknown;
}

function isValidButton(button: RawButton): button is {
  name: string;
  label: string;
  command: string;
  cwd: string;
  profile: PermissionProfile;
  inputAllowed?: boolean;
} {
  return (
    typeof button.name === "string" &&
    typeof button.label === "string" &&
    typeof button.command === "string" &&
    typeof button.cwd === "string" &&
    typeof button.profile === "string" &&
    PERMISSION_PROFILES.includes(button.profile as PermissionProfile) &&
    (button.inputAllowed === undefined || typeof button.inputAllowed === "boolean")
  );
}

export function parseDashboardConfig(raw: string): ParsedDashboardConfig {
  try {
    const data = JSON.parse(raw) as { buttons?: RawButton[] };
    if (!Array.isArray(data.buttons)) return { buttons: [] };

    const buttons: ButtonItem[] = [];
    for (const button of data.buttons) {
      if (!isValidButton(button)) continue;
      buttons.push({
        name: button.name,
        label: button.label,
        command: button.command,
        cwd: button.cwd,
        profile: button.profile,
        ...(button.inputAllowed !== undefined ? { inputAllowed: button.inputAllowed } : {}),
      });
    }
    return { buttons };
  } catch {
    return { buttons: [] };
  }
}
