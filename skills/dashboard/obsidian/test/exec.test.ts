import { describe, it, expect, vi, beforeEach } from "vitest";
import { pressButton } from "../src/exec";
import type { ExecDeps, VaultNote } from "../src/exec";
import type { ButtonItem } from "../src/render";

const BUTTONS: ButtonItem[] = [
  {
    name: "wiki-lint",
    label: "WIKI LINT",
    command: "/coderails:wiki-lint",
    cwd: "/Users/harrison/Github/coderails",
    profile: "standard",
  },
  {
    name: "sync-docs",
    label: "SYNC DOCS",
    command: "/coderails:sync-docs",
    cwd: "/Users/harrison/Github/coderails",
    profile: "read-only",
  },
  {
    name: "ask",
    label: "ASK",
    command: "/coderails:ask",
    cwd: "/Users/harrison/Github/coderails",
    profile: "standard",
    inputAllowed: true,
  },
];

function makeDeps(overrides: Partial<ExecDeps> = {}): ExecDeps {
  const writtenIntents: Array<{ path: string; data: string; mode?: number }> = [];
  const mkdirCalls: Array<{ path: string; mode?: number }> = [];
  const notes = new Map<string, VaultNote>();

  const deps: ExecDeps = {
    mkdirIntentDir: vi.fn((path: string) => {
      mkdirCalls.push({ path, mode: 0o700 });
    }),
    writeIntentFile: vi.fn((path: string, data: string) => {
      writtenIntents.push({ path, data });
    }),
    findUnresolvedRun: vi.fn(() => null),
    createRunNote: vi.fn(async (_path: string, _content: string) => {
      /* no-op default */
    }),
    modifyRunNote: vi.fn(async (_path: string, _content: string) => {
      /* no-op default */
    }),
    execFile: vi.fn((_cmd, _args, _opts, callback) => {
      callback(null, "output", "");
    }),
    now: () => 1751000000000,
    randomRunId: () => "abc12345",
    ...overrides,
  };

  return deps;
}

describe("pressButton — intent file", () => {
  it("writes exactly one intent file with the declared shape on a single press", async () => {
    const writeIntentFile = vi.fn();
    const deps = makeDeps({ writeIntentFile });

    await pressButton(deps, BUTTONS, "wiki-lint");

    expect(writeIntentFile).toHaveBeenCalledTimes(1);
    const [path, data] = writeIntentFile.mock.calls[0];
    expect(path).toContain("abc12345.json");
    expect(path).toContain("queue");
    const parsed = JSON.parse(data);
    expect(parsed).toEqual({
      button: "wiki-lint",
      requestedAt: 1751000000000,
      source: "obsidian",
    });
  });

  it("includes input in the intent file when provided", async () => {
    const writeIntentFile = vi.fn();
    const deps = makeDeps({ writeIntentFile });

    await pressButton(deps, BUTTONS, "ask", "what's next");

    const [, data] = writeIntentFile.mock.calls[0];
    const parsed = JSON.parse(data);
    expect(parsed.input).toBe("what's next");
  });

  it("creates the queue directory before writing the intent", async () => {
    const calls: string[] = [];
    const deps = makeDeps({
      mkdirIntentDir: vi.fn((p: string) => calls.push(`mkdir:${p}`)),
      writeIntentFile: vi.fn((p: string) => calls.push(`write:${p}`)),
    });

    await pressButton(deps, BUTTONS, "wiki-lint");

    expect(calls[0]).toMatch(/^mkdir:/);
    expect(calls[1]).toMatch(/^write:/);
  });
});

describe("pressButton — undeclared button", () => {
  it("never spawns and reports an error for a button not in the declared config", async () => {
    const execFile = vi.fn();
    const writeIntentFile = vi.fn();
    const deps = makeDeps({ execFile, writeIntentFile });

    const result = await pressButton(deps, BUTTONS, "not-a-real-button");

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reason).toBe("undeclared");
    }
    expect(execFile).not.toHaveBeenCalled();
    expect(writeIntentFile).not.toHaveBeenCalled();
  });
});

describe("pressButton — unresolved previous run", () => {
  it("rejects a press when that button's previous run is still unresolved", async () => {
    const execFile = vi.fn();
    const writeIntentFile = vi.fn();
    const deps = makeDeps({
      findUnresolvedRun: vi.fn(() => ({ notePath: "dashboard-runs/2026-07-06-wiki-lint.md" })),
      execFile,
      writeIntentFile,
    });

    const result = await pressButton(deps, BUTTONS, "wiki-lint");

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reason).toBe("unresolved");
    }
    expect(execFile).not.toHaveBeenCalled();
    expect(writeIntentFile).not.toHaveBeenCalled();
  });

  it("only checks unresolved runs for the pressed button, not other buttons", async () => {
    const findUnresolvedRun = vi.fn((name: string) => (name === "sync-docs" ? { notePath: "x" } : null));
    const deps = makeDeps({ findUnresolvedRun });

    const result = await pressButton(deps, BUTTONS, "wiki-lint");

    expect(result.ok).toBe(true);
    expect(findUnresolvedRun).toHaveBeenCalledWith("wiki-lint");
  });
});

