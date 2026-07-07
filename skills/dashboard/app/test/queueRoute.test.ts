import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, writeFileSync, readFileSync, existsSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createQueueActionHandler } from "../src/app/api/queue/route";
import type { ClaimAndSpawnBuildResult } from "../src/lib/build/spawn";

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

// 64-char hex strings, matching the frozen contract's "sha256(...), hex" shape.
const HASH_A = "a".repeat(64);
const HASH_B = "b".repeat(64);
const HASH_X = "1".repeat(64);
const HASH_Y = "2".repeat(64);
const HASH_C = "c".repeat(64);
const HASH_UNKNOWN = "d".repeat(64);

function writeEntry(dir: string, hash: string, overrides: Record<string, unknown> = {}): string {
  const path = join(dir, `${hash}.json`);
  writeFileSync(
    path,
    JSON.stringify({
      hash,
      toolName: "mcp__claude_ai_Slack__slack_send_message",
      toolInput: { channel: "#general" },
      createdAt: 1_720_000_000_000,
      status: "pending",
      ...overrides,
    })
  );
  return path;
}

function makeHandler(
  overrides: {
    token?: string;
    queueDir?: string;
    claimAndSpawnBuild?: (entry: {
      hash: string;
      toolName: string;
      toolInput: unknown;
      createdAt: number;
      status: "approved" | "denied";
    }) => ClaimAndSpawnBuildResult;
  } = {}
) {
  const queueDir = overrides.queueDir ?? tmpDir("dashboard-queue-route-");
  const handler = createQueueActionHandler({
    token: overrides.token ?? TOKEN,
    queueDir,
    claimAndSpawnBuild: overrides.claimAndSpawnBuild,
  });
  return { handler, queueDir };
}

function req(body: unknown, headers: Record<string, string> = {}): Request {
  return new Request("http://127.0.0.1:3000/api/queue", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      origin: "http://127.0.0.1:3000",
      host: "127.0.0.1:3000",
      ...headers,
    },
    body: JSON.stringify(body),
  });
}

describe("POST /api/queue — token/origin", () => {
  it("rejects a missing token with 401 and does not mutate the file", async () => {
    const { handler, queueDir } = makeHandler();
    const path = writeEntry(queueDir, HASH_A);
    const res = await handler(req({ hash: HASH_A, decision: "approved" }));
    expect(res.status).toBe(401);
    expect(JSON.parse(readFileSync(path, "utf-8")).status).toBe("pending");
  });

  it("rejects a wrong token with 401", async () => {
    const { handler } = makeHandler();
    const res = await handler(req({ token: "wrong", hash: HASH_A, decision: "approved" }));
    expect(res.status).toBe(401);
  });

  it("rejects a non-localhost origin with 403", async () => {
    const { handler, queueDir } = makeHandler();
    writeEntry(queueDir, HASH_A);
    const res = await handler(
      req({ token: TOKEN, hash: HASH_A, decision: "approved" }, { origin: "https://evil.example" })
    );
    expect(res.status).toBe(403);
  });

  it("never includes the token in a response body", async () => {
    const { handler } = makeHandler();
    const res = await handler(req({ token: "wrong", hash: HASH_A, decision: "approved" }));
    const text = await res.text();
    expect(text).not.toContain(TOKEN);
  });
});

describe("POST /api/queue — approve/deny", () => {
  it("approves a pending entry via in-place rewrite", async () => {
    const { handler, queueDir } = makeHandler();
    const path = writeEntry(queueDir, HASH_A);
    const res = await handler(req({ token: TOKEN, hash: HASH_A, decision: "approved" }));
    expect(res.status).toBe(200);
    expect(JSON.parse(readFileSync(path, "utf-8")).status).toBe("approved");
  });

  it("denies a pending entry via in-place rewrite", async () => {
    const { handler, queueDir } = makeHandler();
    const path = writeEntry(queueDir, HASH_B);
    const res = await handler(req({ token: TOKEN, hash: HASH_B, decision: "denied" }));
    expect(res.status).toBe(200);
    expect(JSON.parse(readFileSync(path, "utf-8")).status).toBe("denied");
  });

  it("does not bleed through to a different hash in the same dir", async () => {
    const { handler, queueDir } = makeHandler();
    const pathX = writeEntry(queueDir, HASH_X);
    const pathY = writeEntry(queueDir, HASH_Y);
    const res = await handler(req({ token: TOKEN, hash: HASH_X, decision: "approved" }));
    expect(res.status).toBe(200);
    expect(JSON.parse(readFileSync(pathX, "utf-8")).status).toBe("approved");
    expect(JSON.parse(readFileSync(pathY, "utf-8")).status).toBe("pending");
  });

  it("rejects an invalid decision value with 400 and does not mutate the file", async () => {
    const { handler, queueDir } = makeHandler();
    const path = writeEntry(queueDir, HASH_C);
    const res = await handler(req({ token: TOKEN, hash: HASH_C, decision: "expired" }));
    expect(res.status).toBe(400);
    expect(JSON.parse(readFileSync(path, "utf-8")).status).toBe("pending");
  });

  it("rejects a well-formed-but-unknown hash with 404 (unknown queue entry) rather than throwing", async () => {
    const { handler } = makeHandler();
    const res = await handler(req({ token: TOKEN, hash: HASH_UNKNOWN, decision: "approved" }));
    expect(res.status).toBe(404);
  });

  it("rejects a hash that is not well-formed hex-64 with 400, before ever reaching the filesystem", async () => {
    const { handler } = makeHandler();
    const res = await handler(req({ token: TOKEN, hash: "does-not-exist", decision: "approved" }));
    expect(res.status).toBe(400);
  });

  it("rejects a path-traversal-shaped hash with 400 and does not escape queueDir (security)", async () => {
    const { handler, queueDir } = makeHandler();
    // A victim file one level above queueDir that a naive join() would let a ".." hash reach.
    const outsideTarget = join(queueDir, "..", "victim.json");
    writeFileSync(outsideTarget, JSON.stringify({ status: "untouched" }));

    const res = await handler(req({ token: TOKEN, hash: "../victim", decision: "approved" }));
    expect(res.status).toBe(400);
    expect(existsSync(outsideTarget)).toBe(true);
    expect(JSON.parse(readFileSync(outsideTarget, "utf-8"))).toEqual({ status: "untouched" });
  });

  it("rejects a malformed JSON body with 400", async () => {
    const { handler, queueDir } = makeHandler();
    const request = new Request("http://127.0.0.1:3000/api/queue", {
      method: "POST",
      headers: {
        "content-type": "application/json",
        origin: "http://127.0.0.1:3000",
        host: "127.0.0.1:3000",
      },
      body: "{ not valid json",
    });
    void queueDir;
    const res = await handler(request);
    expect(res.status).toBe(400);
  });
});

