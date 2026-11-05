import { mkdtemp, mkdir, readFile, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHash } from "node:crypto";
import { describe, expect, it } from "vitest";
import { readClaudeTracePage, type TraceCollectionDeps } from "../src/lib/collect/sessionTrace";

type Row = Record<string, unknown>;
const digest = (value: string) => createHash("sha256").update(value).digest("hex");

async function fixture(rows: Row[]) {
  const root = await mkdtemp(join(tmpdir(), "claude-observation-"));
  const sourceRoot = join(root, "projects");
  const parent = join(sourceRoot, "project", "s1.jsonl");
  await mkdir(join(sourceRoot, "project"), { recursive: true });
  const save = async () => writeFile(parent, rows.map((row) => JSON.stringify(row)).join("\n") + "\n");
  await save();
  const deps: TraceCollectionDeps = { sourceRoot, cacheRoot: join(root, "cache"),
    now: () => new Date("2026-10-25T00:00:00Z"),
    fs: { readFile: (path) => readFile(path, "utf8"), writeFile, stat } };
  return { deps, save };
}

describe("Claude transcript observations", () => {
  it("keeps arbitrary skill-file origin unproved", async () => {
    const { deps } = await fixture([
      { type: "assistant", sessionId: "s1", message: { content: [
        { type: "tool_use", name: "Read", id: "scratch", input: { file_path: "/scratch/uninstalled/skills/wiki-query/SKILL.md" } },
      ] } },
      { type: "user", sessionId: "s1", message: { content: [
        { type: "tool_result", tool_use_id: "scratch", content: "complete 😀" },
      ] } },
    ]);
    const page = await readClaudeTracePage("s1", null, 50, deps);
    expect(page.events.find((event) => event.name === "tool_result")?.attributes)
      .toMatchObject({ "coderails.observation.kind": "uncertain", "coderails.observation.bytes": 13 });
  });

  it("retains a separate mention beside tool calls without duplicating invocations", async () => {
    const { deps } = await fixture([{ type: "assistant", sessionId: "s1", message: { content: [
      { type: "text", text: "See skills/wiki-query/SKILL.md before continuing." },
      { type: "tool_use", name: "Bash", id: "bash", input: { command: "true" } },
      { type: "tool_use", name: "Skill", id: "skill", input: { skill: "coderails:wiki-query" } },
    ] } }]);
    const page = await readClaudeTracePage("s1", null, 50, deps);
    const kinds = page.events.map((event) => event.attributes["coderails.observation.kind"]);
    expect(kinds.filter((kind) => kind === "mention")).toHaveLength(1);
    expect(kinds.filter((kind) => kind === "invocation")).toHaveLength(1);
    expect(new Set(page.events.map((event) => event.eventId)).size).toBe(page.events.length);
  });

  it.each([null, "true", 1, {}, []].map((value) => [value]))("keeps malformed read error flag %j uncertain", async (is_error) => {
    const { deps } = await fixture([
      { type: "assistant", sessionId: "s1", message: { content: [
        { type: "tool_use", name: "Read", id: "read", input: { file_path: "/repo/AGENTS.md" } },
      ] } },
      { type: "user", sessionId: "s1", message: { content: [
        { type: "tool_result", tool_use_id: "read", is_error, content: "body" },
      ] } },
    ]);
    const page = await readClaudeTracePage("s1", null, 50, deps);
    expect(page.events.find((event) => event.name === "tool_result")?.attributes["coderails.observation.kind"])
      .toBe("uncertain");
  });

  it.each([undefined, false])("retains valid context read success with flag %j", async (is_error) => {
    const { deps } = await fixture([
      { type: "assistant", sessionId: "s1", message: { content: [
        { type: "tool_use", name: "Read", id: "read", input: { file_path: "/repo/AGENTS.md" } },
      ] } },
      { type: "user", sessionId: "s1", message: { content: [
        { type: "tool_result", tool_use_id: "read", is_error, content: "body" },
      ] } },
    ]);
    const page = await readClaudeTracePage("s1", null, 50, deps);
    expect(page.events.find((event) => event.name === "tool_result")?.attributes["coderails.observation.kind"])
      .toBe("read");
  });

  it("retains only a hashed native usage identity across repeated message rows", async () => {
    const row = { type: "assistant", sessionId: "s1", message: { id: "PRIVATE_NATIVE_ID",
      usage: { input_tokens: 8 }, content: [{ type: "text", text: "PRIVATE_BODY" }] } };
    const { deps } = await fixture([row, row, { ...row, message: { ...row.message, id: "distinct-message" } }]);
    const page = await readClaudeTracePage("s1", null, 50, deps);
    const identities = page.events.map((event) => event.attributes["coderails.usage.identity_sha256"]);
    expect(identities[0]).toMatch(/^[a-f0-9]{64}$/);
    expect(identities[1]).toBe(identities[0]);
    expect(identities[2]).not.toBe(identities[0]);
    expect(JSON.stringify(page)).not.toContain("PRIVATE_NATIVE_ID");
    expect(JSON.stringify(page)).not.toContain("PRIVATE_BODY");
  });

  it("keeps invocation, unproved skill-file read and mention separate without source text", async () => {
    const secret = "PRIVATE-😀";
    const rows: Row[] = [
      { type: "assistant", sessionId: "s1", message: { role: "assistant",
        usage: { input_tokens: 8, output_tokens: 3, cache_read_input_tokens: 2 },
        content: [
          { type: "tool_use", name: "Skill", id: "skill-1", input: { skill: "coderails:wiki-query" } },
          { type: "tool_use", name: "Read", id: "read-1",
            input: { file_path: "/plugin/skills/wiki-query/SKILL.md" } },
        ] } },
      { type: "user", sessionId: "s1", message: { role: "user",
        content: [{ type: "tool_result", tool_use_id: "read-1", content: secret }] } },
      { type: "assistant", sessionId: "s1", message: { role: "assistant",
        content: [{ type: "text", text: "See skills/wiki-query/SKILL.md for details." }] } },
    ];
    const { deps } = await fixture(rows);
    const page = await readClaudeTracePage("s1", null, 50, deps);
    const observations = page.events.filter((event) => event.attributes["coderails.observation.kind"]);
    expect(observations.map((event) => event.attributes["coderails.observation.kind"]))
      .toEqual(["invocation", "uncertain", "mention"]);
    expect(observations.every((event) => event.attributes["coderails.observation.target_sha256"] ===
      digest("skill:wiki-query"))).toBe(true);
    expect(observations[1].attributes["coderails.observation.bytes"]).toBe(Buffer.byteLength(secret, "utf8"));
    expect(observations[0].attributes["gen_ai.usage.cache_read_input_tokens"]).toBe(2);
    expect(observations[0].attributes["coderails.usage.semantics"]).toBe("incremental");
    expect(JSON.stringify(page)).not.toContain(secret);
    expect(JSON.stringify(page)).not.toContain("/plugin/skills/wiki-query/SKILL.md");
  });

  it("counts failed reads and leaves a request with no result uncertain", async () => {
    const rows: Row[] = [
      { type: "assistant", sessionId: "s1", message: { role: "assistant", content: [
        { type: "tool_use", name: "Read", id: "fail", input: { file_path: "/x/AGENTS.md" } },
        { type: "tool_use", name: "Read", id: "missing", input: { file_path: "/x/CLAUDE.md" } },
      ] } },
      { type: "user", sessionId: "s1", message: { role: "user",
        content: [{ type: "tool_result", tool_use_id: "fail", is_error: true, content: "PRIVATE error" }] } },
    ];
    const { deps } = await fixture(rows);
    const page = await readClaudeTracePage("s1", null, 50, deps);
    expect(page.events.filter((event) => event.attributes["coderails.observation.kind"])
      .map((event) => event.attributes["coderails.observation.kind"])).toEqual(["uncertain", "failed_read"]);
    expect(JSON.stringify(page)).not.toContain("PRIVATE error");
  });

  it("does not turn duplicate or foreign native read records into observed reads", async () => {
    const rows: Row[] = [
      { type: "assistant", sessionId: "s1", message: { role: "assistant", content: [
        { type: "tool_use", name: "Read", id: "same", input: { file_path: "/x/AGENTS.md" } },
        { type: "tool_use", name: "Read", id: "same", input: { file_path: "/x/AGENTS.md" } },
      ] } },
      { type: "user", sessionId: "s1", message: { role: "user",
        content: [{ type: "tool_result", tool_use_id: "same", content: "PRIVATE" }] } },
      { type: "assistant", sessionId: "foreign", message: { role: "assistant",
        content: [{ type: "text", text: "See AGENTS.md" }] } },
    ];
    const { deps } = await fixture(rows);
    const page = await readClaudeTracePage("s1", null, 50, deps);
    expect(page.events.some((event) => event.attributes["coderails.observation.kind"] === "read")).toBe(false);
    expect(page.errors?.join(" ")).toMatch(/ambiguous read call|foreign session identity/);
    expect(JSON.stringify(page)).not.toContain("PRIVATE");
  });

  it("does not persist a native tool name that contains source text", async () => {
    const rows: Row[] = [{ type: "assistant", sessionId: "s1", message: { role: "assistant",
      content: [{ type: "tool_use", id: "call-1", name: "PRIVATE BODY",
        input: { file_path: "/x/AGENTS.md" } }] } }];
    const { deps } = await fixture(rows);
    const page = await readClaudeTracePage("s1", null, 50, deps);
    expect(page.events[0].attributes["tool.name"]).toBeUndefined();
    expect(JSON.stringify(page)).not.toContain("PRIVATE BODY");
  });

  it("does not accept a read result that precedes its request", async () => {
    const rows: Row[] = [
      { type: "user", sessionId: "s1", message: { role: "user",
        content: [{ type: "tool_result", tool_use_id: "read-1", content: "PRIVATE" }] } },
      { type: "assistant", sessionId: "s1", message: { role: "assistant",
        content: [{ type: "tool_use", name: "Read", id: "read-1", input: { file_path: "/x/AGENTS.md" } }] } },
    ];
    const { deps } = await fixture(rows);
    const page = await readClaudeTracePage("s1", null, 50, deps);
    expect(page.events.some((event) => event.attributes["coderails.observation.kind"] === "read")).toBe(false);
    expect(page.events.some((event) => event.attributes["coderails.observation.kind"] === "uncertain")).toBe(true);
    expect(page.errors?.join(" ")).toMatch(/out-of-order read result/);
  });
});
