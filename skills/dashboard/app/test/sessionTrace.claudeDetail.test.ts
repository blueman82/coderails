import { mkdtemp, mkdir, readFile, readdir, stat, truncate, unlink, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { collectClaudeSessionTrace, listClaudeSessions, readClaudeTraceDetail, readClaudeTracePage, type TraceCollectionDeps } from "../src/lib/collect/sessionTrace";

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

describe("Claude native session trace detail and evidence", () => {
  it("removes metadata generations when the native session is deleted", async () => {
    const { deps, parent } = await fixture();
    await collectClaudeSessionTrace("s1", deps);
    await unlink(parent);
    await expect(collectClaudeSessionTrace("s1", deps)).rejects.toThrow(/uniquely/i);
    const files = await readdir(join(deps.cacheRoot, "claude", "s1"));
    expect(files.filter((name) => name === "manifest.json" || /^events\.[a-f0-9]{64}\.jsonl$/.test(name))).toEqual([]);
  });
  it("joins a validated child, retains ordinals and unknown time, and reads details only on request", async () => {
    const { deps } = await fixture();
    expect((await listClaudeSessions(deps)).map((s) => s.nativeSessionId)).toEqual(["s1"]);
    const manifest = await collectClaudeSessionTrace("s1", deps);
    expect(manifest.complete).toBe(true);
    expect(manifest.sources).toHaveLength(2);
    const page = await readClaudeTracePage("s1", null, 2, deps);
    expect(page.events).toHaveLength(2);
    expect(page.nextCursor).not.toBeNull();
    const remaining = await readClaudeTracePage("s1", page.nextCursor, 20, deps);
    const all = [...page.events, ...remaining.events];
    expect(all.some((e) => e.attributes["coderails.child.id"] === "a1")).toBe(true);
    expect(all.some((e) => e.provenance.sourceOrdinal === 2 && e.startTimeUnixNano === null)).toBe(true);
    expect(all.some((e) => e.attributes["coderails.node.id"] === "U1")).toBe(true);
    expect(JSON.stringify({ manifest, all })).not.toContain("Sensitive");
    const detail = await readClaudeTraceDetail("s1", all[0].provenance.sourceRef, deps);
    expect(detail.content).toContain("Sensitive prompt");
  });

  it("rejects ambiguous or foreign child identity without claiming completion", async () => {
    const { deps, child, children } = await fixture();
    await writeFile(child, children.map((r) => JSON.stringify({ ...r, sessionId: "other" })).join("\n") + "\n");
    const manifest = await collectClaudeSessionTrace("s1", deps);
    expect(manifest.complete).toBe(false);
    expect(manifest.errors.join(" ")).toMatch(/child|identity/i);
    expect(JSON.stringify(await readClaudeTracePage("s1", null, 30, deps))).not.toContain("Sensitive child answer");
  });

  it("leaves duplicate Agent calls unresolved and keeps the cache unchanged for unchanged sources", async () => {
    const { deps, parent, rows } = await fixture();
    const first = await collectClaudeSessionTrace("s1", deps);
    const again = await collectClaudeSessionTrace("s1", deps);
    expect(again.generatedAt).toBe(first.generatedAt);
    await writeFile(parent, [rows[0], rows[0], ...rows.slice(1)].map((row) => JSON.stringify(row)).join("\n") + "\n");
    const duplicate = await collectClaudeSessionTrace("s1", deps);
    expect(duplicate.complete).toBe(false);
    expect(duplicate.errors.join(" ")).toMatch(/duplicate Agent call/);
    const page = await readClaudeTracePage("s1", null, 20, deps);
    expect(page.events.filter((event) => event.attributes["coderails.actor.kind"] === "worker")).toHaveLength(0);
  });

  it("invalidates same-size rewrites and truncated or malformed records", async () => {
    const { deps, parent, rows } = await fixture();
    const first = await collectClaudeSessionTrace("s1", deps);
    const changed = JSON.stringify(rows[0]).replace("tool-1", "tool-2");
    const original = (await readFile(parent, "utf8")).split("\n");
    original[0] = changed;
    await writeFile(parent, original.join("\n"));
    const second = await collectClaudeSessionTrace("s1", deps);
    expect(second.sources[0].fingerprint).not.toBe(first.sources[0].fingerprint);
    expect(second.complete).toBe(false);
    await writeFile(parent, "{\"type\":\"assistant\"\n");
    const third = await collectClaudeSessionTrace("s1", deps);
    expect(third.complete).toBe(false);
    expect(third.errors.join(" ")).toMatch(/malformed|truncated/i);
    expect(third.eventCount).toBe(0);
  });

  it("rejects detail when a native source changes after the index was assembled", async () => {
    const { deps, parent } = await fixture();
    const page = await readClaudeTracePage("s1", null, 20, deps);
    const ref = page.events.find((event) => event.provenance.sourceId.includes("s1.jsonl"))!.provenance.sourceRef;
    const originalRead = deps.fs.readFile;
    let reads = 0;
    deps.fs.readFile = async (path) => {
      if (path === parent && ++reads === 2) {
        await writeFile(parent, (await readFile(parent, "utf8")).replace("Sensitive prompt", "Replaced prompt "));
      }
      return originalRead(path);
    };
    await expect(readClaudeTraceDetail("s1", ref, deps)).rejects.toThrow(/changed/i);
  });

  it("publishes a manifest that names its own complete event generation", async () => {
    const { deps, parent, rows } = await fixture();
    await collectClaudeSessionTrace("s1", deps);
    await writeFile(parent, [rows[0], ...rows.slice(2)].map((row) => JSON.stringify(row)).join("\n") + "\n");
    await Promise.all([collectClaudeSessionTrace("s1", deps), collectClaudeSessionTrace("s1", deps)]);
    const manifest = JSON.parse(await readFile(join(deps.cacheRoot, "claude", "s1", "manifest.json"), "utf8"));
    expect(manifest.eventFile).toMatch(/^events\.[a-f0-9]{64}\.jsonl$/);
    const events = (await readFile(join(deps.cacheRoot, "claude", "s1", manifest.eventFile), "utf8")).split("\n").filter(Boolean);
    expect(events).toHaveLength(manifest.eventCount);
  });

  it("rebuilds a same-length damaged event generation", async () => {
    const { deps } = await fixture();
    const manifest = await collectClaudeSessionTrace("s1", deps);
    const path = join(deps.cacheRoot, "claude", "s1", manifest.eventFile);
    const original = await readFile(path, "utf8");
    await writeFile(path, original.replace('"schemaVersion":1', '"schemaVersion":0'));
    const rebuilt = await collectClaudeSessionTrace("s1", deps);
    expect(rebuilt.eventFile).toBe(manifest.eventFile);
    expect(await readFile(path, "utf8")).toBe(original);
  });

  it("marks an oversized native source incomplete before reading it", async () => {
    const { deps, parent } = await fixture();
    const read = deps.fs.readFile;
    deps.fs.stat = async (path) => path === parent ? { size: 1_000_000_000 } : stat(path);
    deps.fs.readFile = async (path) => {
      if (path === parent) throw new Error("oversized source was read");
      return read(path);
    };
    const manifest = await collectClaudeSessionTrace("s1", deps);
    expect(manifest.complete).toBe(false);
    expect(manifest.errors.join(" ")).toMatch(/scan limit/i);
    const page = await readClaudeTracePage("s1", null, 20, deps);
    expect(page.events).toHaveLength(0);
    expect(page.truncated).toBe(true);
    expect(page.emittedEvents).toBe(0);
  });

  it("does not copy arbitrary read errors into the metadata cache", async () => {
    const { deps, parent } = await fixture();
    const read = deps.fs.readFile;
    deps.fs.readFile = async (path) => path === parent ? Promise.reject(new Error("Sensitive read failure")) : read(path);
    const manifest = await collectClaudeSessionTrace("s1", deps);
    expect(manifest.complete).toBe(false);
    expect(JSON.stringify(manifest)).not.toContain("Sensitive");
  });

  it("indexes only hook audit lines explicitly scoped to this native session", async () => {
    const { deps } = await fixture();
    const auditPath = join(deps.cacheRoot, "claude-audit.log");
    await mkdir(deps.cacheRoot, { recursive: true });
    await writeFile(auditPath, [
      "2026-09-28T12:01:00+0000 hook=loop_state_guard session=s1 blocked=1 note=Sensitive",
      "2026-09-28T12:02:00+0000 hook=loop_state_guard session=foreign blocked=1",
      "2026-09-28T12:03:00+0000 hook=no_edit_on_main blocked=1",
    ].join("\n") + "\n");
    deps.auditPath = auditPath;
    const page = await readClaudeTracePage("s1", null, 30, deps);
    const audits = page.events.filter((event) => event.name === "hook_audit");
    expect(audits).toHaveLength(1);
    expect(audits[0].provenance.sourceOrdinal).toBe(1);
    expect(audits[0].attributes).toMatchObject({ "coderails.start_time.basis": "source",
      "coderails.end_time.basis": "unavailable", "coderails.duration_ms": null,
      "coderails.duration.basis": "unavailable" });
    expect(JSON.stringify(page)).not.toContain("Sensitive");
    expect((await readClaudeTraceDetail("s1", audits[0].provenance.sourceRef, deps)).content).toContain("Sensitive");
    await writeFile(auditPath, (await readFile(auditPath, "utf8")).replace("session=s1", "session=s2"));
    await expect(readClaudeTraceDetail("s1", audits[0].provenance.sourceRef, deps)).rejects.toThrow(/unavailable/i);
  });

  it("retrieves a large record only in detail and stops before reading a source above the scan limit", async () => {
    const { deps, parent, rows } = await fixture();
    const large = "L".repeat(1024 * 1024);
    await writeFile(parent, [...rows, { type: "user", sessionId: "s1", message: large }].map((row) => JSON.stringify(row)).join("\n") + "\n");
    const page = await readClaudeTracePage("s1", null, 30, deps);
    const record = page.events.find((event) => event.provenance.sourceId === "project/s1.jsonl" && event.provenance.sourceOrdinal === rows.length + 1)!;
    expect(JSON.stringify(page)).not.toContain(large);
    const detail = await readClaudeTraceDetail("s1", record.provenance.sourceRef, deps);
    expect(detail.content).toContain(large);
    expect((await stat(parent)).size).toBeGreaterThan(1024 * 1024);
    await truncate(parent, 64 * 1024 * 1024 + 1);
    const read = deps.fs.readFile;
    let nativeReads = 0;
    deps.fs.readFile = async (path) => { if (path === parent) nativeReads++; return read(path); };
    const stopped = await readClaudeTracePage("s1", null, 30, deps);
    expect(stopped.truncated).toBe(true);
    expect(nativeReads).toBe(0);
    expect((await stat(parent)).size).toBe(64 * 1024 * 1024 + 1);
  });

  it("indexes graph retry, hard stop, bound evidence, and completion artifacts by source reference", async () => {
    const { deps } = await fixture();
    const graphRoot = join(deps.cacheRoot, "graph-state");
    await mkdir(graphRoot, { recursive: true });
    deps.graphRoot = graphRoot;
    await writeFile(join(graphRoot, "progress.json"), JSON.stringify({
      schema_version: 3, session_id: "s1", loop_id: "l1", revision: 1,
      graph: { hard_stop: { node: "U1", reason: "sensitive reason" },
        nodes: { U1: { status: "stale", retry: { attempts: 1, max: 5 }, respawn: { generation: 1 },
          evidence: [{ kind: "claude_agent", attempt: 1, wave_id: "w1", tool_use_id: "tool-1",
            record_uuid: "r1", subagent_type: "worker", outcome: "stale", agent_id: "a1" }] } } },
    }));
    for (const name of ["evals", "proof", "retro"])
      await writeFile(join(graphRoot, `${name}.json`), JSON.stringify({ schema_version: 1, secret: "Sensitive artifact" }));
    const manifest = await collectClaudeSessionTrace("s1", deps);
    const page = await readClaudeTracePage("s1", null, 100, deps);
    expect(manifest.complete).toBe(true);
    expect(manifest.sources.map((item) => item.sourceId)).toContain("graph/progress.json");
    expect(page.events.map((event) => event.name)).toEqual(expect.arrayContaining([
      "graph_retry", "graph_hard_stop", "graph_evidence", "evals_reference", "proof_reference", "retro_reference",
    ]));
    expect(page.events.filter((event) => event.provenance.sourceId.startsWith("graph/"))
      .every((event) => event.startTimeUnixNano === null && event.attributes["coderails.start_time.basis"] === "unavailable" &&
        event.attributes["coderails.end_time.basis"] === "unavailable" &&
        event.attributes["coderails.duration_ms"] === null && event.attributes["coderails.duration.basis"] === "unavailable")).toBe(true);
    expect(JSON.stringify({ manifest, page })).not.toContain("Sensitive artifact");
    const evidence = page.events.find((event) => event.name === "graph_evidence")!;
    expect((await readClaudeTraceDetail("s1", evidence.provenance.sourceRef, deps)).content).toContain("claude_agent");
  });

  it("marks graph evidence incomplete when its native call or identity is foreign", async () => {
    const { deps } = await fixture();
    const graphRoot = join(deps.cacheRoot, "graph-state");
    await mkdir(graphRoot, { recursive: true });
    deps.graphRoot = graphRoot;
    await writeFile(join(graphRoot, "progress.json"), JSON.stringify({
      schema_version: 3, session_id: "s1", loop_id: "l1", revision: 1,
      graph: { hard_stop: null, nodes: { U1: { status: "done", retry: { attempts: 0 },
        respawn: { generation: 0 }, evidence: [{ kind: "claude_agent", attempt: 1, wave_id: "w1",
          tool_use_id: "foreign", record_uuid: "r1", subagent_type: "worker", outcome: "done", agent_id: "a1" }] } } },
    }));
    const manifest = await collectClaudeSessionTrace("s1", deps);
    expect(manifest.complete).toBe(false);
    expect(manifest.errors.join(" ")).toMatch(/graph evidence/i);
  });

  it("does not certify a done graph reference without native completion notification", async () => {
    const { deps } = await fixture();
    const graphRoot = join(deps.cacheRoot, "graph-state");
    await mkdir(graphRoot, { recursive: true });
    deps.graphRoot = graphRoot;
    await writeFile(join(graphRoot, "progress.json"), JSON.stringify({
      schema_version: 3, session_id: "s1", loop_id: "l1", revision: 1,
      graph: { hard_stop: null, nodes: { U1: { status: "done", retry: { attempts: 0 },
        respawn: { generation: 0 }, evidence: [{ kind: "claude_agent", attempt: 1, wave_id: "w1",
          tool_use_id: "tool-1", record_uuid: "r1", subagent_type: "worker", outcome: "done", agent_id: "a1" }] } } },
    }));
    const manifest = await collectClaudeSessionTrace("s1", deps);
    expect(manifest.complete).toBe(false);
    expect(manifest.errors.join(" ")).toMatch(/completion notification/i);
  });

  it("accepts mirrored native completion notices but rejects conflicting notices", async () => {
    const { deps, parent, rows } = await fixture();
    const notice = "<task-notification><tool-use-id>tool-1</tool-use-id><task-id>a1</task-id>" +
      "<status>completed</status><result>Finished</result></task-notification>";
    const queue = { type: "queue-operation", sessionId: "s1", content: notice };
    const harness = { type: "user", sessionId: "s1", origin: { kind: "task-notification" },
      message: { content: notice } };
    const graphRoot = join(deps.cacheRoot, "graph-state");
    await mkdir(graphRoot, { recursive: true });
    deps.graphRoot = graphRoot;
    await writeFile(join(graphRoot, "progress.json"), JSON.stringify({
      schema_version: 3, session_id: "s1", loop_id: "l1", revision: 1,
      graph: { hard_stop: null, nodes: { U1: { status: "done", retry: { attempts: 0 },
        respawn: { generation: 0 }, evidence: [{ kind: "claude_agent", attempt: 1, wave_id: "w1",
          tool_use_id: "tool-1", record_uuid: "r1", subagent_type: "worker", outcome: "done", agent_id: "a1" }] } } },
    }));
    const writeRows = async (extra: Record<string, unknown>[]) =>
      writeFile(parent, [...rows, ...extra].map((row) => JSON.stringify(row)).join("\n") + "\n");
    await writeRows([{ type: "user", sessionId: "s1", message: { content: notice } }]);
    expect((await collectClaudeSessionTrace("s1", deps)).complete).toBe(false);
    await writeRows([queue, harness]);
    expect((await collectClaudeSessionTrace("s1", deps)).complete).toBe(true);

    const conflicting = { ...harness, message: { content: notice.replace("<task-id>a1</task-id>",
      "<task-id>other</task-id>") } };
    await writeRows([queue, harness, conflicting]);
    const invalid = await collectClaudeSessionTrace("s1", deps);
    expect(invalid.complete).toBe(false);
    expect(invalid.errors.join(" ")).toMatch(/completion notification/i);
  });
});
