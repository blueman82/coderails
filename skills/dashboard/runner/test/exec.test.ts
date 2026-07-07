import { describe, it, expect, vi } from "vitest";
import { runClaude, resolveClaudePath } from "../src/exec.ts";

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
        { cwd: "/some/cwd" },
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
