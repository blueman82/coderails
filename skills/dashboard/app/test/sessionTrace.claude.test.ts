import { mkdtemp, mkdir, readFile, readdir, stat, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { collectClaudeSessionTrace, listClaudeSessions, readClaudeTracePage, type TraceCollectionDeps } from "../src/lib/collect/sessionTrace";

function fixtureMessage(row: Record<string, unknown>): { content: unknown; stop_reason?: string } {
  return row.message as { content: unknown; stop_reason?: string };
}

function fixtureBlocks(row: Record<string, unknown>): Array<Record<string, unknown>> {
  return fixtureMessage(row).content as Array<Record<string, unknown>>;
}

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), "claude-trace-"));
  const sourceRoot = join(root, "projects");
  const cacheRoot = join(root, "telemetry");
  const dir = join(sourceRoot, "project");
  await mkdir(join(dir, "s1", "subagents"), { recursive: true });
  const parent = join(dir, "s1.jsonl");
  const child = join(dir, "s1", "subagents", "agent-a1.jsonl");
  const native = JSON.parse(await readFile(fileURLToPath(new URL("./fixtures/session-trace/claude/native-shape.json", import.meta.url)), "utf8"));
  const rows = native.parent as Array<Record<string, unknown>>;
  const children = native.child as Array<Record<string, unknown>>;
  await writeFile(parent, rows.map((r) => JSON.stringify(r)).join("\n") + "\n");
  await writeFile(child, children.map((r) => JSON.stringify(r)).join("\n") + "\n");
  const deps: TraceCollectionDeps = { sourceRoot, cacheRoot, now: () => new Date("2026-09-28T13:00:00Z"), fs: { readFile: (p) => readFile(p, "utf8"), writeFile, stat } };
  return { deps, parent, child, rows, children };
}

