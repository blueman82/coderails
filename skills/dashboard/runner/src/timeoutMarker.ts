import { appendFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import type { RoutineDef } from "@coderails/dashboard-lib";
import { resolveArtifactPath, type ArtifactCheckContext } from "./artifactGate.ts";

export function localDateIso(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function recordTimeoutMarker(routine: RoutineDef, ctx: ArtifactCheckContext): void {
  const predicate = routine.expectedArtifact.predicate;
  if (predicate.kind !== "last-marker") return;
  const path = resolveArtifactPath(routine.expectedArtifact.artifactPath, ctx);
  const marker = resolveArtifactPath(predicate.failures[0], ctx);
  try {
    mkdirSync(dirname(path), { recursive: true });
    appendFileSync(path, `${new Date().toISOString()} ${marker}runner-timeout-kill\n`);
  } catch (err) {
    console.error("recordTimeoutMarker: failed to append terminal marker, continuing:", err);
  }
}
