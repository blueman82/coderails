import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { mkdtempSync, rmSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { runClaude, resolveClaudePath, DEFAULT_TIMEOUT_MS } from "../src/exec.ts";

describe("resolveClaudePath", () => {
  it("returns an absolute path", () => {
    const path = resolveClaudePath();
    expect(path.startsWith("/")).toBe(true);
  });
});

describe("runClaude", () => {
  it("invokes execFile with the exact argv and cwd given, using the resolved absolute claude path", () => {
    const execFileImpl = vi.fn((command, args, options, callback) => {
      callback(null, "stdout output", "");
    });
    return runClaude(["-p", "/coderails:wiki-lint"], "/some/cwd", {
      claudePath: "/opt/homebrew/bin/claude",
      execFileImpl,
    }).then((result) => {
      expect(execFileImpl).toHaveBeenCalledWith(
        "/opt/homebrew/bin/claude",
        ["-p", "/coderails:wiki-lint"],
        { cwd: "/some/cwd", timeout: DEFAULT_TIMEOUT_MS, killSignal: "SIGKILL" },
        expect.any(Function)
      );
      expect(result.exitCode).toBe(0);
      expect(result.stdout).toBe("stdout output");
    });
  });

  // execFile's default stdio gives the child a PIPE for stdin that the parent
  // never writes to and never closes. The claude CLI waits on it and, after 3
  // seconds, emits "Warning: no stdin data received in 3s, proceeding without
  // it" — a mandatory ~3s stall on every scheduled routine run. Note the
  // `stdio` OPTION cannot fix this: execFile silently drops it and always
  // pipes all three fds. The only working mechanism is ending the returned
  // child's stdin, which is what this pins.
  it("ends the spawned child's stdin so the CLI does not wait 3s on an unwritten pipe", () => {
    const end = vi.fn();
    const execFileImpl = vi.fn((command, args, options, callback) => {
      callback(null, "stdout output", "");
      return { stdin: { end } };
    });
    return runClaude(["-p", "/x"], "/cwd", {
      claudePath: "/opt/homebrew/bin/claude",
      execFileImpl,
    }).then((result) => {
      expect(end).toHaveBeenCalled();
      // stdout/stderr capture must be untouched by the stdin change.
      expect(result.stdout).toBe("stdout output");
    });
  });

  // The mock test above pins the MECHANISM (".end() was called on the object
  // we handed back") but cannot guard the BEHAVIOUR: an earlier attempted fix
  // (`stdio: ["ignore","pipe","pipe"]`) made a mock test pass while the real
  // stall persisted, because execFile silently DROPS the stdio option. Only a
  // real spawned child that reads stdin can catch that class of regression.
  // /bin/cat reads stdin until EOF: with the fix it gets EOF at once and exits
  // 0; without it, it blocks until timeoutMs and comes back spawnFailure
  // "timeout". No wall-clock assertion — the ExecResult alone discriminates.
  it("really closes a spawned process's stdin — /bin/cat exits 0 instead of blocking (real execFile, no mock)", () => {
    return runClaude([], "/tmp", {
      claudePath: "/bin/cat",
      // 3s, comfortably under vitest's 5s default test timeout, so a
      // regression fails on the honest assertion (spawnFailure "timeout")
      // rather than on the runner giving up first.
      timeoutMs: 3000,
    }).then((result) => {
      expect(result.spawnFailure).toBeUndefined();
      expect(result.exitCode).toBe(0);
    });
  });

  it("does not throw when the injected execFileImpl returns no child object", () => {
    const execFileImpl = vi.fn((command, args, options, callback) => {
      callback(null, "out", "");
    });
    return runClaude(["-p", "/x"], "/cwd", {
      claudePath: "/opt/homebrew/bin/claude",
      execFileImpl,
    }).then((result) => {
      expect(result.exitCode).toBe(0);
      expect(result.stdout).toBe("out");
    });
  });

  it("resolves with a nonzero exitCode and stderr when the child process errors", () => {
    const execFileImpl = vi.fn((command, args, options, callback) => {
      const err = Object.assign(new Error("boom"), { code: 1 });
      callback(err, "", "stderr output");
    });
    return runClaude(["-p", "/x"], "/cwd", {
      claudePath: "/opt/homebrew/bin/claude",
      execFileImpl,
    }).then((result) => {
      expect(result.exitCode).toBe(1);
      expect(result.stderr).toBe("stderr output");
    });
  });

  it("defaults to exitCode 1 when the error has no numeric code", () => {
    const execFileImpl = vi.fn((command, args, options, callback) => {
      callback(new Error("boom"), "", "");
    });
    return runClaude(["-p", "/x"], "/cwd", {
      claudePath: "/opt/homebrew/bin/claude",
      execFileImpl,
    }).then((result) => {
      expect(result.exitCode).toBe(1);
    });
  });

  it("resolves with spawnFailure 'timeout' when the process is killed by SIGKILL after exceeding timeoutMs (B4)", () => {
    const execFileImpl = vi.fn((command, args, options, callback) => {
      const err = Object.assign(new Error("killed"), { killed: true, signal: "SIGKILL" });
      callback(err, "partial stdout", "");
    });
    return runClaude(["-p", "/x"], "/cwd", {
      claudePath: "/opt/homebrew/bin/claude",
      execFileImpl,
      timeoutMs: 5,
    }).then((result) => {
      expect(result.spawnFailure).toBe("timeout");
      expect(result.spawnFailureReason).toMatch(/timeout/i);
      expect(result.exitCode).not.toBe(0);
    });
  });

  it("passes timeoutMs and killSignal SIGKILL to execFile (B4)", () => {
    const execFileImpl = vi.fn((command, args, options, callback) => {
      callback(null, "", "");
    });
    return runClaude(["-p", "/x"], "/cwd", {
      claudePath: "/opt/homebrew/bin/claude",
      execFileImpl,
      timeoutMs: 42,
    }).then(() => {
      expect(execFileImpl).toHaveBeenCalledWith(
        "/opt/homebrew/bin/claude",
        ["-p", "/x"],
        expect.objectContaining({ timeout: 42, killSignal: "SIGKILL" }),
        expect.any(Function)
      );
    });
  });

  it("resolves with spawnFailure 'spawn-failed' and an honest reason when resolveClaudePath throws (B4)", () => {
    const execFileImpl = vi.fn();
    const resolveClaudePathImpl = () => {
      throw new Error("resolveClaudePath: no claude binary found at any known path");
    };
    return runClaude(["-p", "/x"], "/cwd", { execFileImpl, resolveClaudePathImpl }).then((result) => {
      expect(result.spawnFailure).toBe("spawn-failed");
      expect(result.spawnFailureReason).toMatch(/no claude binary found/i);
      expect(execFileImpl).not.toHaveBeenCalled();
    });
  });

  it("resolves with spawnFailure 'spawn-failed' distinct from exec-error when execFile itself fails to spawn (e.g. ENOENT cwd) (B4)", () => {
    const execFileImpl = vi.fn((command, args, options, callback) => {
      const err = Object.assign(new Error("spawn claude ENOENT"), { code: "ENOENT" });
      callback(err, "", "");
    });
    return runClaude(["-p", "/x"], "/nonexistent-cwd", {
      claudePath: "/opt/homebrew/bin/claude",
      execFileImpl,
    }).then((result) => {
      expect(result.spawnFailure).toBe("spawn-failed");
      expect(result.spawnFailureReason).toContain("ENOENT");
    });
  });

  it("never receives a shell-interpolated string — argv is passed as a discrete array", () => {
    const execFileImpl = vi.fn((command, args, options, callback) => {
      expect(Array.isArray(args)).toBe(true);
      callback(null, "", "");
    });
    return runClaude(["-p", "/x", "--", "; rm -rf /"], "/cwd", {
      claudePath: "/opt/homebrew/bin/claude",
      execFileImpl,
    }).then(() => {
      expect(execFileImpl).toHaveBeenCalled();
    });
  });
});

// The motivating gap: a scheduled routine that runs RED left no transcript
// on disk because runClaude returned stdout/stderr in-memory only (never
// wrote the outputPath the sweeper had already recorded in the run ledger).
// This mirrors route.ts, which persists the run's output to its outputPath.
describe("runClaude output persistence", () => {
  let dir: string;

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "exec-output-"));
  });

  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  it("writes final stdout and stderr to outputPath once the run settles successfully", () => {
    const outputPath = join(dir, "run.log");
    const execFileImpl = vi.fn((command, args, options, callback) => {
      callback(null, "hello from stdout", "a warning on stderr");
    });
    return runClaude(["-p", "/x"], "/cwd", {
      claudePath: "/opt/homebrew/bin/claude",
      execFileImpl,
      outputPath,
    }).then((result) => {
      expect(existsSync(outputPath)).toBe(true);
      const content = readFileSync(outputPath, "utf-8");
      expect(content).toContain("hello from stdout");
      expect(content).toContain("a warning on stderr");
      expect(result.stdout).toBe("hello from stdout");
    });
  });

  it("persists output to outputPath even when the run exits non-zero — the RED-routine diagnosability case", () => {
    const outputPath = join(dir, "run.log");
    const execFileImpl = vi.fn((command, args, options, callback) => {
      const err = Object.assign(new Error("boom"), { code: 2 });
      callback(err, "partial work before failing", "the failure reason on stderr");
    });
    return runClaude(["-p", "/x"], "/cwd", {
      claudePath: "/opt/homebrew/bin/claude",
      execFileImpl,
      outputPath,
    }).then((result) => {
      expect(result.exitCode).toBe(2);
      const content = readFileSync(outputPath, "utf-8");
      expect(content).toContain("partial work before failing");
      expect(content).toContain("the failure reason on stderr");
    });
  });

  it("creates the outputPath parent directory if it does not yet exist", () => {
    const outputPath = join(dir, "nested", "deeper", "run.log");
    const execFileImpl = vi.fn((command, args, options, callback) => {
      callback(null, "output", "");
    });
    return runClaude(["-p", "/x"], "/cwd", {
      claudePath: "/opt/homebrew/bin/claude",
      execFileImpl,
      outputPath,
    }).then(() => {
      expect(existsSync(outputPath)).toBe(true);
      expect(readFileSync(outputPath, "utf-8")).toContain("output");
    });
  });

  it("does not write any file when outputPath is omitted (backward compatible)", () => {
    const execFileImpl = vi.fn((command, args, options, callback) => {
      callback(null, "output", "");
    });
    return runClaude(["-p", "/x"], "/cwd", {
      claudePath: "/opt/homebrew/bin/claude",
      execFileImpl,
    }).then((result) => {
      expect(result.stdout).toBe("output");
      // No outputPath supplied → nothing written; dir stays empty.
      expect(existsSync(join(dir, "run.log"))).toBe(false);
    });
  });

  // The two tests below pin persistence on the SIGKILL-timeout and
  // spawn-failure settle paths. The B4 tests above cover those paths'
  // ExecResult but supply no outputPath, so before these existed, MOVING the
  // persistOutput call to after either early-return broke persistence on that
  // path with the whole suite still green. A long-running scheduled routine
  // going RED by timeout is the motivating case for this feature, so the
  // timeout path is exactly where a silent regression would hurt most.
  it("persists partial output on the SIGKILL-timeout settle path", () => {
    const outputPath = join(dir, "run.log");
    const execFileImpl = vi.fn((command, args, options, callback) => {
      const err = Object.assign(new Error("killed"), { killed: true, signal: "SIGKILL" });
      callback(err, "partial stdout", "stderr before kill");
    });
    return runClaude(["-p", "/x"], "/cwd", {
      claudePath: "/opt/homebrew/bin/claude",
      execFileImpl,
      timeoutMs: 5,
      outputPath,
    }).then((result) => {
      expect(result.spawnFailure).toBe("timeout");
      expect(existsSync(outputPath)).toBe(true);
      const content = readFileSync(outputPath, "utf-8");
      expect(content).toContain("partial stdout");
      expect(content).toContain("stderr before kill");
    });
  });

  it("persists whatever was captured on the ENOENT spawn-failure settle path", () => {
    const outputPath = join(dir, "run.log");
    const execFileImpl = vi.fn((command, args, options, callback) => {
      const err = Object.assign(new Error("spawn claude ENOENT"), { code: "ENOENT" });
      callback(err, "", "spawn diagnostics on stderr");
    });
    return runClaude(["-p", "/x"], "/nonexistent-cwd", {
      claudePath: "/opt/homebrew/bin/claude",
      execFileImpl,
      outputPath,
    }).then((result) => {
      expect(result.spawnFailure).toBe("spawn-failed");
      expect(existsSync(outputPath)).toBe(true);
      expect(readFileSync(outputPath, "utf-8")).toContain("spawn diagnostics on stderr");
    });
  });

  // persistOutput swallows its own write failures by design: losing a
  // transcript must never mask or discard the ExecResult the caller needs to
  // gate the run. That contract lived only in a prose comment — deleting the
  // try/catch entirely, so a write failure rejects the promise, left the
  // suite green. This pins it.
  it("still resolves with the real ExecResult when the transcript write fails", () => {
    // Parent of outputPath is a regular FILE, so mkdirSync throws ENOTDIR.
    const blocker = join(dir, "blocker");
    writeFileSync(blocker, "not a directory");
    const outputPath = join(blocker, "run.log");
    const execFileImpl = vi.fn((command, args, options, callback) => {
      callback(null, "real stdout", "");
    });
    return runClaude(["-p", "/x"], "/cwd", {
      claudePath: "/opt/homebrew/bin/claude",
      execFileImpl,
      outputPath,
    }).then((result) => {
      // The write failed, but the run's own outcome is intact and unmasked.
      expect(result.exitCode).toBe(0);
      expect(result.stdout).toBe("real stdout");
      expect(existsSync(outputPath)).toBe(false);
    });
  });
});