describe("Claude native session trace", () => {
  it.each(["foreign-only", "mixed"])("marks %s explicit foreign parent identity incomplete without indexing it", async (shape) => {
    const { deps, parent, rows } = await fixture();
    const foreign = { type: "assistant", sessionId: "other", timestamp: "2026-09-28T12:00:01Z",
      message: { role: "assistant", content: [{ type: "text", text: "Foreign secret" }] } };
    const parentRows = shape === "mixed" ? [rows[0], foreign, ...rows.slice(1)] : [foreign];
    await writeFile(parent, parentRows.map((row) => JSON.stringify(row)).join("\n") + "\n");
    const page = await readClaudeTracePage("s1", null, 50, deps);
    expect(page.complete).toBe(false);
    expect(page.errors?.join(" ")).toMatch(/foreign session identity at project\/s1\.jsonl:\d+/i);
    expect(JSON.stringify(page)).not.toContain("Foreign secret");
    expect(page.events.filter((event) => event.provenance.sourceId === "project/s1.jsonl"))
      .toHaveLength(shape === "mixed" ? 3 : 0);
  });

  it("retains parent auxiliary rows without a session ID beside foreign rows", async () => {
    const { deps, parent } = await fixture();
    await writeFile(parent, [
      { type: "system", timestamp: "2026-09-28T12:00:00Z", message: "Auxiliary" },
      { type: "assistant", sessionId: "other", message: { content: [] } },
    ].map((row) => JSON.stringify(row)).join("\n") + "\n");
    const page = await readClaudeTracePage("s1", null, 50, deps);
    expect(page.complete).toBe(false);
    expect(page.events.map((event) => event.name)).toEqual(["system"]);
    expect(page.events[0].provenance.sourceOrdinal).toBe(1);
  });

  it("derives only a source-timestamped matching request/result gap and orders cross-source events", async () => {
    const { deps, parent, child, rows, children } = await fixture();
    rows[1].timestamp = "2026-09-28T12:00:03Z";
    children[0].timestamp = "2026-09-28T12:00:01Z";
    children[1].timestamp = "2026-09-28T12:00:02Z";
    await writeFile(parent, rows.map((row) => JSON.stringify(row)).join("\n") + "\n");
    await writeFile(child, children.map((row) => JSON.stringify(row)).join("\n") + "\n");
    const page = await readClaudeTracePage("s1", null, 50, deps);
    const request = page.events.find((event) => event.name === "tool_request")!;
    const result = page.events.find((event) => event.name === "tool_result")!;
    expect(result.attributes).toMatchObject({
      "coderails.elapsed_gap_ms": 3000, "coderails.elapsed_gap.basis": "derived",
      "coderails.elapsed_gap.method": "timestamp_difference", "coderails.elapsed_gap.cause": "unknown",
      "coderails.elapsed_gap.start_source_ref": JSON.stringify(request.provenance.sourceRef),
      "coderails.elapsed_gap.end_source_ref": JSON.stringify(result.provenance.sourceRef),
    });
    expect(result.attributes).toMatchObject({ "coderails.duration_ms": null,
      "coderails.duration.basis": "unavailable" });
    expect(page.events.filter((event) => event.provenance.sourceId.includes(".jsonl"))
      .map((event) => [event.provenance.sourceId, event.provenance.sourceOrdinal]))
      .toEqual([["project/s1.jsonl", 1], ["project/s1/subagents/agent-a1.jsonl", 1],
        ["project/s1/subagents/agent-a1.jsonl", 2], ["project/s1.jsonl", 2], ["project/s1.jsonl", 3]]);
    const childEvent = page.events.find((event) => event.attributes["coderails.actor.id"] === "a1")!;
    expect(childEvent.parentSpanId).toBe(request.spanId);
    expect(childEvent.attributes).toMatchObject({
      "coderails.parent_join.basis": "derived", "coderails.parent_join.method": "native_agent_call",
      "coderails.parent_join.parent_source_ref": JSON.stringify(request.provenance.sourceRef),
      "coderails.parent_join.child_source_ref": JSON.stringify(childEvent.provenance.sourceRef),
    });
  });

  it("leaves gaps unavailable for invalid, missing and ambiguous request timestamps", async () => {
    const { deps, parent, rows } = await fixture();
    rows[0].timestamp = "invalid";
    rows[1].timestamp = "2026-09-28T12:00:03Z";
    fixtureBlocks(rows[0]).push({ type: "tool_use", id: "tool-1", name: "Read" });
    await writeFile(parent, rows.map((row) => JSON.stringify(row)).join("\n") + "\n");
    const page = await readClaudeTracePage("s1", null, 50, deps);
    expect(page.events.filter((event) => event.name === "tool_result").every((event) =>
      event.attributes["coderails.elapsed_gap_ms"] === undefined)).toBe(true);
    const request = page.events.find((event) => event.name === "tool_request")!;
    expect(request.startTimeUnixNano).toBeNull();
    expect(request.attributes).toMatchObject({ "coderails.start_time.basis": "unavailable",
      "coderails.end_time.basis": "unavailable" });
  });
  it("labels source, missing, and invalid native time independently of record provenance", async () => {
    const { deps, parent, rows } = await fixture();
    rows[2].timestamp = "invalid";
    await writeFile(parent, rows.map((row) => JSON.stringify(row)).join("\n") + "\n");
    const page = await readClaudeTracePage("s1", null, 30, deps);
    const parentEvents = page.events.filter((item) => item.provenance.sourceId === "project/s1.jsonl");
    expect(parentEvents.map((item) => [item.startTimeUnixNano === null, item.attributes["coderails.start_time.basis"]]))
      .toEqual([[false, "source"], [true, "unavailable"], [true, "unavailable"]]);
    expect(parentEvents.every((item) => item.attributes["coderails.end_time.basis"] === "unavailable" &&
      item.attributes["coderails.duration_ms"] === null &&
      item.attributes["coderails.duration.basis"] === "unavailable")).toBe(true);
  });
  it("keeps native events visible while graph discovery ambiguity marks the page incomplete", async () => {
    const { deps } = await fixture();
    deps.graphDiscoveryError = "multiple matching graph roots (2)";
    const page = await readClaudeTracePage("s1", null, 30, deps);
    expect(page.events.length).toBeGreaterThan(0);
    expect(page.complete).toBe(false);
    expect(page.errors).toContain("multiple matching graph roots (2)");
  });
  it("keeps a selectable session's last activity unavailable without native event time", async () => {
    const { deps } = await fixture();
    const sessions = await listClaudeSessions(deps);
    expect(sessions.map((session) => session.nativeSessionId)).toEqual(["s1"]);
    expect(sessions[0].lastActivity).toEqual({ value: null, basis: "unavailable" });
  });
  it("emits each native tool block with its own stable identity and source backed failure", async () => {
    const { deps, parent, rows } = await fixture();
    fixtureBlocks(rows[0]).push({ type: "tool_use", id: "read-2", name: "Read", input: { secret: "Sensitive argument" } });
    fixtureBlocks(rows[1]).push({ type: "tool_result", tool_use_id: "read-2", is_error: true, content: "Sensitive failure" });
    await writeFile(parent, rows.map((row) => JSON.stringify(row)).join("\n") + "\n");
    const page = await readClaudeTracePage("s1", null, 30, deps);
    const calls = page.events.filter((event) => event.provenance.sourceId === "project/s1.jsonl");
    expect(calls.map((event) => event.attributes["coderails.native.call_id"])).toEqual(["tool-1", "read-2", "tool-1", "read-2", undefined]);
    expect(new Set(calls.map((event) => event.eventId)).size).toBe(calls.length);
    expect(calls[3].status).toEqual({ value: "error", basis: "source" });
    expect(calls[2].status.value).toBe("unavailable");
    expect(JSON.stringify(page)).not.toContain("Sensitive argument");
  });

  it("joins ordinary and nested Agent workers to their exact native call spans", async () => {
    const { deps, parent, rows, children } = await fixture();
    const rootCall = fixtureBlocks(rows[0])[0];
    (rootCall.input as { prompt: string }).prompt = "Ordinary parent prompt";
    fixtureMessage(children[0]).content = "Ordinary parent prompt";
    const nestedCall = { type: "tool_use", id: "nested-call", name: "Agent", input: { prompt: "Nested prompt", subagent_type: "worker" } };
    fixtureMessage(children[1]).content = [nestedCall];
    fixtureMessage(children[1]).stop_reason = "tool_use";
    children.push({ type: "user", sessionId: "s1", agentId: "a1", isSidechain: true,
      message: { content: [{ type: "tool_result", tool_use_id: "nested-call", content: "Sensitive nested result" }] },
      toolUseResult: { agentId: "a2" } });
    await writeFile(parent, rows.map((row) => JSON.stringify(row)).join("\n") + "\n");
    const childDir = join(deps.sourceRoot, "project", "s1", "subagents");
    await writeFile(join(childDir, "agent-a1.jsonl"), children.map((row) => JSON.stringify(row)).join("\n") + "\n");
    const nestedRows = [{ type: "user", sessionId: "s1", agentId: "a2", isSidechain: true,
      message: { role: "user", content: "Nested prompt" } },
      { type: "assistant", sessionId: "s1", agentId: "a2", isSidechain: true, attributionAgent: "worker",
        message: { role: "assistant", stop_reason: "end_turn", content: [{ type: "text", text: "Sensitive nested answer" }] } }];
    await writeFile(join(childDir, "agent-a2.jsonl"), nestedRows.map((row) => JSON.stringify(row)).join("\n") + "\n");
    const manifest = await collectClaudeSessionTrace("s1", deps);
    const page = await readClaudeTracePage("s1", null, 30, deps);
    const parentCall = page.events.find((event) => event.attributes["coderails.native.call_id"] === "tool-1" && event.name === "tool_request")!;
    const nested = page.events.find((event) => event.attributes["coderails.native.call_id"] === "nested-call")!;
    expect(manifest.complete).toBe(true);
    expect(page.events.filter((event) => event.attributes["coderails.actor.id"] === "a1")).toHaveLength(3);
    expect(page.events.filter((event) => event.attributes["coderails.actor.id"] === "a2")).toHaveLength(2);
    expect(page.events.filter((event) => event.attributes["coderails.actor.id"] === "a1").every((event) => event.parentSpanId === parentCall.spanId)).toBe(true);
    expect(page.events.filter((event) => event.attributes["coderails.actor.id"] === "a2").every((event) => event.parentSpanId === nested.spanId)).toBe(true);
  });

  it("attaches parallel workers to different Agent blocks in one parent message", async () => {
    const { deps, parent, rows, children } = await fixture();
    fixtureBlocks(rows[0]).push({ type: "tool_use", id: "tool-2", name: "Agent",
      input: { prompt: "Second worker prompt", subagent_type: "worker" } });
    rows.push({ type: "user", sessionId: "s1", message: { content: [{ type: "tool_result", tool_use_id: "tool-2" }] },
      toolUseResult: { agentId: "a2" } });
    await writeFile(parent, rows.map((row) => JSON.stringify(row)).join("\n") + "\n");
    const childDir = join(deps.sourceRoot, "project", "s1", "subagents");
    const second = structuredClone(children);
    for (const row of second) row.agentId = "a2";
    fixtureMessage(second[0]).content = "Second worker prompt";
    await writeFile(join(childDir, "agent-a2.jsonl"), second.map((row) => JSON.stringify(row)).join("\n") + "\n");
    const page = await readClaudeTracePage("s1", null, 30, deps);
    const call1 = page.events.find((event) => event.name === "tool_request" && event.attributes["coderails.native.call_id"] === "tool-1")!;
    const call2 = page.events.find((event) => event.name === "tool_request" && event.attributes["coderails.native.call_id"] === "tool-2")!;
    expect(call1.spanId).not.toBe(call2.spanId);
    expect(page.events.filter((event) => event.attributes["coderails.actor.id"] === "a1").map((event) => event.parentSpanId)).toEqual([call1.spanId, call1.spanId]);
    expect(page.events.filter((event) => event.attributes["coderails.actor.id"] === "a2").map((event) => event.parentSpanId)).toEqual([call2.spanId, call2.spanId]);
    expect(page.complete).toBe(true);
  });

  it("rejects stale generation cursors after a source changes", async () => {
    const { deps, parent, rows } = await fixture();
    const first = await readClaudeTracePage("s1", null, 2, deps);
    expect(first.nextCursor).toMatch(/^g:[a-f0-9]{64}:2$/);
    await writeFile(parent, [...rows, { type: "user", sessionId: "s1", message: "later" }].map((row) => JSON.stringify(row)).join("\n") + "\n");
    await expect(readClaudeTracePage("s1", first.nextCursor, 2, deps)).rejects.toThrow(/stale.*generation/i);
  });

  it("retires superseded cache generations after repeated source changes", async () => {
    const { deps, parent, rows } = await fixture();
    for (let i = 0; i < 5; i++) {
      await writeFile(parent, [...rows, ...Array.from({ length: i + 1 }, (_, n) => ({ type: "user", sessionId: "s1", message: `change ${n}` }))].map((row) => JSON.stringify(row)).join("\n") + "\n");
      await collectClaudeSessionTrace("s1", deps);
    }
    const files = await readdir(join(deps.cacheRoot, "claude", "s1"));
    expect(files.filter((name) => /^events\.[a-f0-9]{64}\.jsonl$/.test(name))).toHaveLength(1);
  });

  it("retries a page read when a concurrent rebuild retires its generation", async () => {
    const { deps, parent, rows } = await fixture();
    const old = await collectClaudeSessionTrace("s1", deps);
    const read = deps.fs.readFile;
    let eventReads = 0;
    deps.fs.readFile = async (path) => {
      if (path.endsWith(old.eventFile) && ++eventReads === 2) {
        await writeFile(parent, [...rows, { type: "user", sessionId: "s1", message: "later" }]
          .map((row) => JSON.stringify(row)).join("\n") + "\n");
        await collectClaudeSessionTrace("s1", { ...deps, fs: { ...deps.fs, readFile: read } });
      }
      return read(path);
    };
    const page = await readClaudeTracePage("s1", null, 30, deps);
    expect(page.events).toHaveLength(6);
    expect(eventReads).toBeGreaterThanOrEqual(2);
  });

});
