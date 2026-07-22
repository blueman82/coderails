import { describe, it, expect, afterEach } from "vitest";
import { mkdtempSync, writeFileSync, readFileSync, readdirSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { resolveQueueEntry, QueueActionError } from "../src/lib/collect/queueActions";

const tmpDirs: string[] = [];

function makeTmpDir(name: string): string {
  const dir = mkdtempSync(join(tmpdir(), `dashboard-queue-actions-${name}-`));
  tmpDirs.push(dir);
  return dir;
}

// 64-char hex strings, matching the frozen contract's "sha256(...), hex" shape.
const HASH_A = "a".repeat(64);
const HASH_B = "b".repeat(64);
const HASH_X = "1".repeat(64);
const HASH_Y = "2".repeat(64);
const HASH_Z = "3".repeat(64);
const HASH_BAD_JSON = "4".repeat(64);
const HASH_MISSING = "5".repeat(64);
const HASH_INVALID_DECISION = "6".repeat(64);

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
    const path = writeEntry(dir, HASH_A);

    resolveQueueEntry(dir, HASH_A, "approved");

    const filesAfter = readdirSync(dir);
    expect(filesAfter).toEqual([`${HASH_A}.json`]); // no separate decision file appeared

    const rewritten = JSON.parse(readFileSync(path, "utf-8"));
    expect(rewritten).toEqual({
      hash: HASH_A,
      toolName: "mcp__claude_ai_Slack__slack_send_message",
      toolInput: { channel: "#general", text: "hello" },
      createdAt: 1_720_000_000_000,
      status: "approved",
    });
  });

  it("negative control: an implementation that writes a separate decision file instead of mutating in place would leave more than one file in the dir", () => {
    const dir = makeTmpDir("inplace-negctrl");
    writeEntry(dir, HASH_A);
    // Simulate the wrong implementation directly to prove the assertion style catches it.
    writeFileSync(join(dir, `${HASH_A}.decision.json`), JSON.stringify({ status: "approved" }));
    const filesAfter = readdirSync(dir);
    expect(filesAfter.length).toBeGreaterThan(1); // demonstrates the control fires
  });

  it("denies in place the same way approve does", () => {
    const dir = makeTmpDir("deny");
    const path = writeEntry(dir, HASH_B);
    resolveQueueEntry(dir, HASH_B, "denied");
    const rewritten = JSON.parse(readFileSync(path, "utf-8"));
    expect(rewritten.status).toBe("denied");
  });

  it("negative control (a) no bleed-through: resolving hash X does not change a different pending hash Y", () => {
    const dir = makeTmpDir("no-bleed");
    const pathX = writeEntry(dir, HASH_X);
    const pathY = writeEntry(dir, HASH_Y);

    resolveQueueEntry(dir, HASH_X, "approved");

    const rewrittenX = JSON.parse(readFileSync(pathX, "utf-8"));
    const rewrittenY = JSON.parse(readFileSync(pathY, "utf-8"));
    expect(rewrittenX.status).toBe("approved");
    expect(rewrittenY.status).toBe("pending"); // untouched
  });

  it("negative control: a resolver that globbed and updated every file in the dir would fail the no-bleed-through control", () => {
    const dir = makeTmpDir("no-bleed-negctrl");
    const pathX = writeEntry(dir, HASH_X);
    const pathY = writeEntry(dir, HASH_Y);
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
    const path = writeEntry(dir, HASH_Z);
    // no call to resolveQueueEntry
    const untouched = JSON.parse(readFileSync(path, "utf-8"));
    expect(untouched.status).toBe("pending");
  });

  it("negative control (c): throws (does not silently succeed) when the target hash file is malformed JSON", () => {
    const dir = makeTmpDir("malformed");
    writeFileSync(join(dir, `${HASH_BAD_JSON}.json`), "{ not valid json");
    expect(() => resolveQueueEntry(dir, HASH_BAD_JSON, "approved")).toThrow(QueueActionError);
  });

  it("negative control (c): throws when the target hash file does not exist", () => {
    const dir = makeTmpDir("missing-file");
    expect(() => resolveQueueEntry(dir, HASH_MISSING, "approved")).toThrow(QueueActionError);
  });

  it("throws given an invalid decision value rather than writing it", () => {
    const dir = makeTmpDir("invalid-decision");
    const path = writeEntry(dir, HASH_INVALID_DECISION);
    expect(() =>
      // @ts-expect-error -- deliberately passing an invalid decision to prove it's rejected
      resolveQueueEntry(dir, HASH_INVALID_DECISION, "expired")
    ).toThrow(QueueActionError);
    const untouched = JSON.parse(readFileSync(path, "utf-8"));
    expect(untouched.status).toBe("pending");
  });

  it("throws on a hash that is not well-formed hex-64 (rejects non-hash-shaped input)", () => {
    const dir = makeTmpDir("bad-hash-shape");
    expect(() => resolveQueueEntry(dir, "not-a-hash", "approved")).toThrow(QueueActionError);
  });

  it("throws on a path-traversal hash rather than escaping queueDir (security: no out-of-directory write)", () => {
    const dir = makeTmpDir("traversal");
    // A file that would be the traversal target if the join() were not guarded.
    const outsideDir = makeTmpDir("traversal-outside");
    const outsideTarget = join(outsideDir, "victim.json");
    writeFileSync(outsideTarget, JSON.stringify({ status: "untouched" }));

    const traversalHash = `../../../../../../..${outsideDir}/victim`;
    expect(() => resolveQueueEntry(dir, traversalHash, "approved")).toThrow(QueueActionError);

    // The victim file outside queueDir must remain completely unmodified.
    expect(JSON.parse(readFileSync(outsideTarget, "utf-8"))).toEqual({ status: "untouched" });
  });

  it("negative control: an unguarded join() would in fact escape queueDir given a traversal hash (proves the guard is load-bearing)", () => {
    const dir = makeTmpDir("traversal-negctrl");
    const outsideDir = makeTmpDir("traversal-negctrl-outside");
    const naivePath = join(dir, `../${outsideDir.split("/").pop()}/escaped.json`);
    // Demonstrates path.join happily resolves ".." segments out of dir — this is exactly the
    // primitive HASH_PATTERN validation in resolveQueueEntry exists to block.
    expect(naivePath.startsWith(dir)).toBe(false);
    expect(existsSync(naivePath.replace("escaped.json", ""))).toBe(true);
  });

  it("throws QueueActionError when the target entry's status is not pending (approve-after-deny)", () => {
    const dir = makeTmpDir("approve-after-deny");
    const path = writeEntry(dir, HASH_A, { status: "denied" });
    expect(() => resolveQueueEntry(dir, HASH_A, "approved")).toThrow(QueueActionError);
    const untouched = JSON.parse(readFileSync(path, "utf-8"));
    expect(untouched.status).toBe("denied"); // the guard fires before the write
  });

  it("throws QueueActionError on double-approve (already approved)", () => {
    const dir = makeTmpDir("double-approve");
    const path = writeEntry(dir, HASH_A, { status: "approved" });
    expect(() => resolveQueueEntry(dir, HASH_A, "approved")).toThrow(QueueActionError);
    const untouched = JSON.parse(readFileSync(path, "utf-8"));
    expect(untouched.status).toBe("approved");
  });

  it("returns the updated entry with the new status, matching the file's new bytes", () => {
    const dir = makeTmpDir("returns-updated-entry");
    const path = writeEntry(dir, HASH_A);
    const returned = resolveQueueEntry(dir, HASH_A, "approved");
    const onDisk = JSON.parse(readFileSync(path, "utf-8"));
    expect(returned).toEqual(onDisk);
    expect(returned.status).toBe("approved");
  });

  it("security: returned snapshot's hash is the validated parameter, not the file contents' hash field, when they disagree (path-traversal defense-in-depth)", () => {
    const dir = makeTmpDir("hash-mismatch");
    // The file is named and read by HASH_A (the validated parameter), but its
    // own JSON contents claim a different, traversal-shaped hash. A caller
    // that trusts the returned snapshot's hash (e.g. claimAndSpawnBuild's
    // join(buildsDir, entry.hash)) must never see that traversal value.
    const path = writeEntry(dir, HASH_A, { hash: "../../../../etc/evil" });

    const returned = resolveQueueEntry(dir, HASH_A, "approved");

    expect(returned.hash).toBe(HASH_A);
    const onDisk = JSON.parse(readFileSync(path, "utf-8"));
    expect(onDisk.hash).toBe(HASH_A);
  });
});
