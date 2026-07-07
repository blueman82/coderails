import { existsSync, readFileSync, statSync } from "node:fs";
import { resolve as resolvePath, sep } from "node:path";
import type { ExpectedArtifact } from "@coderails/dashboard-lib";

export interface ArtifactCheckContext {
  date: string;
  runId: string;
  vault: string;
}

export interface ArtifactCheckResult {
  passed: boolean;
  reason: string;
}

export function resolveArtifactPath(template: string, ctx: ArtifactCheckContext): string {
  return template
    .replaceAll("{date}", ctx.date)
    .replaceAll("{runId}", ctx.runId)
    .replaceAll("{vault}", ctx.vault);
}

// {date}/{runId} are substituted from values this process itself derives
// (todayIso()-shaped date, a randomBytes-generated runId — see sweep.ts),
// not from the queued intent file, so they can't smuggle "../" today. This
// check is defense-in-depth per WU1 review carry-note 2: it stops a crafted
// artifactPath template or a future producer of {runId}/{date} from
// resolving outside the one directory that template's own {vault}/fixed
// prefix names, rather than trusting every template author to get this
// right by hand.
function escapesRoot(resolvedPath: string, template: string, ctx: ArtifactCheckContext): boolean {
  const rootToken = template.includes("{vault}") ? ctx.vault : undefined;
  if (!rootToken) return false; // no {vault} token: nothing to contain against
  const root = resolvePath(rootToken);
  const withinRoot = resolvedPath === root || resolvedPath.startsWith(root + sep);
  return !withinRoot;
}

function getJsonField(obj: unknown, path: string): unknown {
  return path.split(".").reduce<unknown>((acc, key) => {
    if (acc === undefined || acc === null || typeof acc !== "object") return undefined;
    return (acc as Record<string, unknown>)[key];
  }, obj);
}

export function checkArtifact(
  artifact: ExpectedArtifact,
  ctx: ArtifactCheckContext
): ArtifactCheckResult {
  const path = resolvePath(resolveArtifactPath(artifact.artifactPath, ctx));

  if (escapesRoot(path, artifact.artifactPath, ctx)) {
    return {
      passed: false,
      reason: `Artifact path escapes its configured {vault} root: ${path}`,
    };
  }

  if (!existsSync(path)) {
    return { passed: false, reason: `Artifact does not exist: ${path}` };
  }

  const stat = statSync(path);
  const ageSeconds = (Date.now() - stat.mtimeMs) / 1000;
  if (ageSeconds > artifact.maxAgeSeconds) {
    return {
      passed: false,
      reason: `Artifact is stale (too old): ${path} is ${Math.round(ageSeconds)}s old, max is ${artifact.maxAgeSeconds}s`,
    };
  }

  const predicate = artifact.predicate;
  if (predicate.kind === "exists") {
    return { passed: true, reason: `Artifact exists and is fresh: ${path}` };
  }

  if (predicate.kind === "contains") {
    const marker = resolveArtifactPath(predicate.marker, ctx);
    const content = readFileSync(path, "utf-8");
    if (content.includes(marker)) {
      return { passed: true, reason: `Artifact contains marker "${marker}"` };
    }
    return { passed: false, reason: `Artifact is missing expected marker "${marker}"` };
  }

  if (predicate.kind === "json-field") {
    let parsed: unknown;
    try {
      parsed = JSON.parse(readFileSync(path, "utf-8"));
    } catch {
      return { passed: false, reason: `Artifact is not valid JSON: ${path}` };
    }
    const actual = getJsonField(parsed, predicate.path);
    if (actual === predicate.value) {
      return { passed: true, reason: `Artifact field "${predicate.path}" matches expected value` };
    }
    return {
      passed: false,
      reason: `Artifact field "${predicate.path}" is ${JSON.stringify(actual)}, expected ${JSON.stringify(predicate.value)}`,
    };
  }

  return { passed: false, reason: `Unknown predicate kind` };
}
