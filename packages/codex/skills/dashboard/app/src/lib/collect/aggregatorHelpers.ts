import { readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import type { PrGate, PrGateError } from "./prGates";
import type { SessionInfo, LoopInfo } from "./sessions";

export type LocalSource = "projects" | "loops" | "runs" | "queue" | "builds";

// Poll metadata only. Include directory entries to notice creation/removal and
// file identity to notice atomic replacement even when size/mtime coincide.
export function sourceFingerprint(root: string, source: LocalSource): string {
  const parts: string[] = [];
  function visit(dir: string, depth: number): void {
    let entries;
    try { entries = readdirSync(dir, { withFileTypes: true }).sort((a, b) => a.name.localeCompare(b.name)); }
    catch { parts.push(`${dir}:missing`); return; }
    for (const entry of entries) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) {
        parts.push(`${path}:dir`);
        if (source === "projects" || source === "loops" && depth < 2 || source === "builds" && depth < 1) {
          visit(path, depth + 1);
        }
        continue;
      }
      if (!entry.isFile()) continue;
      if (source === "loops" && !["progress.json", "evals.json"].includes(entry.name)) continue;
      if (source === "queue" && !entry.name.endsWith(".json")) continue;
      if (source === "builds" && !["state.json", "heartbeat", "phase"].includes(entry.name)) continue;
      try {
        const stat = statSync(path);
        parts.push(`${path}:${stat.dev}:${stat.ino}:${stat.size}:${stat.mtimeMs}`);
      } catch { parts.push(`${path}:missing`); }
    }
  }
  visit(root, 0);
  return parts.join("\n");
}

export function sortSessions(sessions: SessionInfo[]): SessionInfo[] {
  return [...sessions].sort((a, b) => b.lastActivity - a.lastActivity);
}

export function ageSessions(sessions: SessionInfo[], now: number): SessionInfo[] {
  return sessions.map((session) => {
    const age = now - session.lastActivity;
    const state: SessionInfo["state"] = age < 5 * 60_000 ? "active" : age < 60 * 60_000 ? "idle" : "stalled";
    return state === session.state ? session : { ...session, state };
  });
}

export function sortLoops(loops: LoopInfo[]): LoopInfo[] {
  return [...loops].sort((a, b) => a.slug.localeCompare(b.slug));
}

function isGateError(gate: PrGate | PrGateError): gate is PrGateError {
  return "error" in gate;
}

// Sorted by repo, then PR number (error entries carry no number — they sort
// first within their repo, since a missing/unreachable repo has no number to
// compare).
export function sortGates(gates: (PrGate | PrGateError)[]): (PrGate | PrGateError)[] {
  return [...gates].sort((a, b) => {
    const repoCmp = a.repo.localeCompare(b.repo);
    if (repoCmp !== 0) return repoCmp;
    const aNum = isGateError(a) ? -1 : a.number;
    const bNum = isGateError(b) ? -1 : b.number;
    return aNum - bNum;
  });
}
