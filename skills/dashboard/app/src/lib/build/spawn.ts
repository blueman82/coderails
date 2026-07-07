import { spawn as spawnReal } from "node:child_process";
import { mkdirSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import type { QueueEntrySnapshot } from "../collect/queueActions";

const NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,63}$/;
const DEFAULT_BUILDS_DIR = join(homedir(), ".claude", "coderails-dashboard", "builds");

export type SpawnFn = (
  command: string,
  args: readonly string[],
  options: { detached: boolean; stdio: "ignore"; env: NodeJS.ProcessEnv }
) => { unref: () => void };

export interface ClaimAndSpawnBuildDeps {
  buildsDir?: string;
  wrapperPath: string;
  spawnImpl?: SpawnFn;
}

export type ClaimAndSpawnBuildResult =
  | { claimed: true; runId: string }
  | { claimed: false; alreadyClaimed: true }
  | { claimed: false; error: "invalid_name" };

// The claim-and-spawn seam: called from POST /api/queue after resolveQueueEntry
// flips an entry to "approved" with toolName "workflow-audit:propose-skill".
// Claims the hash via a non-recursive mkdirSync (EEXIST = already claimed —
// the atomic-exclusive idiom, same as api/run/route.ts's acquireLock), writes
// the sidecar files a detached builder wrapper will consume, then spawns and
// detaches it. Fire-and-forget is safe here: the claim dir is never released
// on exit, it transitions to a terminal state instead (retry = delete it).
export function claimAndSpawnBuild(
  entry: QueueEntrySnapshot,
  deps: ClaimAndSpawnBuildDeps
): ClaimAndSpawnBuildResult {
  // toolInput is opaque (`unknown`) per queue.ts's own documented contract —
  // narrow explicitly rather than trusting its shape.
  const toolInput = entry.toolInput as Record<string, unknown> | null | undefined;
  const proposedName =
    toolInput && typeof toolInput === "object" ? toolInput.proposed_name : undefined;
  if (typeof proposedName !== "string" || !NAME_PATTERN.test(proposedName)) {
    return { claimed: false, error: "invalid_name" };
  }

  const buildsDir = deps.buildsDir ?? DEFAULT_BUILDS_DIR;
  const buildDir = join(buildsDir, entry.hash);

  mkdirSync(buildsDir, { recursive: true });

  try {
    mkdirSync(buildDir);
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "EEXIST") {
      return { claimed: false, alreadyClaimed: true };
    }
    throw err;
  }

  writeFileSync(join(buildDir, "snapshot.json"), JSON.stringify(entry));
  // WU2's src/lib/build/prompt.ts supplies the real template; this task only
  // establishes the file-write contract with a placeholder.
  writeFileSync(
    join(buildDir, "prompt.md"),
    `# Builder prompt for ${entry.hash}\n\nSee prompt.ts (WU2) for the real template — this task only establishes the file-write contract.`
  );
  writeFileSync(
    join(buildDir, "state.json"),
    JSON.stringify({ schemaVersion: 1, hash: entry.hash, state: "claimed", createdAt: Date.now() })
  );

  const spawnImpl = deps.spawnImpl ?? (spawnReal as unknown as SpawnFn);
  const child = spawnImpl("bash", [deps.wrapperPath, buildDir], {
    detached: true,
    stdio: "ignore",
    env: { ...process.env, CODERAILS_BUILDER: "1" },
  });
  child.unref();

  return { claimed: true, runId: entry.hash.slice(0, 8) };
}