describe("pressButton — client-side dash rejection", () => {
  it("rejects input starting with '-' before ever touching fs or spawning", async () => {
    const execFile = vi.fn();
    const writeIntentFile = vi.fn();
    const deps = makeDeps({ execFile, writeIntentFile });

    const result = await pressButton(deps, BUTTONS, "ask", "--dangerously-skip-permissions");

    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.reason).toBe("invalid-input");
    }
    expect(execFile).not.toHaveBeenCalled();
    expect(writeIntentFile).not.toHaveBeenCalled();
  });
});

describe("pressButton — run note lifecycle", () => {
  it("creates a run note with status: running before spawning, then flips to done on success", async () => {
    let runningContent = "";
    let finalContent = "";
    const createRunNote = vi.fn(async (_path: string, content: string) => {
      runningContent = content;
    });
    const modifyRunNote = vi.fn(async (_path: string, content: string) => {
      finalContent = content;
    });
    const execFile = vi.fn((_cmd, _args, _opts, callback) => {
      expect(runningContent).toContain("status: running");
      callback(null, "all good", "");
    });
    const deps = makeDeps({ createRunNote, modifyRunNote, execFile });

    const result = await pressButton(deps, BUTTONS, "wiki-lint");

    expect(result.ok).toBe(true);
    expect(createRunNote).toHaveBeenCalledTimes(1);
    expect(modifyRunNote).toHaveBeenCalledTimes(1);
    expect(finalContent).toContain("status: done");
    expect(finalContent).toContain("exitCode: 0");
  });

  it("flips the run note to failed with a non-zero exit code on failure", async () => {
    let finalContent = "";
    const modifyRunNote = vi.fn(async (_path: string, content: string) => {
      finalContent = content;
    });
    const execFile = vi.fn((_cmd, _args, _opts, callback) => {
      const err = Object.assign(new Error("boom"), { code: 1 });
      callback(err, "", "some stderr");
    });
    const deps = makeDeps({ modifyRunNote, execFile });

    const result = await pressButton(deps, BUTTONS, "wiki-lint");

    expect(result.ok).toBe(true);
    expect(finalContent).toContain("status: failed");
    expect(finalContent).toContain("exitCode: 1");
  });

  it("names the run note dashboard-runs/<date>-<button>.md", async () => {
    let notePath = "";
    const createRunNote = vi.fn(async (path: string) => {
      notePath = path;
    });
    const deps = makeDeps({ createRunNote, now: () => new Date("2026-07-06T12:00:00Z").getTime() });

    await pressButton(deps, BUTTONS, "wiki-lint");

    expect(notePath).toBe("dashboard-runs/2026-07-06-wiki-lint.md");
  });

  it("includes a duration in the final frontmatter", async () => {
    let finalContent = "";
    const modifyRunNote = vi.fn(async (_path: string, content: string) => {
      finalContent = content;
    });
    let call = 0;
    const now = vi.fn(() => {
      call += 1;
      return call === 1 ? 1000 : 1500;
    });
    const deps = makeDeps({ modifyRunNote, now });

    await pressButton(deps, BUTTONS, "wiki-lint");

    expect(finalContent).toContain("duration:");
  });
});

describe("pressButton — argv parity with Task 7's buildArgv", () => {
  it("passes the standard-profile argv exactly as buildArgv would produce it", async () => {
    const execFile = vi.fn((_cmd: string, args: string[], _opts, callback) => {
      expect(args).toEqual(["-p", "/coderails:wiki-lint"]);
      callback(null, "", "");
    });
    const deps = makeDeps({ execFile });

    await pressButton(deps, BUTTONS, "wiki-lint");
    expect(execFile).toHaveBeenCalledTimes(1);
  });

  it("passes the read-only-profile argv with --allowedTools", async () => {
    const execFile = vi.fn((_cmd: string, args: string[], _opts, callback) => {
      expect(args).toEqual(["-p", "/coderails:sync-docs", "--allowedTools", "Read", "Grep", "Glob"]);
      callback(null, "", "");
    });
    const deps = makeDeps({ execFile });

    await pressButton(deps, BUTTONS, "sync-docs");
  });

  it("passes input with the -- sentinel for an inputAllowed button", async () => {
    const execFile = vi.fn((_cmd: string, args: string[], _opts, callback) => {
      expect(args).toEqual(["-p", "/coderails:ask", "--", "hello"]);
      callback(null, "", "");
    });
    const deps = makeDeps({ execFile });

    await pressButton(deps, BUTTONS, "ask", "hello");
  });

  it("uses the button's cwd for execFile", async () => {
    const execFile = vi.fn((_cmd: string, _args, opts: { cwd: string }, callback) => {
      expect(opts.cwd).toBe("/Users/harrison/Github/coderails");
      callback(null, "", "");
    });
    const deps = makeDeps({ execFile });

    await pressButton(deps, BUTTONS, "wiki-lint");
  });

  it("invokes execFile with the literal command 'claude'", async () => {
    const execFile = vi.fn((cmd: string, _args, _opts, callback) => {
      expect(cmd).toBe("claude");
      callback(null, "", "");
    });
    const deps = makeDeps({ execFile });

    await pressButton(deps, BUTTONS, "wiki-lint");
  });
});
