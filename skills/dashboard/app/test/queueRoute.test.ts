import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, writeFileSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createQueueActionHandler } from "../src/app/api/queue/route";

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

function makeHandler(overrides: { token?: string; queueDir?: string } = {}) {
  const queueDir = overrides.queueDir ?? tmpDir("dashboard-queue-route-");
  const handler = createQueueActionHandler({ token: overrides.token ?? TOKEN, queueDir });
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
    const path = writeEntry(queueDir, "hashA");
    const res = await handler(req({ hash: "hashA", decision: "approved" }));
    expect(res.status).toBe(401);
    expect(JSON.parse(readFileSync(path, "utf-8")).status).toBe("pending");
  });

  it("rejects a wrong token with 401", async () => {
    const { handler } = makeHandler();
    const res = await handler(req({ token: "wrong", hash: "hashA", decision: "approved" }));
    expect(res.status).toBe(401);
  });

  it("rejects a non-localhost origin with 403", async () => {
    const { handler, queueDir } = makeHandler();
    writeEntry(queueDir, "hashA");
    const res = await handler(
      req({ token: TOKEN, hash: "hashA", decision: "approved" }, { origin: "https://evil.example" })
    );
    expect(res.status).toBe(403);
  });

  it("never includes the token in a response body", async () => {
    const { handler } = makeHandler();
    const res = await handler(req({ token: "wrong", hash: "hashA", decision: "approved" }));
    const text = await res.text();
    expect(text).not.toContain(TOKEN);
  });
});

describe("POST /api/queue — approve/deny", () => {
  it("approves a pending entry via in-place rewrite", async () => {
    const { handler, queueDir } = makeHandler();
    const path = writeEntry(queueDir, "hashA");
    const res = await handler(req({ token: TOKEN, hash: "hashA", decision: "approved" }));
    expect(res.status).toBe(200);
    expect(JSON.parse(readFileSync(path, "utf-8")).status).toBe("approved");
  });

  it("denies a pending entry via in-place rewrite", async () => {
    const { handler, queueDir } = makeHandler();
    const path = writeEntry(queueDir, "hashB");
    const res = await handler(req({ token: TOKEN, hash: "hashB", decision: "denied" }));
    expect(res.status).toBe(200);
    expect(JSON.parse(readFileSync(path, "utf-8")).status).toBe("denied");
  });

  it("does not bleed through to a different hash in the same dir", async () => {
    const { handler, queueDir } = makeHandler();
    const pathX = writeEntry(queueDir, "hashX");
    const pathY = writeEntry(queueDir, "hashY");
    const res = await handler(req({ token: TOKEN, hash: "hashX", decision: "approved" }));
    expect(res.status).toBe(200);
    expect(JSON.parse(readFileSync(pathX, "utf-8")).status).toBe("approved");
    expect(JSON.parse(readFileSync(pathY, "utf-8")).status).toBe("pending");
  });

  it("rejects an invalid decision value with 400 and does not mutate the file", async () => {
    const { handler, queueDir } = makeHandler();
    const path = writeEntry(queueDir, "hashC");
    const res = await handler(req({ token: TOKEN, hash: "hashC", decision: "expired" }));
    expect(res.status).toBe(400);
    expect(JSON.parse(readFileSync(path, "utf-8")).status).toBe("pending");
  });

  it("rejects a missing hash with 404 (unknown queue entry) rather than throwing", async () => {
    const { handler } = makeHandler();
    const res = await handler(req({ token: TOKEN, hash: "does-not-exist", decision: "approved" }));
    expect(res.status).toBe(404);
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
