import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, writeFileSync, readFileSync, readdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { resolveQueueEntry, QueueActionError } from "../src/lib/collect/queueActions";

const tmpDirs: string[] = [];

function makeTmpDir(name: string): string {
  const dir = mkdtempSync(join(tmpdir(), `dashboard-queue-actions-${name}-`));
  tmpDirs.push(dir);
  return dir;
}

function writeEntry(dir: string, hash: string, overrides: Record<string, unknown> = {}): string {
  const path = join(dir, `${hash}.json`);
  const entry = {
    hash,
    toolName: "mcp__claude_ai_Slack__slack_send_message",
    toolInput: { channel: "#general", text: "hello" },
    createdAt: 1_720_000_000_000,
    status: "pending",
    ...overrides,
  };
  writeFileSync(path, JSON.stringify(entry));
  return path;
}

afterEach(() => {
  for (const dir of tmpDirs.splice(0)) {
    rmSync(dir, { recursive: true, force: true });
  }
});

describe("resolveQueueEntry", () => {
  it("performs an in-place JSON rewrite of the target <hash>.json file's status field, preserving other fields", () => {
    const dir = makeTmpDir("inplace");
    const path = writeEntry(dir, "hashA");

    resolveQueueEntry(dir, "hashA", "approved");

    const filesAfter = readdirSync(dir);
    expect(filesAfter).toEqual(["hashA.json"]); // no separate decision file appeared

    const rewritten = JSON.parse(readFileSync(path, "utf-8"));
    expect(rewritten).toEqual({
      hash: "hashA",
      toolName: "mcp__claude_ai_Slack__slack_send_message",
      toolInput: { channel: "#general", text: "hello" },
      createdAt: 1_720_000_000_000,
      status: "approved",
    });
  });

  it("negative control: an implementation that writes a separate decision file instead of mutating in place would leave more than one file in the dir", () => {
    const dir = makeTmpDir("inplace-negctrl");
    writeEntry(dir, "hashA");
    // Simulate the wrong implementation directly to prove the assertion style catches it.
    writeFileSync(join(dir, "hashA.decision.json"), JSON.stringify({ status: "approved" }));
    const filesAfter = readdirSync(dir);
    expect(filesAfter.length).toBeGreaterThan(1); // demonstrates the control fires
  });

  it("denies in place the same way approve does", () => {
    const dir = makeTmpDir("deny");
    const path = writeEntry(dir, "hashB");
    resolveQueueEntry(dir, "hashB", "denied");
    const rewritten = JSON.parse(readFileSync(path, "utf-8"));
    expect(rewritten.status).toBe("denied");
  });

  it("negative control (a) no bleed-through: resolving hash X does not change a different pending hash Y", () => {
    const dir = makeTmpDir("no-bleed");
    const pathX = writeEntry(dir, "hashX");
    const pathY = writeEntry(dir, "hashY");

    resolveQueueEntry(dir, "hashX", "approved");

    const rewrittenX = JSON.parse(readFileSync(pathX, "utf-8"));
    const rewrittenY = JSON.parse(readFileSync(pathY, "utf-8"));
    expect(rewrittenX.status).toBe("approved");
    expect(rewrittenY.status).toBe("pending"); // untouched
  });

  it("negative control: a resolver that globbed and updated every file in the dir would fail the no-bleed-through control", () => {
    const dir = makeTmpDir("no-bleed-negctrl");
    const pathX = writeEntry(dir, "hashX");
    const pathY = writeEntry(dir, "hashY");
    // Simulate the broken behaviour directly: update every file regardless of hash.
    for (const file of readdirSync(dir)) {
      const p = join(dir, file);
      const parsed = JSON.parse(readFileSync(p, "utf-8"));
      parsed.status = "approved";
      writeFileSync(p, JSON.stringify(parsed));
    }
    const rewrittenX = JSON.parse(readFileSync(pathX, "utf-8"));
    const rewrittenY = JSON.parse(readFileSync(pathY, "utf-8"));
    expect(rewrittenX.status).toBe("approved");
    expect(rewrittenY.status).toBe("approved"); // proves the negative-control scenario itself bleeds through
  });

  it("negative control (b): an entry that is never resolved stays pending", () => {
    const dir = makeTmpDir("stays-pending");
    const path = writeEntry(dir, "hashZ");
    // no call to resolveQueueEntry
    const untouched = JSON.parse(readFileSync(path, "utf-8"));
    expect(untouched.status).toBe("pending");
  });

  it("negative control (c): throws (does not silently succeed) when the target hash file is malformed JSON", () => {
    const dir = makeTmpDir("malformed");
    writeFileSync(join(dir, "badHash.json"), "{ not valid json");
    expect(() => resolveQueueEntry(dir, "badHash", "approved")).toThrow(QueueActionError);
  });

  it("negative control (c): throws when the target hash file does not exist", () => {
    const dir = makeTmpDir("missing-file");
    expect(() => resolveQueueEntry(dir, "doesNotExist", "approved")).toThrow(QueueActionError);
  });

  it("throws given an invalid decision value rather than writing it", () => {
    const dir = makeTmpDir("invalid-decision");
    const path = writeEntry(dir, "hashInvalid");
    expect(() =>
      // @ts-expect-error -- deliberately passing an invalid decision to prove it's rejected
      resolveQueueEntry(dir, "hashInvalid", "expired")
    ).toThrow(QueueActionError);
    const untouched = JSON.parse(readFileSync(path, "utf-8"));
    expect(untouched.status).toBe("pending");
  });
});
