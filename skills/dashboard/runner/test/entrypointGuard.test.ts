// Regression test for the entrypoint guard bug found by the E2 cold-read
// eval: `import.meta.url === \`file://${process.argv[1]}\`` compares a
// realpath-resolved URL (import.meta.url always resolves through the
// filesystem) against process.argv[1] verbatim (whatever path string was
// typed on the command line). When the two differ — e.g. invoked through a
// symlink, or simply because the invocation path traverses a symlinked
// directory such as macOS's /var -> /private/var — the comparison silently
// fails and the entrypoint no-ops: exit 0, zero output, nothing run. This
// spawns each entrypoint as a real child process (not an in-process import)
// through a symlink to prove the fix actually executes at runtime, not just
// that the guard's string comparison changed.
import { describe, it, expect, beforeAll, afterAll } from "vitest";
import { execFileSync } from "node:child_process";
import { mkdtempSync, mkdirSync, symlinkSync, rmSync, writeFileSync, realpathSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const runnerDir = join(__dirname, "..");

let symlinkDir: string;
let fakeHome: string;

beforeAll(() => {
  // A symlink to the runner package directory, placed under a fresh tmp
  // root so the symlink hop is unambiguous (distinct from any incidental
  // /var -> /private/var hop the real path might already have).
  const linkParent = mkdtempSync(join(tmpdir(), "coderails-entrypoint-link-"));
  symlinkDir = join(linkParent, "runner-link");
  symlinkSync(runnerDir, symlinkDir);

  // Isolated HOME with a minimal dashboard config so run() doesn't touch
  // (or require) the real machine's ~/.claude/coderails-dashboard.json.
  fakeHome = mkdtempSync(join(tmpdir(), "coderails-entrypoint-home-"));
  mkdirSync(join(fakeHome, ".claude"), { recursive: true });
  writeFileSync(
    join(fakeHome, ".claude", "coderails-dashboard.json"),
    JSON.stringify({ repos: [], wikiPaths: [], memoryPaths: [], buttons: [], routines: [] })
  );
});

afterAll(() => {
  rmSync(dirname(symlinkDir), { recursive: true, force: true });
  rmSync(fakeHome, { recursive: true, force: true });
});

function runEntrypoint(scriptRelPath: string, viaSymlink: boolean): { stdout: string; exitCode: number } {
  const base = viaSymlink ? symlinkDir : runnerDir;
  const scriptPath = join(base, scriptRelPath);
  try {
    const stdout = execFileSync(process.execPath, ["--experimental-strip-types", scriptPath], {
      cwd: base,
      env: { ...process.env, HOME: fakeHome },
      encoding: "utf-8",
    });
    return { stdout, exitCode: 0 };
  } catch (err) {
    const e = err as { stdout?: string; status?: number | null };
    return { stdout: e.stdout ?? "", exitCode: e.status ?? 1 };
  }
}

describe("entrypoint guard: runs when invoked through a symlinked path", () => {
  it("main.ts sweeps and prints output via a symlinked invocation path", () => {
    const result = runEntrypoint("src/main.ts", true);
    expect(result.stdout).toContain("Sweep complete");
    expect(result.exitCode).toBe(0);
  });

  it("main.ts sweeps and prints output via its real (non-symlinked) path — control", () => {
    const result = runEntrypoint("src/main.ts", false);
    expect(result.stdout).toContain("Sweep complete");
    expect(result.exitCode).toBe(0);
  });

  it("seedMain.ts seeds and prints output via a symlinked invocation path", () => {
    const result = runEntrypoint("src/seedMain.ts", true);
    expect(result.stdout).toContain("Seed complete");
    expect(result.exitCode).toBe(0);
  });

  it("seedMain.ts seeds and prints output via its real (non-symlinked) path — control", () => {
    const result = runEntrypoint("src/seedMain.ts", false);
    expect(result.stdout).toContain("Seed complete");
    expect(result.exitCode).toBe(0);
  });

  it("sanity: the symlink used above really is a symlink to a different path than its realpath", () => {
    expect(realpathSync(symlinkDir)).not.toBe(symlinkDir);
  });
});
