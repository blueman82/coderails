import { realpath } from "node:fs/promises";
import { homedir } from "node:os";
import { join, resolve, sep } from "node:path";
import type { SourceRef, TraceCollectionDeps } from "./sessionTrace";

export const NATIVE_SESSION_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const MAX_TRACE_PAGE = 100;

export interface NativeRouteDeps {
  token: string;
  sourceRoot: string;
  cacheRoot: string;
  loopsRoot: string;
  list: (deps: TraceCollectionDeps) => Promise<unknown[]>;
  page: (sessionId: string, cursor: string | null, limit: number, deps: TraceCollectionDeps) => Promise<{
    events: Array<{ provenance: { sourceId: string; sourceRef: SourceRef } }>;
    inputCursor: string | null; nextCursor: string | null; complete: boolean;
  }>;
  detail: (sessionId: string, ref: SourceRef, deps: TraceCollectionDeps) => Promise<unknown>;
}

export function nativeRouteDefaults(provider: "claude" | "codex") {
  return {
    sourceRoot: join(homedir(), provider === "claude" ? ".claude" : ".codex", provider === "claude" ? "projects" : "sessions"),
    cacheRoot: join(homedir(), ".coderails", "telemetry"),
    loopsRoot: join(homedir(), ".coderails", "agentic-loop"),
  };
}

export function validSourceRef(value: unknown): value is SourceRef {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const ref = value as Record<string, unknown>;
  return Object.keys(ref).length === 3 && typeof ref.kind === "string" && /^[a-z_]+$/.test(ref.kind) &&
    typeof ref.recordId === "string" && ref.recordId.length > 0 && ref.recordId.length <= 512 &&
    !ref.recordId.includes("..") && !ref.recordId.includes("\\") &&
    typeof ref.ordinal === "number" && Number.isSafeInteger(ref.ordinal) && ref.ordinal >= 0;
}

export async function sourceInsideRoot(sourceId: string, sourceRoot: string): Promise<boolean> {
  const root = resolve(sourceRoot);
  const path = resolve(sourceRoot, sourceId);
  if (!path.startsWith(root + sep)) return false;
  try { return (await realpath(path)).startsWith((await realpath(root)) + sep); }
  catch { return false; }
}
