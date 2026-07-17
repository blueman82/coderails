import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join, isAbsolute } from "node:path";
import {
  loadConfig as loadBaseConfig,
  ConfigError,
  type ButtonDef,
  type PermissionProfile,
} from "../../app/src/lib/config.ts";

export type { ButtonDef, PermissionProfile };
export { ConfigError }; // a class (value + type) — re-exported as a value, not `export type`, so `instanceof ConfigError` and `new ConfigError(...)` both work for consumers importing it from this module

export type ArtifactPredicate =
  | { kind: "exists" }
  | { kind: "contains"; marker: string }
  | { kind: "last-marker"; success: string; failures: string[] }
  | { kind: "json-field"; path: string; value: unknown };

export interface ExpectedArtifact {
  artifactPath: string;
  maxAgeSeconds: number;
  predicate: ArtifactPredicate;
}

export const ESCALATION_CHANNELS = ["notification", "vault-note"] as const;
export type EscalationChannel = typeof ESCALATION_CHANNELS[number];

export interface RoutineDef {
  name: string;
  label?: string;
  skillCommand?: string;
  buttonRef?: string;
  cadence: string;
  expectedArtifact: ExpectedArtifact;
  escalation: EscalationChannel[];
  foreignSkillPath?: string;
}

export interface DashboardConfig {
  repos: string[];
  wikiPaths: string[];
  buttons: ButtonDef[];
  routines?: RoutineDef[];
}

const PREDICATE_KINDS = ["exists", "contains", "json-field"];

const DEFAULT_CONFIG_PATH = join(homedir(), ".claude", "coderails-dashboard.json");

function validateRoutines(routines: RoutineDef[], buttons: ButtonDef[]): void {
  const buttonNames = new Set(buttons.map((b) => b.name));
  const seenNames = new Set<string>();
  for (const routine of routines) {
    if (seenNames.has(routine.name)) {
      throw new ConfigError(`Duplicate routine name: ${routine.name}`);
    }
    seenNames.add(routine.name);

    if (!routine.skillCommand && !routine.buttonRef) {
      throw new ConfigError(
        `Routine "${routine.name}" must define exactly one of skillCommand or buttonRef`
      );
    }
    if (routine.skillCommand && routine.buttonRef) {
      throw new ConfigError(
        `Routine "${routine.name}" must define exactly one of skillCommand or buttonRef, not both`
      );
    }
    if (routine.buttonRef && !buttonNames.has(routine.buttonRef)) {
      throw new ConfigError(
        `Routine "${routine.name}" has buttonRef "${routine.buttonRef}" that matches no button`
      );
    }

    const artifact = routine.expectedArtifact;
    if (!artifact || typeof artifact.maxAgeSeconds !== "number" || artifact.maxAgeSeconds <= 0) {
      throw new ConfigError(
        `Routine "${routine.name}" expectedArtifact.maxAgeSeconds must be a positive number`
      );
    }
    // Template placeholders like {date}/{vault} are left unresolved here — the runner
    // resolves them at execution time; this only checks the field is a non-empty string.
    if (!artifact || typeof artifact.artifactPath !== "string" || artifact.artifactPath.length === 0) {
      throw new ConfigError(
        `Routine "${routine.name}" expectedArtifact.artifactPath must be a non-empty string`
      );
    }
    if (!artifact.predicate || !PREDICATE_KINDS.includes(artifact.predicate.kind)) {
      throw new ConfigError(
        `Routine "${routine.name}" expectedArtifact.predicate has unknown kind`
      );
    }

    for (const channel of routine.escalation) {
      if (!(ESCALATION_CHANNELS as readonly string[]).includes(channel)) {
        throw new ConfigError(
          `Routine "${routine.name}" has unknown escalation channel: ${channel}`
        );
      }
    }

    if (routine.foreignSkillPath !== undefined) {
      if (typeof routine.foreignSkillPath !== "string" || routine.foreignSkillPath.length === 0) {
        throw new ConfigError(
          `Routine "${routine.name}" foreignSkillPath must be a non-empty string`
        );
      }
      if (!isAbsolute(routine.foreignSkillPath)) {
        throw new ConfigError(
          `Routine "${routine.name}" has relative foreignSkillPath (must be absolute): ${routine.foreignSkillPath}`
        );
      }
    }
  }
}

// Wraps the merged app's loadConfig (which already validates buttons and
// throws ConfigError on the base shape) and layers routine validation on
// top. Re-parses the file rather than calling loadBaseConfig(path) and
// trusting its return type, because loadBaseConfig's own DashboardConfig
// type has no `routines` field — a plain re-read keeps this function
// honest about what it actually validates.
export function loadConfig(path: string = DEFAULT_CONFIG_PATH): DashboardConfig {
  loadBaseConfig(path); // throws ConfigError on malformed JSON / bad buttons — reuse, don't reimplement

  const raw = readFileSync(path, "utf-8");
  const data = JSON.parse(raw) as DashboardConfig;

  if (data.routines) {
    validateRoutines(data.routines, data.buttons);
  }

  return data;
}