describe("POST /api/queue — pending-only guard + build spawn seam", () => {
  it("returns 409 when the entry is already approved (double-click / stale tab)", async () => {
    const { handler, queueDir } = makeHandler();
    const path = writeEntry(queueDir, HASH_A, { status: "approved" });
    const res = await handler(req({ token: TOKEN, hash: HASH_A, decision: "approved" }));
    expect(res.status).toBe(409);
    expect(JSON.parse(readFileSync(path, "utf-8")).status).toBe("approved");
  });

  it("denied entry never calls claimAndSpawnBuild", async () => {
    const calls: unknown[] = [];
    const claimAndSpawnBuild = (entry: unknown) => {
      calls.push(entry);
      return { claimed: true };
    };
    const { handler, queueDir } = makeHandler({ claimAndSpawnBuild });
    writeEntry(queueDir, HASH_A, { toolName: "workflow-audit:propose-skill" });
    const res = await handler(req({ token: TOKEN, hash: HASH_A, decision: "denied" }));
    expect(res.status).toBe(200);
    expect(calls).toHaveLength(0);
  });

  it("approved entry with non-matching toolName never calls claimAndSpawnBuild", async () => {
    const calls: unknown[] = [];
    const claimAndSpawnBuild = (entry: unknown) => {
      calls.push(entry);
      return { claimed: true };
    };
    const { handler, queueDir } = makeHandler({ claimAndSpawnBuild });
    writeEntry(queueDir, HASH_A, { toolName: "mcp__claude_ai_Slack__slack_send_message" });
    const res = await handler(req({ token: TOKEN, hash: HASH_A, decision: "approved" }));
    expect(res.status).toBe(200);
    expect(calls).toHaveLength(0);
    const body = await res.json();
    expect(body.build).toBeUndefined();
  });

  it("approved entry with toolName workflow-audit:propose-skill calls claimAndSpawnBuild exactly once and echoes its result under build", async () => {
    const calls: unknown[] = [];
    const claimAndSpawnBuild = (entry: unknown) => {
      calls.push(entry);
      return { claimed: true as const, runId: "abc12345" };
    };
    const { handler, queueDir } = makeHandler({ claimAndSpawnBuild });
    writeEntry(queueDir, HASH_A, {
      toolName: "workflow-audit:propose-skill",
      toolInput: { proposed_name: "my-new-skill" },
    });
    const res = await handler(req({ token: TOKEN, hash: HASH_A, decision: "approved" }));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.build).toEqual({ claimed: true, runId: "abc12345" });
    expect(calls).toHaveLength(1);
    expect(calls[0]).toEqual({
      hash: HASH_A,
      toolName: "workflow-audit:propose-skill",
      toolInput: { proposed_name: "my-new-skill" },
      createdAt: 1_720_000_000_000,
      status: "approved",
    });
  });

  it("echoes {claimed:false, error:'invalid_name'} under build when claimAndSpawnBuild rejects the name", async () => {
    const claimAndSpawnBuild = () => ({ claimed: false as const, error: "invalid_name" as const });
    const { handler, queueDir } = makeHandler({ claimAndSpawnBuild });
    writeEntry(queueDir, HASH_A, {
      toolName: "workflow-audit:propose-skill",
      toolInput: { proposed_name: "Has Spaces" },
    });
    const res = await handler(req({ token: TOKEN, hash: HASH_A, decision: "approved" }));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.build).toEqual({ claimed: false, error: "invalid_name" });
  });

  it("echoes {claimed:false, alreadyClaimed:true} under build when the hash was already claimed", async () => {
    const claimAndSpawnBuild = () => ({ claimed: false as const, alreadyClaimed: true as const });
    const { handler, queueDir } = makeHandler({ claimAndSpawnBuild });
    writeEntry(queueDir, HASH_A, {
      toolName: "workflow-audit:propose-skill",
      toolInput: { proposed_name: "my-new-skill" },
    });
    const res = await handler(req({ token: TOKEN, hash: HASH_A, decision: "approved" }));
    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.build).toEqual({ claimed: false, alreadyClaimed: true });
  });
});
