import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";

export class QueueActionError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "QueueActionError";
  }
}

type Decision = "approved" | "denied";

export interface QueueEntrySnapshot {
  hash: string;
  toolName: string;
  toolInput: unknown;
  createdAt: number;
  status: "approved" | "denied";
}

const VALID_DECISIONS: Decision[] = ["approved", "denied"];

// hash is the hex SHA-256 filename stem per the queue contract (see
// lib/collect/queue.ts's QueueFileEntry shape). The API
// route already validates this shape before calling in, but this function is
// exported and documented as the sole writer of the approved/denied
// transition — it must not trust a caller to have sanitised `hash`, since
// `join(queueDir, hash + ".json")` does NOT stop a "../" segment from
// escaping queueDir. Re-checking here is defense-in-depth, not redundant.
const HASH_PATTERN = /^[0-9a-f]{64}$/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

// The dashboard's Approve/Deny action: the only writer of the
// approved/denied transition per the queue contract. Reads the single
// <hash>.json file named by `hash` (never globs the directory — this is
// what guarantees no bleed-through to a different pending entry), parses
// it, flips its status field in place, and writes the same file back
// unchanged otherwise. This is an in-place JSON rewrite, not a separate
// decision-file mechanism, per the spec's own "Deferred work" language.
//
// Throws QueueActionError (never silently succeeds, never defaults to
// approved) when: the hash is not a well-formed hex SHA-256 (blocks path
// traversal), the decision value is invalid, the target file doesn't exist
// or can't be read, the file's contents aren't valid JSON, or the entry is
// not currently pending (blocks approve-after-deny and double-approve
// re-flips — the transition is pending-only, one-shot).
export function resolveQueueEntry(
  queueDir: string,
  hash: string,
  decision: Decision
): QueueEntrySnapshot {
  if (!HASH_PATTERN.test(hash)) {
    throw new QueueActionError(`invalid hash: ${hash}`);
  }

  if (!VALID_DECISIONS.includes(decision)) {
    throw new QueueActionError(`invalid decision: ${String(decision)}`);
  }

  const path = join(queueDir, `${hash}.json`);

  let raw: string;
  try {
    raw = readFileSync(path, "utf-8");
  } catch (err) {
    throw new QueueActionError(`could not read queue file for hash ${hash}: ${String(err)}`);
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch (err) {
    throw new QueueActionError(`queue file for hash ${hash} is not valid JSON: ${String(err)}`);
  }

  if (!isRecord(parsed)) {
    throw new QueueActionError(`queue file for hash ${hash} does not contain a JSON object`);
  }

  if (parsed.status !== "pending") {
    throw new QueueActionError(
      `entry ${hash} is not pending (current status: ${String(parsed.status)})`
    );
  }

  // hash is the validated parameter, never the file's own hash field — the
  // file contents are otherwise-untrusted, and a caller (e.g.
  // claimAndSpawnBuild's join(buildsDir, entry.hash)) must never see a
  // divergent value from inside the JSON.
  const updated: Record<string, unknown> = { ...parsed, hash, status: decision };
  writeFileSync(path, JSON.stringify(updated));
  return updated as unknown as QueueEntrySnapshot;
}
