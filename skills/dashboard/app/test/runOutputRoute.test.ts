import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createRunOutputHandler } from "../src/app/api/run/output/route";
import { appendRun } from "../src/lib/runlog";
import type { RunRecord } from "../src/lib/runlog";

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

const TOKEN = "test-token-abc123";
// 16 lowercase hex chars, matching randomBytes(8).toString("hex") (api/run/route.ts).
const RUN_ID = "0123456789abcdef";

function req(url: string, headers: Record<string, string> = {}): Request {
  return new Request(url, {
    headers: {
      origin: "http://127.0.0.1:3000",
      host: "127.0.0.1:3000",
      ...headers,
    },
  });
}

function makeHandler(overrides: { token?: string; runsDir?: string } = {}) {
  return createRunOutputHandler({
    token: overrides.token ?? TOKEN,
    runsDir: overrides.runsDir ?? tmpDir("run-output-route-"),
  });
}

function writeRunRecord(runsDir: string, outputPath: string, overrides: Partial<RunRecord> = {}): void {
  appendRun(
    {
      runId: RUN_ID,
      button: "wiki-lint",
      argv: [],
      cwd: "/",
      profile: "standard",
      startedAt: 1,
      outputPath,
      ...overrides,
    },
    { runsDir }
  );
}

describe("GET /api/run/output — origin/host wall", () => {
  it("rejects a non-localhost Origin with 403", async () => {
    const handler = makeHandler();
    const res = await handler(req(`http://127.0.0.1:3000/api/run/output?runId=${RUN_ID}&token=${TOKEN}`, { origin: "https://evil.example" }));
    expect(res.status).toBe(403);
  });
});

describe("GET /api/run/output — auth", () => {
  it("rejects a missing token with 401", async () => {
    const handler = makeHandler();
    const res = await handler(req(`http://127.0.0.1:3000/api/run/output?runId=${RUN_ID}`));
    expect(res.status).toBe(401);
  });

  it("rejects a wrong token with 401", async () => {
    const handler = makeHandler();
    const res = await handler(req(`http://127.0.0.1:3000/api/run/output?runId=${RUN_ID}&token=wrong`));
    expect(res.status).toBe(401);
  });
});

describe("GET /api/run/output — runId validation", () => {
  it("rejects a runId that isn't 16 lowercase hex chars with 400, without touching the filesystem", async () => {
    const runsDir = tmpDir("run-output-route-");
    const handler = makeHandler({ runsDir });
    const res = await handler(req(`http://127.0.0.1:3000/api/run/output?runId=../../../../etc/passwd&token=${TOKEN}`));
    expect(res.status).toBe(400);
  });

  it("rejects an uppercase-hex runId with 400 (exact charset, not case-insensitive)", async () => {
    const handler = makeHandler();
    const res = await handler(req(`http://127.0.0.1:3000/api/run/output?runId=${RUN_ID.toUpperCase()}&token=${TOKEN}`));
    expect(res.status).toBe(400);
  });

  it("rejects a too-short hex runId with 400", async () => {
    const handler = makeHandler();
    const res = await handler(req(`http://127.0.0.1:3000/api/run/output?runId=abc123&token=${TOKEN}`));
    expect(res.status).toBe(400);
  });

  it("rejects a missing runId with 400", async () => {
    const handler = makeHandler();
    const res = await handler(req(`http://127.0.0.1:3000/api/run/output?token=${TOKEN}`));
    expect(res.status).toBe(400);
  });
});

describe("GET /api/run/output — lookup and read", () => {
  it("returns 404 for a well-formed but unknown runId (no matching record in runs.jsonl)", async () => {
    const runsDir = tmpDir("run-output-route-");
    const handler = makeHandler({ runsDir });
    const res = await handler(req(`http://127.0.0.1:3000/api/run/output?runId=${RUN_ID}&token=${TOKEN}`));
    expect(res.status).toBe(404);
  });

  it("reads the run's own recorded outputPath (server-controlled, never client-supplied) and returns its content", async () => {
    const runsDir = tmpDir("run-output-route-");
    const logPath = join(runsDir, `${RUN_ID}.log`);
    writeFileSync(logPath, "hello from the log\n");
    writeRunRecord(runsDir, logPath, { endedAt: 100, exitCode: 0 });

    const handler = makeHandler({ runsDir });
    const res = await handler(req(`http://127.0.0.1:3000/api/run/output?runId=${RUN_ID}&token=${TOKEN}`));
    expect(res.status).toBe(200);
    const body = (await res.json()) as { output: string };
    expect(body.output).toBe("hello from the log\n");
  });

  it("returns an empty output string (200) if the record exists but the log file is missing, rather than throwing", async () => {
    const runsDir = tmpDir("run-output-route-");
    const missingPath = join(runsDir, `${RUN_ID}.log`);
    writeRunRecord(runsDir, missingPath, { endedAt: 100, exitCode: 0 });

    const handler = makeHandler({ runsDir });
    const res = await handler(req(`http://127.0.0.1:3000/api/run/output?runId=${RUN_ID}&token=${TOKEN}`));
    expect(res.status).toBe(200);
    const body = (await res.json()) as { output: string };
    expect(body.output).toBe("");
  });

  it("never joins the client-supplied runId directly into a filesystem path — a path-traversal-shaped runId is rejected by the format check before any lookup", async () => {
    // Negative control for the security property: even if an attacker's runId happened to
    // collide with RUN_ID_PATTERN by some other means, this route only ever reads
    // RunRecord.outputPath (written by api/run/route.ts itself), never
    // join(runsDir, `${runId}.log`) built from the request. Checked directly against the
    // executable source (comments stripped) rather than just the behavioral 404 case above,
    // since a future refactor could add a join(...runId...) code path that still happens to
    // pass every behavioral test here (e.g. an added debug/fallback branch).
    const raw = await import("node:fs").then((fs) => fs.readFileSync(new URL("../src/app/api/run/output/route.ts", import.meta.url), "utf-8"));
    const withoutComments = raw.replace(/\/\/.*$/gm, "").replace(/\/\*[\s\S]*?\*\//g, "");
    expect(withoutComments).not.toMatch(/join\([^)]*runId/);
  });
});
