import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join, isAbsolute } from "node:path";

export type PermissionProfile = "read-only" | "standard" | "auto" | "bypass";

export interface ButtonDef {
  name: string;
  label: string;
  // An empty string is valid only for an input-bearing (inputAllowed) button
  // whose free-text input supplies the whole prompt; an empty or
  // whitespace-only command with no (effective) input is rejected by
  // buildArgv rather than spawning an empty prompt.
  command: string;
  cwd: string;
  profile: PermissionProfile;
  inputAllowed?: boolean;
  bypassPermissions?: true;
  hidden?: boolean;
}

export interface DashboardConfig {
  repos: string[];
  wikiPaths: string[];
  memoryPaths: string[];
  buttons: ButtonDef[];
}

const PERMISSION_PROFILES: PermissionProfile[] = ["read-only", "standard", "auto", "bypass"];

const DEFAULT_CONFIG_PATH = join(homedir(), ".claude", "coderails-dashboard.json");

export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConfigError";
  }
}

export function loadConfig(path?: string): DashboardConfig {
  const configPath = path ?? DEFAULT_CONFIG_PATH;
  let raw: string;
  try {
    raw = readFileSync(configPath, "utf-8");
  } catch {
    throw new ConfigError(`Config file not found: ${configPath}`);
  }

  let data: DashboardConfig;
  try {
    data = JSON.parse(raw) as DashboardConfig;
  } catch {
    throw new ConfigError(`Config file has malformed JSON: ${configPath}`);
  }

  const seenNames = new Set<string>();
  for (const button of data.buttons) {
    if (seenNames.has(button.name)) {
      throw new ConfigError(`Duplicate button name: ${button.name}`);
    }
    seenNames.add(button.name);

    if (!PERMISSION_PROFILES.includes(button.profile)) {
      throw new ConfigError(
        `Button "${button.name}" has unknown profile: ${button.profile}`
      );
    }

    if (button.profile === "bypass" && button.bypassPermissions !== true) {
      throw new ConfigError(
        `Button "${button.name}" has profile "bypass" but is missing bypassPermissions: true`
      );
    }

    if (!isAbsolute(button.cwd)) {
      throw new ConfigError(
        `Button "${button.name}" has relative cwd (must be absolute): ${button.cwd}`
      );
    }
  }

  return data;
}
