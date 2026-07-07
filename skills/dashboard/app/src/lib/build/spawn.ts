import { spawn as spawnReal } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import type { QueueEntrySnapshot } from "../collect/queueActions";
import { buildPrompt } from "./prompt";

const NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,63}$/;
const DEFAULT_BUILDS_DIR = join(homedir(), ".claude", "coderails-dashboard", "builds");
const MAX_ANCESTORS = 10;

// A distinctive line from this exact wrapper script (not a generic
// "coderails" string match) — checked against any scripts/run-builder.sh
// candidate found during the walk-up below, so an unrelated tree that
// happens to share the same relative scripts/run-builder.sh path (a nested
// checkout, a monorepo, some other project's own differently-shaped
// wrapper script) is rejected rather than silently accepted.
const WRAPPER_IDENTITY_MARKER = "Owns the build lifecycle state machine for one approved";

// route.ts previously resolved the wrapper path via
// join(process.cwd(), "..", "scripts", "run-builder.sh") — cwd-relative,
// the exact class of bug design-loop2.md's premortem #8 flags (a
// production Next.js server's cwd is not guaranteed to be the app root).
// This walks upward from the module's own location (__dirname, stable
// regardless of the server process's cwd) looking for the known sibling
// skills/dashboard/scripts/run-builder.sh, matching the same
// find-the-repo-root-by-walking-up technique already used by
// collect/markerVersions.ts's findRepoRoot — with an added content-identity
// check (existence alone isn't enough: a nested checkout or monorepo could
// have its own unrelated scripts/run-builder.sh at a shallower ancestor
// level). Returns null (never a fabricated guess) if no matching sibling is
// found within MAX_ANCESTORS levels — callers must treat null as "no
// default available", not silently spawn a wrong path.
export function resolveDefaultWrapperPath(startDir: string = __dirname): string | null {
  let dir = startDir;
  for (let i = 0; i < MAX_ANCESTORS; i++) {
    const candidate = join(dir, "scripts", "run-builder.sh");
    if (existsSync(candidate)) {
      try {
        const contents = readFileSync(candidate, "utf-8");
        if (contents.includes(WRAPPER_IDENTITY_MARKER)) {
          return candidate;
        }
      } catch {
        // unreadable — treat as not a match, keep walking up
      }
    }
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

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
  | { claimed: false; error: "invalid_name" | "wrapper_not_found" };

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
  writeFileSync(join(buildDir, "prompt.md"), buildPrompt(entry));
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
