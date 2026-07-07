import { describe, it, expect, vi } from "vitest";
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
