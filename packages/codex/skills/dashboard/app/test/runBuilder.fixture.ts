import { afterEach } from "vitest";

import { mkdtempSync, writeFileSync, readFileSync, rmSync, chmodSync, mkdirSync } from "node:fs";

import { execFileSync } from "node:child_process";

import { tmpdir } from "node:os";

import { join } from "node:path";

import { createHash } from "node:crypto";

const SCRIPT_PATH = join(__dirname, "..", "..", "scripts", "run_builder.py");

const tmpDirs: string[] = [];

function tmpDir(prefix: string): string {
  const dir = mkdtempSync(join(tmpdir(), prefix));
  tmpDirs.push(dir);
  return dir;
}

afterEach(() => {
  for (const dir of tmpDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

function readState(buildDir: string): Record<string, unknown> {
  return JSON.parse(readFileSync(join(buildDir, "state.json"), "utf-8"));
}

function makeBuildDir(): string {
  const dir = tmpDir("dashboard-run-builder-");
  writeFileSync(
    join(dir, "state.json"),
    JSON.stringify({ schemaVersion: 1, hash: "unset", state: "claimed" })
  );
  return dir;
}

// Hash the sorted compact JSON snapshot, matching the native wrapper contract.
function computeHash(toolInput: unknown): string {
  const canonical = JSON.stringify(sortKeysDeep(toolInput));
  return createHash("sha256").update(canonical).digest("hex");
}

// Sort object keys recursively before compact JSON serialization.
function sortKeysDeep(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeysDeep);
  if (value !== null && typeof value === "object") {
    const sorted: Record<string, unknown> = {};
    for (const key of Object.keys(value as Record<string, unknown>).sort()) {
      sorted[key] = sortKeysDeep((value as Record<string, unknown>)[key]);
    }
    return sorted;
  }
  return value;
}

function writeSnapshot(
  buildDir: string,
  overrides: Record<string, unknown> = {}
): { hash: string; toolInput: unknown } {
  const toolInput = overrides.toolInput ?? { proposed_name: "x" };
  const hash = (overrides.hash as string | undefined) ?? computeHash(toolInput);
  const snapshot = Object.assign({
    hash,
    toolName: "workflow-audit:propose-skill",
    toolInput,
    createdAt: 1_720_000_000_000,
    status: "approved",
  }, overrides);
  writeFileSync(join(buildDir, "snapshot.json"), JSON.stringify(snapshot));
  return { hash: snapshot.hash as string, toolInput: snapshot.toolInput };
}

function makeRepoFixture(): string {
  // The wrapper runs `git fetch origin` and `worktree add ... origin/main`,
  // matching real production topology (a real clone with an origin
  // remote) — so the fixture needs a bare "origin" repo, not just a lone
  // working copy with no remote.
  const bareDir = tmpDir("dashboard-run-builder-bare-");
  execFileSync("git", ["init", "-q", "--bare", bareDir]);

  const repoDir = tmpDir("dashboard-run-builder-repo-");
  execFileSync("git", ["init", "-q", repoDir]);
  execFileSync("git", ["-C", repoDir, "config", "user.email", "test@example.com"]);
  execFileSync("git", ["-C", repoDir, "config", "user.name", "Test"]);
  mkdirSync(join(repoDir, "packages", "codex", ".codex-plugin"), { recursive: true });
  writeFileSync(
    join(repoDir, "packages", "codex", ".codex-plugin", "plugin.json"),
    JSON.stringify({ name: "coderails-codex" }),
  );
  execFileSync("git", ["-C", repoDir, "add", "packages/codex/.codex-plugin/plugin.json"]);
  execFileSync("git", ["-C", repoDir, "commit", "-q", "-m", "init"]);
  execFileSync("git", ["-C", repoDir, "branch", "-M", "main"]);
  execFileSync("git", ["-C", repoDir, "remote", "add", "origin", bareDir]);
  execFileSync("git", ["-C", repoDir, "push", "-q", "origin", "main"]);
  return repoDir;
}

interface StubOptions {
  argvLog?: string;
  argvLines?: boolean;
  outputs?: Record<string, string>;
  stderr?: string;
  exitCode?: number;
  sleepSeconds?: number;
}

function makeStubCodexBin(options: StubOptions): string {
  const binDir = tmpDir("dashboard-run-builder-stubbin-");
  const stubPath = join(binDir, "codex");
  const script = `#!/usr/bin/env python3
import json
import sys
import time
from pathlib import Path
if sys.argv[1:] == ["--version"]:
    print("stub-codex 0.0.0")
    raise SystemExit(0)
options = json.loads(${JSON.stringify(JSON.stringify(options))})
if "argvLog" in options:
    separator = "\\n" if options.get("argvLines") else " "
    with Path(options["argvLog"]).open("a") as stream:
        stream.write(separator.join(sys.argv[1:]) + "\\n")
time.sleep(options.get("sleepSeconds", 0))
for path, content in options.get("outputs", {}).items():
    Path(path).write_text(content)
if "stderr" in options:
    print(options["stderr"], file=sys.stderr)
raise SystemExit(options.get("exitCode", 0))
`;
  writeFileSync(stubPath, script);
  chmodSync(stubPath, 0o755);
  return binDir;
}

function runWrapper(
  buildDir: string,
  env: Record<string, string> = {}
): { status: number } {
  try {
    execFileSync("python3", [SCRIPT_PATH, buildDir], {
      env: { ...process.env, ...env },
      // "ignore" (not "pipe"): the wrapper's own heartbeat/watchdog run as
      // detached background subshells that inherit stdio file descriptors.
      // With "pipe", Node's execFileSync waits for those inherited pipe FDs
      // to close (EOF), not just for this child to exit — since the
      // subshells only die from the wrapper's own kill in its EXIT trap,
      // that race can leave the pipe open well past the wrapper's real
      // completion. "ignore" avoids creating a pipe to wait on at all.
      stdio: "ignore",
    });
    return { status: 0 };
  } catch (err) {
    const e = err as { status: number | null };
    return { status: e.status ?? 1 };
  }
}

export { SCRIPT_PATH, tmpDir, readState, makeBuildDir, computeHash, writeSnapshot, makeRepoFixture, makeStubCodexBin, runWrapper };
