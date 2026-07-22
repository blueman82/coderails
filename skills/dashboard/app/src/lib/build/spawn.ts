import { spawn as spawnReal } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import type { QueueEntrySnapshot } from "../collect/queueActions";
import { buildPrompt } from "./prompt";

const NAME_PATTERN = /^[a-z0-9][a-z0-9-]{0,63}$/;
// entry.hash is documented (queueActions.ts) as the hex SHA-256 filename
// stem, and the API route validates the request's hash parameter against
// this same shape — but queueActions.ts's returned snapshot still passes
// through an otherwise-untrusted JSON file's contents, so this is
// defense-in-depth: re-checking here means a bug upstream can't turn
// join(buildsDir, entry.hash) below into a path-traversal write.
const HASH_PATTERN = /^[0-9a-f]{64}$/;
const DEFAULT_BUILDS_DIR = join(homedir(), ".claude", "coderails-dashboard", "builds");
const MAX_ANCESTORS = 10;

// A distinctive line from this exact wrapper script (not a generic
// "coderails" string match) — checked against any scripts/run-builder.sh
// candidate found during the walk-up below, so an unrelated tree that
// happens to share the same relative scripts/run-builder.sh path (a nested
// checkout, a monorepo, some other project's own differently-shaped
// wrapper script) is rejected rather than silently accepted.
const WRAPPER_IDENTITY_MARKER = "Owns the build lifecycle state machine for one approved";

const WRAPPER_ENV_OVERRIDE = "CODERAILS_BUILDER_WRAPPER";

// Checks a single candidate file against the content-identity marker,
// rather than trusting existence alone — shared by every tier of the
// fallback chain below (env override, __dirname walk, cwd walk) so a
// lookalike script at any tier is rejected the same way.
function isIdentifiedWrapper(candidate: string): boolean {
  if (!existsSync(candidate)) return false;
  try {
    return readFileSync(candidate, "utf-8").includes(WRAPPER_IDENTITY_MARKER);
  } catch {
    return false;
  }
}

// Walks upward from startDir looking for a sibling scripts/run-builder.sh,
// matching the same find-the-repo-root-by-walking-up technique already
// used by collect/markerVersions.ts's findRepoRoot — with the same
// content-identity check as isIdentifiedWrapper (existence alone isn't
// enough: a nested checkout or monorepo could have its own unrelated
// scripts/run-builder.sh at a shallower ancestor level).
function walkUpForWrapper(startDir: string): string | null {
  let dir = startDir;
  for (let i = 0; i < MAX_ANCESTORS; i++) {
    const candidate = join(dir, "scripts", "run-builder.sh");
    if (isIdentifiedWrapper(candidate)) {
      return candidate;
    }
    const parent = dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

// route.ts previously resolved the wrapper path via
// join(process.cwd(), "..", "scripts", "run-builder.sh") — cwd-relative,
// the exact class of bug design-loop2.md's premortem #8 flags (a
// production Next.js server's cwd is not guaranteed to be the app root).
//
// This tries an ordered fallback chain, each tier gated by the same
// content-identity check (a lookalike is rejected, worst case falls
// through to the next tier — never a fabricated guess):
//   1. CODERAILS_BUILDER_WRAPPER env override, if set — an explicit
//      deployment-provided path, for cases where neither of the walks
//      below can find it (e.g. a packaging layout this function doesn't
//      anticipate).
//   2. Walk upward from the module's own location (__dirname) — stable
//      regardless of the server process's cwd, and correct in dev/vitest
//      where __dirname is a real source path. Under a built `next start`
//      server, though, the bundler virtualises __dirname into a chunk
//      path (e.g. "[root-of-the-server]__foo.js") that doesn't exist on
//      disk, so this walk finds nothing there.
//   3. Walk upward from process.cwd() — for `npm run start`, cwd is the
//      app directory, so this recovers the production case tier 2 misses.
//      The identity check makes this safe even though cwd is normally
//      untrustworthy (see the class of bug above): a lookalike is
//      rejected, worst case stays wrapper_not_found.
// Returns null if no tier finds a match — callers must treat null as "no
// default available", not silently spawn a wrong path.
export function resolveDefaultWrapperPath(startDir: string = __dirname): string | null {
  const envOverride = process.env[WRAPPER_ENV_OVERRIDE];
  if (envOverride && isIdentifiedWrapper(envOverride)) {
    return envOverride;
  }

  const viaModuleDir = walkUpForWrapper(startDir);
  if (viaModuleDir) return viaModuleDir;

  return walkUpForWrapper(process.cwd());
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
  | { claimed: false; error: "invalid_name" | "invalid_hash" | "wrapper_not_found" };

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

  if (!HASH_PATTERN.test(entry.hash)) {
    return { claimed: false, error: "invalid_hash" };
  }

  const buildsDir = deps.buildsDir ?? DEFAULT_BUILDS_DIR;
  const buildDir = join(buildsDir, entry.hash);

  mkdirSync(buildsDir, { recursive: true, mode: 0o700 });

  try {
    mkdirSync(buildDir);
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "EEXIST") {
      return { claimed: false, alreadyClaimed: true };
    }
    throw err;
  }

  writeFileSync(join(buildDir, "snapshot.json"), JSON.stringify(entry));
  writeFileSync(join(buildDir, "prompt.md"), buildPrompt(entry, buildDir));
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
