import { mkdir, readFile, readdir, stat, truncate, unlink, writeFile } from "node:fs/promises";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { fixture } from "./sessionTraceFixture";
import { collectCodexSessionTrace, listCodexSessions, readCodexTraceDetail, readCodexTracePage } from "../src/lib/collect/sessionTrace";

describe("Codex native session trace", () => {
  it("decodes source backed loop and node identities from a canonical native dispatch", async () => {
    const { deps } = await fixture();
    const page = await readCodexTracePage("parent", null, 30, deps);
    const dispatch = page.events.find((event) => event.attributes["coderails.native.call_id"] === "call-one");
    const worker = page.events.find((event) => event.attributes["coderails.actor.id"] === "child-one");
    for (const event of [dispatch, worker]) {
      expect(event?.attributes).toMatchObject({
        "coderails.loop.id": "loop",
        "coderails.node.id": "U3[1]",
        "coderails.attempt": 1,
      });
    }
    expect(worker?.parentSpanId).toBe(dispatch?.spanId);
  });

  it("orders cross-source timestamps and records the source-backed worker parent join", async () => {
    const { deps, parent, child, rows, children, save } = await fixture();
    await save(parent, [{ ...rows[0], timestamp: "2026-09-28T12:00:00Z" },
      { ...rows[1], timestamp: "2026-09-28T12:00:01Z" },
      { ...rows[2], timestamp: "2026-09-28T12:00:02Z" },
      { ...rows[3], timestamp: "2026-09-28T12:00:04Z" }]);
    await save(child, [{ ...children[0], timestamp: "2026-09-28T12:00:03Z" }, ...children.slice(1)]);
    const page = await readCodexTracePage("parent", null, 30, deps);
    const call = page.events.find((event) => event.provenance.sourceId.includes("parent") && event.provenance.sourceOrdinal === 2);
    const worker = page.events.find((event) => event.provenance.sourceId.includes("child-one") && event.provenance.sourceOrdinal === 1);
    expect(page.events.findIndex((event) => event.eventId === worker?.eventId)).toBeLessThan(
      page.events.findIndex((event) => event.provenance.sourceId.includes("parent") && event.provenance.sourceOrdinal === 4));
    expect(worker?.parentSpanId).toBe(call?.spanId);
    expect(worker?.attributes).toMatchObject({
      "coderails.parent_join.basis": "derived",
      "coderails.parent_join.method": "codex_dispatch_child_metadata",
      "coderails.parent_join.parent_source_ref": call?.provenance.sourceRef.recordId,
      "coderails.parent_join.child_source_ref": worker?.provenance.sourceRef.recordId,
    });
  });
  it("keeps native events visible while graph discovery ambiguity marks the page incomplete", async () => {
    const { deps } = await fixture();
    deps.graphDiscoveryError = "multiple matching graph roots (2)";
    const page = await readCodexTracePage("parent", null, 30, deps);
    expect(page.events.length).toBeGreaterThan(0);
    expect(page.complete).toBe(false);
    expect(page.errors).toContain("multiple matching graph roots (2)");
  });
  it("joins current dispatch only through matching activity and child metadata; keeps source order and details separate", async () => {
    const { deps } = await fixture();
    expect((await listCodexSessions(deps)).map((s) => s.nativeSessionId)).toContain("parent");
    const manifest = await collectCodexSessionTrace("parent", deps);
    expect(manifest.complete).toBe(true);
    const first = await readCodexTracePage("parent", null, 2, deps);
    const rest = await readCodexTracePage("parent", first.nextCursor, 30, deps);
    const events = [...first.events, ...rest.events];
    expect(events.some((e) => e.attributes["coderails.child.id"] === "child-one" && e.parentSpanId)).toBe(true);
    expect(events.find((e) => e.provenance.sourceOrdinal === 2 && e.provenance.sourceId.includes("parent"))?.startTimeUnixNano).toBeNull();
    expect(JSON.stringify({ manifest, events })).not.toContain("Sensitive prompt");
    const spawn = events.find((event) => event.provenance.sourceId.includes("parent") && event.provenance.sourceOrdinal === 2);
    expect((await readCodexTraceDetail("parent", spawn!.provenance.sourceRef, deps)).content).toContain("Sensitive prompt");
  });

  it("includes ordinary and nested workers and preserves a child's own tool call", async () => {
    const { deps, parent, child, rows, children, save } = await fixture();
    const ordinary = "ordinary_worker";
    const call = rows[1].payload as Record<string, unknown>;
    const childMeta = children[0].payload as Record<string, unknown>;
    const subagent = (childMeta.source as Record<string, unknown>).subagent as Record<string, unknown>;
    await save(parent, [rows[0], { ...rows[1], payload: { ...call, arguments: JSON.stringify({ task_name: ordinary, message: "Sensitive prompt" }) } },
      { ...rows[2], payload: { item: { type: "SubAgentActivity", kind: "started", id: "call-one", agent_thread_id: "child-one", agent_path: `/root/${ordinary}` } } },
      { type: "response_item", payload: { type: "function_call", name: "spawn_agent", namespace: "collaboration", call_id: "sibling-call", arguments: JSON.stringify({ task_name: "reviewer", message: "Sensitive review prompt" }) } },
      { type: "event_msg", payload: { item: { type: "SubAgentActivity", kind: "started", id: "sibling-call", agent_thread_id: "sibling", agent_path: "/root/reviewer" } } }, rows[3]]);
    await save(child, [{ ...children[0], payload: { ...childMeta, agent_path: `/root/${ordinary}`,
      source: { subagent: { ...subagent, thread_spawn: { ...(subagent.thread_spawn as object), agent_path: `/root/${ordinary}` } } } } },
      ...children.slice(1),
      { type: "response_item", payload: { type: "function_call", name: "exec_command", call_id: "child-tool-call", arguments: "Sensitive command" } },
      { type: "response_item", payload: { type: "function_call", name: "spawn_agent", namespace: "collaboration", call_id: "nested-call", arguments: JSON.stringify({ task_name: "researcher", message: "Sensitive nested prompt" }) } },
      { type: "event_msg", payload: { item: { type: "SubAgentActivity", kind: "started", id: "nested-call", agent_thread_id: "grandchild", agent_path: `/root/${ordinary}/researcher` } } }]);
    const grandchild = join(deps.sourceRoot, "2026", "09", "28", "rollout-grandchild.jsonl");
    await save(grandchild, [{ type: "session_meta", payload: { id: "grandchild", session_id: "parent", parent_thread_id: "child-one", thread_source: "subagent", agent_role: null,
      agent_path: `/root/${ordinary}/researcher`, source: { subagent: { thread_spawn: { parent_thread_id: "child-one", depth: 2, agent_role: null, agent_path: `/root/${ordinary}/researcher` } } } } }]);
    const sibling = join(deps.sourceRoot, "2026", "09", "28", "rollout-sibling.jsonl");
    await save(sibling, [{ type: "session_meta", payload: { id: "sibling", session_id: "parent", parent_thread_id: "parent", thread_source: "subagent", agent_role: null,
      agent_path: "/root/reviewer", source: { subagent: { thread_spawn: { parent_thread_id: "parent", depth: 1, agent_role: null, agent_path: "/root/reviewer" } } } } }]);
    const manifest = await collectCodexSessionTrace("parent", deps);
    const page = await readCodexTracePage("parent", null, 50, deps);
    expect(manifest.complete).toBe(true);
    expect(page.events.some((e) => e.attributes["coderails.actor.kind"] === "worker" && e.provenance.sourceId.includes("grandchild"))).toBe(true);
    const one = page.events.find((e) => e.provenance.sourceId.includes("child-one") && e.provenance.sourceOrdinal === 1);
    const two = page.events.find((e) => e.provenance.sourceId.includes("sibling") && e.provenance.sourceOrdinal === 1);
    expect(one?.parentSpanId).toBeTruthy();
    expect(two?.parentSpanId).toBeTruthy();
    expect(one?.parentSpanId).not.toBe(two?.parentSpanId);
    expect(page.events.find((e) => e.attributes["tool.name"] === "exec_command")?.attributes["coderails.native.call_id"]).toBe("child-tool-call");
    const nestedSpawn = page.events.find((e) => e.provenance.sourceId.includes("child-one") && e.attributes["coderails.native.call_id"] === "nested-call");
    expect(nestedSpawn?.attributes["coderails.actor.id"]).toBe("child-one");
    expect(nestedSpawn?.attributes["coderails.child.id"]).toBe("grandchild");
  });

  it("rejects a changed generation instead of mixing trace pages", async () => {
    const { deps, parent, rows, save } = await fixture();
    const first = await readCodexTracePage("parent", null, 2, deps);
    expect(first.nextCursor).toMatch(/^g:[a-f0-9]{64}:[0-9]+$/);
    await save(parent, [...rows, { type: "event_msg", payload: { type: "note" } }]);
    await expect(readCodexTracePage("parent", first.nextCursor, 20, deps)).rejects.toThrow(/stale/i);
  });

  it("bounds picker work and retains unavailable entries for oversized or unreadable files", async () => {
    const { deps, parent } = await fixture();
    const huge = join(deps.sourceRoot, "2026", "09", "28", "rollout-huge.jsonl");
    const untimed = join(deps.sourceRoot, "2026", "09", "28", "rollout-untimed.jsonl");
    await writeFile(huge, "");
    await writeFile(untimed, JSON.stringify({ type: "session_meta", payload: { id: "untimed" } }) + "\n");
    expect((await stat(untimed)).mtimeMs).toBeGreaterThan(0);
    const read = deps.fs.readFile;
    let nativeReads = 0;
    deps.fs.readFile = async (path) => { if (path.startsWith(deps.sourceRoot)) nativeReads++; return read(path); };
    deps.fs.stat = async (path) => path === huge ? { size: 1_000_000_000 } : path === parent ? Promise.reject(new Error("Sensitive failure")) : stat(path);
    const sessions = await listCodexSessions(deps);
    expect(nativeReads).toBe(1);
    expect(sessions.find((s) => s.nativeSessionId === "huge")?.lastActivity.basis).toBe("unavailable");
    expect(sessions.find((s) => s.nativeSessionId === "parent")?.lastActivity.basis).toBe("unavailable");
    expect(sessions.find((s) => s.nativeSessionId === "untimed")?.lastActivity).toEqual({ value: null, basis: "unavailable" });
  });

  it("uses session metadata cwd and valid native timestamps without reading prompt text", async () => {
    const { deps, parent, rows, save } = await fixture();
    rows[0].payload = { ...((rows[0].payload ?? {}) as object), cwd: "/Users/example/project-alpha" };
    rows.push({ timestamp: "2026-09-28T12:34:56Z", type: "event_msg", payload: { type: "note", message: "private prompt" } });
    rows.push({ timestamp: "invalid", type: "event_msg", payload: { type: "note", message: "private prompt" } });
    await save(parent, rows);
    const [session] = (await listCodexSessions(deps)).filter((item) => item.nativeSessionId === "parent");
    expect(session.projectLabel).toBe("project-alpha");
    expect(session.displayLabel).toBe("project-alpha · parent");
    expect(session.lastActivity).toEqual({ value: "2026-09-28T12:34:56.000Z", basis: "observed" });
    expect(JSON.stringify(session)).not.toContain("private prompt");
  });

  it("retires superseded cache generations and keeps concurrent page readers safe", async () => {
    const { deps, parent, rows, save } = await fixture();
    await collectCodexSessionTrace("parent", deps);
    for (let i = 0; i < 5; i++) {
      await save(parent, [...rows, ...Array.from({ length: i + 1 }, () => ({ type: "event_msg", payload: { type: "note" } }))]);
      await Promise.all([readCodexTracePage("parent", null, 2, deps), collectCodexSessionTrace("parent", deps)]);
    }
    const dir = join(deps.cacheRoot, "codex", "parent");
    const manifest = JSON.parse(await readFile(join(dir, "manifest.json"), "utf8"));
    const generations = (await readdir(dir)).filter((name) => /^events\.[a-f0-9]{64}\.jsonl$/.test(name));
    expect(generations).toContain(manifest.eventFile);
    expect(generations.length).toBeLessThanOrEqual(2);
  });

  it("retries a page read whose generation was retired during a rebuild", async () => {
    const { deps, parent, rows, save } = await fixture();
    await collectCodexSessionTrace("parent", deps);
    let resume!: () => void;
    let entered!: () => void;
    const paused = new Promise<void>((resolve) => { resume = resolve; });
    const reading = new Promise<void>((resolve) => { entered = resolve; });
    const read = deps.fs.readFile;
    let eventReads = 0;
    deps.fs.readFile = async (path) => {
      if (/events\.[a-f0-9]{64}\.jsonl$/.test(path) && ++eventReads === 2) { entered(); await paused; }
      return read(path);
    };
    const pending = readCodexTracePage("parent", null, 2, deps);
    await reading;
    for (let i = 0; i < 4; i++) {
      await save(parent, [...rows, ...Array.from({ length: i + 1 }, () => ({ type: "event_msg", payload: { type: "note" } }))]);
      await collectCodexSessionTrace("parent", deps);
    }
    resume();
    const page = await pending;
    expect(page.events).toHaveLength(2);
    expect(page.nextCursor).toMatch(/^g:[a-f0-9]{64}:2$/);
  });

  it("marks an unsupported spawn incomplete and clears old metadata after source loss", async () => {
    const { deps, parent, rows, save } = await fixture();
    const first = await collectCodexSessionTrace("parent", deps);
    await save(parent, [rows[0], { type: "response_item", payload: { type: "function_call", name: "spawn_agent", call_id: "bad", arguments: "invalid JSON" } }]);
    const unsupported = await collectCodexSessionTrace("parent", deps);
    expect(unsupported.complete).toBe(false);
    expect(unsupported.errors.join(" ")).toMatch(/unsupported spawn/i);
    await unlink(parent);
    const lost = await collectCodexSessionTrace("parent", deps);
    expect(lost.complete).toBe(false);
    const generations = (await readdir(join(deps.cacheRoot, "codex", "parent"))).filter((name) => /^events\.[a-f0-9]{64}\.jsonl$/.test(name));
    expect(generations).toEqual([lost.eventFile]);
    expect(generations).not.toContain(first.eventFile);
  });

  it("retires old native metadata after parent loss while retaining current audit events", async () => {
    const { deps, parent } = await fixture();
    const auditPath = join(deps.cacheRoot, "codex-audit.log");
    await mkdir(deps.cacheRoot, { recursive: true });
    await writeFile(auditPath, "2026-09-28T12:01:00+0000 hook=test_gate session=parent blocked=1\n");
    deps.auditPath = auditPath;
    const first = await collectCodexSessionTrace("parent", deps);
    await unlink(parent);
    const lost = await collectCodexSessionTrace("parent", deps);
    expect(lost.complete).toBe(false);
    expect(lost.sources.map((source) => source.sourceId)).toEqual(["audit/discipline.log"]);
    expect((await readCodexTracePage("parent", null, 30, deps)).events.map((event) => event.name)).toEqual(["hook_audit"]);
    const generations = (await readdir(join(deps.cacheRoot, "codex", "parent"))).filter((name) => /^events\.[a-f0-9]{64}\.jsonl$/.test(name));
    expect(generations).toEqual([lost.eventFile]);
    expect(generations).not.toContain(first.eventFile);
  });

  it("leaves duplicate calls and foreign children unresolved", async () => {
    const { deps, parent, child, rows, children, save } = await fixture();
    await save(parent, [rows[0], rows[1], rows[1], ...rows.slice(2)]);
    let manifest = await collectCodexSessionTrace("parent", deps);
    expect(manifest.complete).toBe(false);
    expect(manifest.errors.join(" ")).toMatch(/duplicate|ambiguous/i);
    expect((await readCodexTracePage("parent", null, 30, deps)).events.some((e) => e.attributes["coderails.actor.kind"] === "worker")).toBe(false);
    await save(parent, rows);
    await save(child, [{ ...children[0], payload: { ...(children[0].payload as object), parent_thread_id: "foreign" } }, ...children.slice(1)]);
    manifest = await collectCodexSessionTrace("parent", deps);
    expect(manifest.complete).toBe(false);
    expect(manifest.errors.join(" ")).toMatch(/foreign|child/i);
  });

  it("accepts the evidence reader's legacy dispatch shape", async () => {
    const { deps, parent, child, rows, children, save } = await fixture();
    const legacy = { type: "event_msg", payload: { item: { type: "CollabAgentToolCall", tool: "spawn_agent", status: "completed", id: "legacy", prompt: "loop_worker_55335b315d\nSensitive prompt", receiver_thread_ids: ["child-one"], receiver_agents: [{ thread_id: "child-one", agent_role: "worker", agent_nickname: "Nick" }] } } };
    await save(parent, [rows[0], legacy]);
    const meta = children[0].payload as Record<string, unknown>;
    const source = meta.source as Record<string, unknown>;
    const subagent = source.subagent as Record<string, unknown>;
    await save(child, [{ ...children[0], payload: { ...meta, agent_role: "worker", agent_nickname: "Nick", agent_path: null, source: { subagent: { ...subagent, thread_spawn: { parent_thread_id: "parent", depth: 1, agent_role: "worker", agent_nickname: "Nick", agent_path: null } } } } }, ...children.slice(1)]);
    const result = await collectCodexSessionTrace("parent", deps);
    expect(result.complete).toBe(true);
    const events = (await readCodexTracePage("parent", null, 30, deps)).events;
    const linked = events.filter((event) => event.attributes["coderails.child.id"] === "child-one");
    expect(linked.length).toBeGreaterThan(0);
    for (const event of linked) {
      expect(event.attributes["coderails.loop.id"]).toBeUndefined();
      expect(event.attributes["coderails.node.id"]).toBeUndefined();
      expect(event.attributes["coderails.attempt"]).toBeUndefined();
    }
  });

  it("invalidates same-size rewrite, truncation, and malformed JSONL", async () => {
    const { deps, parent } = await fixture();
    const first = await collectCodexSessionTrace("parent", deps);
    expect((await collectCodexSessionTrace("parent", deps)).generatedAt).toBe(first.generatedAt);
    await writeFile(parent, (await readFile(parent, "utf8")).replace("call-one", "call-two"));
    const second = await collectCodexSessionTrace("parent", deps);
    expect(second.sources[0].fingerprint).not.toBe(first.sources[0].fingerprint);
    expect(second.complete).toBe(false);
    await writeFile(parent, "{\"type\":\"session_meta\"\n");
    const third = await collectCodexSessionTrace("parent", deps);
    expect(third.complete).toBe(false);
    expect(third.errors.join(" ")).toMatch(/malformed|truncated/i);
  });

  it("publishes a manifest that names its own complete event generation", async () => {
    const { deps, parent, rows, save } = await fixture();
    await collectCodexSessionTrace("parent", deps);
    await save(parent, [...rows, { type: "event_msg", payload: { type: "note" } }]);
    await Promise.all([collectCodexSessionTrace("parent", deps), collectCodexSessionTrace("parent", deps)]);
    const manifest = JSON.parse(await readFile(join(deps.cacheRoot, "codex", "parent", "manifest.json"), "utf8"));
    expect(manifest.eventFile).toMatch(/^events\.[a-f0-9]{64}\.jsonl$/);
    const events = (await readFile(join(deps.cacheRoot, "codex", "parent", manifest.eventFile), "utf8")).split("\n").filter(Boolean);
    expect(events).toHaveLength(manifest.eventCount);
  });

  it("marks an oversized native source incomplete before reading it", async () => {
    const { deps, parent } = await fixture();
    const read = deps.fs.readFile;
    deps.fs.stat = async (path) => path === parent ? { size: 1_000_000_000 } : stat(path);
    deps.fs.readFile = async (path) => {
      if (path === parent) throw new Error("oversized source was read");
      return read(path);
    };
    const manifest = await collectCodexSessionTrace("parent", deps);
    expect(manifest.complete).toBe(false);
    expect(manifest.errors.join(" ")).toMatch(/scan limit/i);
    const page = await readCodexTracePage("parent", null, 20, deps);
    expect(page.events).toHaveLength(0);
    expect(page.truncated).toBe(true);
    expect(page.emittedEvents).toBe(0);
  });

  it("does not copy arbitrary read errors into the metadata cache", async () => {
    const { deps, parent } = await fixture();
    const read = deps.fs.readFile;
    deps.fs.readFile = async (path) => path === parent ? Promise.reject(new Error("Sensitive read failure")) : read(path);
    const manifest = await collectCodexSessionTrace("parent", deps);
    expect(manifest.complete).toBe(false);
    expect(JSON.stringify(manifest)).not.toContain("Sensitive");
  });

  it("indexes only hook audit lines explicitly scoped to this native session", async () => {
    const { deps } = await fixture();
    const auditPath = join(deps.cacheRoot, "codex-audit.log");
    await mkdir(deps.cacheRoot, { recursive: true });
    await writeFile(auditPath, [
      "2026-09-28T12:01:00+0000 hook=graph_completion_guard session=parent blocked=1 note=Sensitive",
      "2026-09-28T12:02:00+0000 hook=graph_completion_guard session=foreign blocked=1",
      "2026-09-28T12:03:00+0000 hook=no_edit_on_main decision=deny",
    ].join("\n") + "\n");
    deps.auditPath = auditPath;
    const page = await readCodexTracePage("parent", null, 30, deps);
    const audits = page.events.filter((event) => event.name === "hook_audit");
    expect(audits).toHaveLength(1);
    expect(audits[0].provenance.sourceOrdinal).toBe(1);
    expect(audits[0].attributes).toMatchObject({ "coderails.start_time.basis": "source",
      "coderails.end_time.basis": "unavailable", "coderails.duration_ms": null,
      "coderails.duration.basis": "unavailable" });
    expect(JSON.stringify(page)).not.toContain("Sensitive");
    expect((await readCodexTraceDetail("parent", audits[0].provenance.sourceRef, deps)).content).toContain("Sensitive");
    await writeFile(auditPath, (await readFile(auditPath, "utf8")).replace("session=parent", "session=forign"));
    await expect(readCodexTraceDetail("parent", audits[0].provenance.sourceRef, deps)).rejects.toThrow(/unavailable/i);
  });

  it("marks an audit record with invalid time as unavailable", async () => {
    const { deps } = await fixture();
    const auditPath = join(deps.cacheRoot, "codex-audit.log");
    await mkdir(deps.cacheRoot, { recursive: true });
    await writeFile(auditPath, "invalid-time hook=test_gate session=parent blocked=1\n");
    deps.auditPath = auditPath;
    const audits = (await readCodexTracePage("parent", null, 30, deps)).events.filter((event) => event.name === "hook_audit");
    expect(audits).toHaveLength(1);
    expect(audits[0].startTimeUnixNano).toBeNull();
    expect(audits[0].attributes["coderails.start_time.basis"]).toBe("unavailable");
  });

  it("retrieves a large record only in detail and stops before reading a source above the scan limit", async () => {
    const { deps, parent, rows, save } = await fixture();
    const large = "L".repeat(1024 * 1024);
    await save(parent, [...rows, { type: "event_msg", payload: { type: "note", body: large } }]);
    const page = await readCodexTracePage("parent", null, 30, deps);
    const record = page.events.find((event) => event.provenance.sourceId.endsWith("rollout-parent.jsonl") && event.provenance.sourceOrdinal === rows.length + 1)!;
    expect(JSON.stringify(page)).not.toContain(large);
    const detail = await readCodexTraceDetail("parent", record.provenance.sourceRef, deps);
    expect(detail.content).toContain(large);
    expect((await stat(parent)).size).toBeGreaterThan(1024 * 1024);
    await truncate(parent, 64 * 1024 * 1024 + 1);
    const read = deps.fs.readFile;
    let nativeReads = 0;
    deps.fs.readFile = async (path) => { if (path === parent) nativeReads++; return read(path); };
    const stopped = await readCodexTracePage("parent", null, 30, deps);
    expect(stopped.truncated).toBe(true);
    expect(nativeReads).toBe(0);
    expect((await stat(parent)).size).toBe(64 * 1024 * 1024 + 1);
  });

  it("keeps command, MCP, file change and missing usage metadata without cached bodies", async () => {
    const { deps, parent, rows, save } = await fixture();
    rows.push({ type: "response_item", payload: { type: "function_call", name: "exec_command", call_id: "cmd-1", arguments: "Sensitive command" } });
    rows.push({ type: "event_msg", payload: { item: { type: "McpToolCall", status: "failed", duration_ms: 42, tool: "lookup", result: "Sensitive result" } } });
    rows.push({ type: "event_msg", payload: { item: { type: "FileChange", changes: [{ path: "Sensitive path" }] } } });
    await save(parent, rows);
    const manifest = await collectCodexSessionTrace("parent", deps);
    const page = await readCodexTracePage("parent", null, 40, deps);
    expect(manifest.complete).toBe(true);
    expect(page.events.find((e) => e.attributes["tool.name"] === "exec_command")?.attributes["gen_ai.usage.input_tokens"]).toBeUndefined();
    expect(page.events.find((e) => e.name === "McpToolCall")?.status.value).toBe("error");
    expect(page.events.find((e) => e.name === "McpToolCall")?.attributes["coderails.duration_ms"]).toBe(42);
    expect(page.events.find((e) => e.name === "McpToolCall")?.attributes["coderails.duration.basis"]).toBe("source");
    expect(page.events.find((e) => e.name === "FileChange")?.attributes["coderails.file.change_count"]).toBe(1);
    expect(await readFile(join(deps.cacheRoot, "codex", "parent", manifest.eventFile), "utf8")).not.toMatch(/Sensitive command|Sensitive result|Sensitive path/);
  });

  it("indexes graph and completion references without promoting invalid native evidence", async () => {
    const { deps } = await fixture();
    deps.graphRoot = join(deps.cacheRoot, "graph-state");
    await mkdir(deps.graphRoot, { recursive: true });
    const progress = { schema_version: 3, session_id: "parent", loop_id: "loop", graph: {
      hard_stop: { node: "U3[1]", reason: "Sensitive reason" }, nodes: { "U3[1]": { retry: { attempts: 1 },
        evidence: [{ kind: "codex_agent", attempt: 1, wave_id: "wave-1", spawn_call_id: "call-one",
          agent_thread_id: "child-one", task_complete_turn_id: "turn-one" }] } } } };
    await writeFile(join(deps.graphRoot, "progress.json"), JSON.stringify(progress));
    for (const name of ["evals", "proof", "retro"])
      await writeFile(join(deps.graphRoot, `${name}.json`), JSON.stringify({ secret: "Sensitive artifact" }));
    const first = await collectCodexSessionTrace("parent", deps);
    expect(first.complete).toBe(true);
    const page = await readCodexTracePage("parent", null, 50, deps);
    expect(page.events.map((e) => e.name)).toEqual(expect.arrayContaining(["graph_retry", "graph_evidence", "graph_hard_stop", "evals_reference", "proof_reference", "retro_reference"]));
    for (const event of page.events.filter((e) => e.provenance.sourceId.startsWith("graph/"))) {
      expect(event.startTimeUnixNano).toBeNull();
      expect(event.attributes).toMatchObject({ "coderails.start_time.basis": "unavailable",
        "coderails.end_time.basis": "unavailable", "coderails.duration_ms": null,
        "coderails.duration.basis": "unavailable" });
    }
    expect(JSON.stringify(page)).not.toContain("Sensitive artifact");
    const ref = page.events.find((e) => e.name === "graph_evidence")!.provenance.sourceRef;
    expect((await readCodexTraceDetail("parent", ref, deps)).content).toContain("spawn_call_id");
    progress.graph.nodes["U3[1]"].evidence[0].agent_thread_id = "foreign";
    await writeFile(join(deps.graphRoot, "progress.json"), JSON.stringify(progress));
    const changed = await collectCodexSessionTrace("parent", deps);
    expect(changed.complete).toBe(false);
    expect(changed.errors.join(" ")).toMatch(/graph evidence/i);
  });
});
