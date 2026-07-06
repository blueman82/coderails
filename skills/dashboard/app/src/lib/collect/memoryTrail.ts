import { readdirSync, statSync } from "node:fs";
import { join, sep } from "node:path";

export interface TrailEntry {
  path: string;
  displayPath: string;
  mtime: number;
}

// displayPath is the last two path segments (e.g. "memory/feedback_x.md") —
// enough to place the file within its dir without the full absolute path.
function displayPathFor(path: string): string {
  const parts = path.split(sep);
  return parts.slice(-2).join(sep);
}

// Files directly inside `dir` (not recursed), each as a TrailEntry. A
// nonexistent or unreadable dir contributes nothing and never throws.
function listFilesFlat(dir: string): TrailEntry[] {
  let entries;
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return [];
  }
  const files: TrailEntry[] = [];
  for (const entry of entries) {
    if (!entry.isFile()) continue;
    const path = join(dir, entry.name);
    try {
      const mtime = statSync(path).mtimeMs;
      files.push({ path, displayPath: displayPathFor(path), mtime });
    } catch {
      // ignore unreadable file
    }
  }
  return files;
}

// Merges the flat file listing of each dir (newest-first across all dirs
// combined), truncated to `limit`. A nonexistent dir contributes nothing;
// never throws.
export function collectMemoryTrail(dirs: string[], limit: number): TrailEntry[] {
  const all = dirs.flatMap(listFilesFlat);
  all.sort((a, b) => b.mtime - a.mtime);
  return all.slice(0, limit);
}
