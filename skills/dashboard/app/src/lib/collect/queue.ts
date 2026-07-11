import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

// This is the frozen QueueFileEntry shape — the queue contract other
// modules (api/queue/route.ts, queueActions.ts) cite and depend on.
// toolInput is `unknown` deliberately: the queue is generic across all
// gated tools, rendered opaquely, never destructured by assumed shape.
export interface QueueEntry {
  hash: string;
  toolName: string;
  toolInput: unknown;
  createdAt: number;
  status: "pending" | "approved" | "denied";
}

const VALID_STATUSES: QueueEntry["status"][] = ["pending", "approved", "denied"];

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// Validates a parsed JSON value against the QueueFileEntry shape exactly —
// no renamed/snake_case field is accepted in place of the camelCase original,
// and a missing or out-of-vocabulary status is rejected rather than
// defaulted. Returns undefined (never throws) for anything that doesn't
// match, so the caller can skip the file.
function parseQueueEntry(raw: unknown): QueueEntry | undefined {
  if (!isRecord(raw)) return undefined;
  if (typeof raw.hash !== "string") return undefined;
  if (typeof raw.toolName !== "string") return undefined;
  if (!("toolInput" in raw)) return undefined;
  if (typeof raw.createdAt !== "number") return undefined;
  if (typeof raw.status !== "string" || !VALID_STATUSES.includes(raw.status as QueueEntry["status"])) {
    return undefined;
  }
  return {
    hash: raw.hash,
    toolName: raw.toolName,
    toolInput: raw.toolInput,
    createdAt: raw.createdAt,
    status: raw.status as QueueEntry["status"],
  };
}

// Lists `<queueDir>/*.json`, parsing each as a QueueFileEntry. A missing dir,
// an unreadable file, or a file that fails JSON.parse or shape validation
// contributes nothing — never throws. Modeled on collectMemoryTrail's
// per-file try/catch degrade-to-skip idiom.
export function collectQueue(queueDir: string, limit = 50): QueueEntry[] {
  let names: string[];
  try {
    names = readdirSync(queueDir).filter((name) => name.endsWith(".json"));
  } catch {
    return [];
  }

  const entries: QueueEntry[] = [];
  for (const name of names) {
    const path = join(queueDir, name);
    try {
      const raw: unknown = JSON.parse(readFileSync(path, "utf-8"));
      const entry = parseQueueEntry(raw);
      if (entry) entries.push(entry);
    } catch {
      // unreadable or malformed JSON — skip this file, not fatal to the read
    }
  }

  entries.sort((a, b) => b.createdAt - a.createdAt);
  return entries.slice(0, limit);
}
