import { TRACE_SCHEMA_VERSION, serializeTraceEvent, type SourceRef, type TraceAttribute, type TraceCollectionDeps, type TraceEvent, type TraceManifest, type NativeSessionSummary } from "./sessionTraceSchema";
import { record, nonempty } from "./sessionTraceSchema";

// Claude's index is deliberately disposable. Native transcript bytes are read
// again for detail requests and are never copied into the index.
import { createHash } from "node:crypto";
import { mkdir, readdir, rename, rmdir, stat as nodeStat, unlink, writeFile as nodeWriteFile } from "node:fs/promises";
import { basename, dirname, join, relative, sep } from "node:path";
import { setTimeout as delay } from "node:timers/promises";

export const CLAUDE_PARSER_VERSION = 4;
const MAX_SOURCE_SCAN_BYTES = 64 * 1024 * 1024;
export function safeReadError(error: unknown): string {
  if (error instanceof Error && error.message.startsWith("source exceeds trace scan limit:"))
    return "source exceeds trace scan limit";
  if (error instanceof Error && error.message.startsWith("malformed or truncated JSONL:"))
    return "malformed or truncated JSONL source";
  return "unreadable or invalid source";
}
export type NativeRecord = Record<string, unknown>;
export type Source = { path: string; id: string; text: string; rows: NativeRecord[]; ordinals: number[]; fingerprint: string; cursor: string };

export function obj(value: unknown): NativeRecord | null {
  return record(value) ? value : null;
}

export function hash(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

export function safeSession(sessionId: string): boolean {
  return /^[A-Za-z0-9_-]+$/.test(sessionId);
}

export function claudeUnavailableSummary(nativeSessionId: string, projectLabel: string): NativeSessionSummary {
  const shortId = nativeSessionId.length > 12 ? nativeSessionId.slice(0, 8) : nativeSessionId;
  return { nativeSessionId, provider: "claude", projectLabel, displayLabel: `${projectLabel} · ${shortId}`,
    lastActivity: { value: null, basis: "unavailable" } };
}

export function claudeSessionSummary(nativeSessionId: string, projectLabel: string, text: string): NativeSessionSummary {
  let latest: number | null = null;
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    let row: NativeRecord;
    try {
      const parsed: unknown = JSON.parse(line);
      const value = obj(parsed);
      if (!value) return claudeUnavailableSummary(nativeSessionId, projectLabel);
      row = value;
    } catch { return claudeUnavailableSummary(nativeSessionId, projectLabel); }
    if (typeof row.timestamp !== "string") continue;
    const milliseconds = Date.parse(row.timestamp);
    if (Number.isFinite(milliseconds) && (latest === null || milliseconds > latest)) latest = milliseconds;
  }
  const shortId = nativeSessionId.length > 12 ? nativeSessionId.slice(0, 8) : nativeSessionId;
  return { nativeSessionId, provider: "claude", projectLabel, displayLabel: `${projectLabel} · ${shortId}`,
    lastActivity: latest === null ? { value: null, basis: "unavailable" } :
      { value: new Date(latest).toISOString(), basis: "observed" } };
}

export function cacheDir(sessionId: string, deps: TraceCollectionDeps): string {
  if (!safeSession(sessionId)) throw new TypeError("Invalid native session ID");
  return join(deps.cacheRoot, "claude", sessionId);
}

export async function parentPath(sessionId: string, deps: TraceCollectionDeps): Promise<string> {
  if (!safeSession(sessionId)) throw new TypeError("Invalid native session ID");
  const projects = await readdir(deps.sourceRoot, { withFileTypes: true });
  const matches: string[] = [];
  for (const project of projects) {
    if (!project.isDirectory()) continue;
    const candidate = join(deps.sourceRoot, project.name, `${sessionId}.jsonl`);
    try {
      if ((await nodeStat(candidate)).isFile()) matches.push(candidate);
    } catch { /* another project may own this session */ }
  }
  if (matches.length !== 1) throw new Error("Claude session transcript must resolve uniquely");
  return matches[0];
}

export async function source(path: string, deps: TraceCollectionDeps): Promise<Source> {
  const metadata = await deps.fs.stat(path) as { dev?: number; ino?: number; size?: number; mtimeMs?: number };
  if (typeof metadata.size === "number" && metadata.size > MAX_SOURCE_SCAN_BYTES)
    throw new Error(`source exceeds trace scan limit: ${relative(deps.sourceRoot, path)}`);
  const text = await deps.fs.readFile(path);
  if (Buffer.byteLength(text, "utf8") > MAX_SOURCE_SCAN_BYTES)
    throw new Error(`source exceeds trace scan limit: ${relative(deps.sourceRoot, path)}`);
  const id = relative(deps.sourceRoot, path).split(sep).join("/");
  const lines = text.split("\n");
  if (lines.at(-1) === "") lines.pop();
  const rows: NativeRecord[] = [];
  const ordinals: number[] = [];
  for (const [index, line] of lines.entries()) {
    if (!line.trim()) continue;
    let parsed: unknown;
    try { parsed = JSON.parse(line); } catch { throw new Error(`malformed or truncated JSONL: ${id}:${index + 1}`); }
    const value = obj(parsed);
    if (!value) throw new Error(`malformed JSONL object: ${id}:${index + 1}`);
    rows.push(value);
    ordinals.push(index + 1);
  }
  const identity = [metadata.dev, metadata.ino, metadata.size, metadata.mtimeMs].join(":");
  return { path, id, text, rows, ordinals, fingerprint: `sha256:${hash(text)};identity:${identity}`, cursor: String(lines.length) };
}

export async function teammateChild(parentTranscriptPath: string, sessionId: string, name: string,
  teamName: string, prompt: string, deps: TraceCollectionDeps): Promise<{ childId: string; child: Source; metadataSources: Source[] }> {
  const subagentsDir = join(dirname(parentTranscriptPath), sessionId, "subagents");
  const entries = (await readdir(subagentsDir)).filter((entry) => /^agent-[A-Za-z0-9_-]+\.meta\.json$/.test(entry));
  const matches: Array<{ childId: string; transcriptPath: string }> = [];
  const metadataSources: Source[] = [];
  for (const entry of entries) {
    const match = /^agent-([A-Za-z0-9_-]+)\.meta\.json$/.exec(entry);
    if (!match) continue;
    try {
      const metadata = await source(join(subagentsDir, entry), deps);
      metadataSources.push(metadata);
      if (metadata.rows.length === 1 && metadata.rows[0].name === name && metadata.rows[0].teamName === teamName)
        matches.push({ childId: match[1], transcriptPath: join(subagentsDir, `agent-${match[1]}.jsonl`) });
    } catch { /* malformed sidecars cannot authorize a child join */ }
  }
  if (matches.length !== 1) throw new Error("ambiguous or missing teammate sidecar");
  const [{ childId, transcriptPath }] = matches;
  const child = await source(transcriptPath, deps);
  if (child.rows.some((row) => row.sessionId !== sessionId || row.agentId !== childId || row.isSidechain !== true))
    throw new Error("foreign child identity or prompt");
  const first = obj(child.rows[0]?.message);
  const wrapper = typeof first?.content === "string"
    ? /^<teammate-message(?:\s[^>]*)?>\n([\s\S]*)\n<\/teammate-message>$/.exec(first.content) : null;
  if (first?.role !== "user" || !wrapper || wrapper[1] !== prompt)
    throw new Error("foreign child identity or prompt");
  return { childId, child, metadataSources };
}

export async function artifactSource(path: string, name: string, deps: TraceCollectionDeps): Promise<Source> {
  const metadata = await deps.fs.stat(path) as { dev?: number; ino?: number; size?: number; mtimeMs?: number };
  if (typeof metadata.size === "number" && metadata.size > MAX_SOURCE_SCAN_BYTES)
    throw new Error(`source exceeds trace scan limit: graph/${name}`);
  const text = await deps.fs.readFile(path);
  return { path, id: `graph/${name}`, text, rows: [], ordinals: [],
    fingerprint: `sha256:${hash(text)};identity:${[metadata.dev, metadata.ino, metadata.size, metadata.mtimeMs].join(":")}`,
    cursor: "1" };
}

export async function auditSource(path: string, deps: TraceCollectionDeps): Promise<Source> {
  const metadata = await deps.fs.stat(path) as { dev?: number; ino?: number; size?: number; mtimeMs?: number };
  if (typeof metadata.size === "number" && metadata.size > MAX_SOURCE_SCAN_BYTES)
    throw new Error("source exceeds trace scan limit: hook audit");
  const text = await deps.fs.readFile(path);
  if (Buffer.byteLength(text, "utf8") > MAX_SOURCE_SCAN_BYTES)
    throw new Error("source exceeds trace scan limit: hook audit");
  return { path, id: "audit/discipline.log", text, rows: [], ordinals: [],
    fingerprint: `sha256:${hash(text)};identity:${[metadata.dev, metadata.ino, metadata.size, metadata.mtimeMs].join(":")}`,
    cursor: String(text.split("\n").filter(Boolean).length) };
}

export function auditEvents(sessionId: string, src: Source): TraceEvent[] {
  const events: TraceEvent[] = [];
  for (const [index, line] of src.text.split("\n").entries()) {
    const tokens = line.split(/\s+/);
    if (!tokens.includes(`session=${sessionId}`)) continue;
    const hook = tokens.find((token) => /^hook=[a-z0-9_-]+$/.test(token))?.slice(5);
    if (!hook) continue;
    const ordinal = index + 1;
    const eventId = hash(`claude:${sessionId}:${src.id}:${ordinal}:hook_audit`);
    const flagged = tokens.some((token) => ["blocked=1", "denied=1", "decision=deny"].includes(token));
    const startTime = nano(tokens[0]);
    events.push({ schemaVersion: TRACE_SCHEMA_VERSION, eventId, traceId: hash(`claude:${sessionId}`).slice(0, 32),
      spanId: eventId.slice(0, 16), parentSpanId: null, name: "hook_audit", kind: "internal",
      status: flagged ? { value: "error", basis: "source" } : { value: "unavailable", basis: "unavailable" },
      startTimeUnixNano: startTime, endTimeUnixNano: null, events: [],
      attributes: { "coderails.source.ordinal": ordinal, "coderails.actor.kind": "orchestrator",
        "coderails.start_time.basis": startTime === null ? "unavailable" : "source",
        "coderails.end_time.basis": "unavailable",
        "coderails.duration_ms": null, "coderails.duration.basis": "unavailable",
        "coderails.evidence.kind": "hook_audit", "coderails.evidence.id": hook },
      provenance: { provider: "claude", nativeSessionId: sessionId, sourceId: src.id,
        sourceOrdinal: ordinal, basis: "observed",
        sourceRef: { kind: "claude_hook_audit_record", recordId: `audit:${ordinal}`, ordinal } } });
  }
  return events;
}

export function blocks(row: NativeRecord): NativeRecord[] {
  const content = obj(row.message)?.content;
  return Array.isArray(content) ? content.filter((item): item is NativeRecord => obj(item) !== null) : [];
}

export function toolBlocks(row: NativeRecord): Array<{ block: NativeRecord; item: number }> {
  const content = obj(row.message)?.content;
  if (!Array.isArray(content)) return [];
  return content.flatMap((value, item) => {
    const block = obj(value);
    return block && (block.type === "tool_use" || block.type === "tool_result") ? [{ block, item }] : [];
  });
}

export function explicitBlockedLaunch(src: Source, callId: string, result: NativeRecord): boolean {
  if (result.is_error !== true) return false;
  const matches = src.rows.flatMap((row) => toolBlocks(row).filter(({ block }) =>
    block.type === "tool_result" && block.tool_use_id === callId).map(({ block }) => block));
  return matches.length === 1 && matches[0].is_error === true && typeof matches[0].content === "string" &&
    matches[0].content.includes("[loop-dispatch-guard] Blocked");
}

export function dispatch(block: NativeRecord, sessionId: string): NativeRecord | null {
  if (block.type !== "tool_use" || block.name !== "Agent") return null;
  const input = obj(block.input);
  const prompt = input?.prompt;
  if (typeof prompt !== "string" || !prompt.startsWith("CODERAILS_GRAPH_DISPATCH=")) return null;
  const line = prompt.split("\n", 1)[0].slice("CODERAILS_GRAPH_DISPATCH=".length);
  let envelope: unknown;
  try { envelope = JSON.parse(line); } catch { return null; }
  const value = obj(envelope);
  if (!value || Object.keys(value).sort().join(",") !== "loop_id,node_id,revision,session_id,wave_id" ||
    value.session_id !== sessionId || !nonempty(value.loop_id) || !nonempty(value.node_id) ||
    !nonempty(value.wave_id) || !Number.isSafeInteger(value.revision) || Number(value.revision) < 1 ||
    !nonempty(block.id) || !nonempty(input?.subagent_type)) return null;
  return { ...value, prompt, callId: block.id, role: input.subagent_type };
}

export function nano(timestamp: unknown): string | null {
  if (typeof timestamp !== "string" ||
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})$/.test(timestamp)) return null;
  const milliseconds = Date.parse(timestamp);
  return Number.isFinite(milliseconds) ? (BigInt(milliseconds) * BigInt(1000000)).toString() : null;
}

export function makeEvent(sessionId: string, src: Source, ordinal: number, row: NativeRecord,
  actor: "orchestrator" | "worker", childId: string | null, parentSpanId: string | null,
  ownership: NativeRecord | null, block: NativeRecord | null = null, itemIndex = -1,
  parentSourceRef: SourceRef | null = null): TraceEvent {
  const sourceRef: SourceRef = { kind: actor === "worker" ? "claude_child_record" : "claude_parent_record",
    recordId: `${src.id}:${ordinal}${itemIndex >= 0 ? `:item:${itemIndex}` : ""}`, ordinal };
  const firstTool = block;
  const name = firstTool?.type === "tool_use" && typeof firstTool.name === "string" ? "tool_request" :
    firstTool?.type === "tool_result" ? "tool_result" : typeof row.type === "string" ? row.type : "record";
  const attributes: Record<string, TraceAttribute> = {
    "coderails.source.ordinal": ordinal,
    "coderails.actor.kind": actor,
    "coderails.end_time.basis": "unavailable",
    "coderails.duration_ms": null,
    "coderails.duration.basis": "unavailable",
  };
  if (itemIndex >= 0) attributes["coderails.source.item"] = itemIndex;
  if (childId) attributes["coderails.actor.id"] = childId;
  if (parentSpanId && parentSourceRef) {
    attributes["coderails.parent_join.basis"] = "derived";
    attributes["coderails.parent_join.method"] = "native_agent_call";
    attributes["coderails.parent_join.parent_source_ref"] = JSON.stringify(parentSourceRef);
    attributes["coderails.parent_join.child_source_ref"] = JSON.stringify(sourceRef);
  }
  if (firstTool?.type === "tool_use" && typeof firstTool.name === "string") attributes["tool.name"] = firstTool.name;
  const callId = firstTool?.id ?? firstTool?.tool_use_id;
  if (typeof callId === "string") attributes["coderails.native.call_id"] = callId;
  if (ownership) {
    attributes["coderails.loop.id"] = String(ownership.loop_id);
    attributes["coderails.wave.id"] = String(ownership.wave_id);
    attributes["coderails.node.id"] = String(ownership.node_id);
    attributes["coderails.graph.revision"] = Number(ownership.revision);
  }
  if (childId && ownership) attributes["coderails.child.id"] = childId;
  const message = obj(row.message);
  if (typeof message?.model === "string") attributes["gen_ai.response.model"] = message.model;
  const usage = obj(message?.usage);
  if (typeof usage?.input_tokens === "number") attributes["gen_ai.usage.input_tokens"] = usage.input_tokens;
  if (typeof usage?.output_tokens === "number") attributes["gen_ai.usage.output_tokens"] = usage.output_tokens;
  const id = hash(`claude:${sessionId}:${src.id}:${ordinal}:${itemIndex}:${name}`);
  const time = nano(row.timestamp);
  attributes["coderails.start_time.basis"] = time === null ? "unavailable" : "source";
  return {
    schemaVersion: TRACE_SCHEMA_VERSION, eventId: id, traceId: hash(`claude:${sessionId}`).slice(0, 32),
    spanId: id.slice(0, 16), parentSpanId, name, kind: "internal",
    status: firstTool?.type === "tool_result" && firstTool.is_error === true ?
      { value: "error", basis: "source" } : { value: "unavailable", basis: "unavailable" },
    startTimeUnixNano: time, endTimeUnixNano: null,
    events: [], attributes,
    provenance: { provider: "claude", nativeSessionId: sessionId, sourceId: src.id,
      sourceOrdinal: ordinal, basis: "observed", sourceRef },
  };
}

export function childValid(src: Source, sessionId: string, agentId: string, prompt: string, role: string): boolean {
  if (!src.rows.length) return false;
  if (src.rows.some((row) => row.sessionId !== sessionId || row.agentId !== agentId || row.isSidechain !== true)) return false;
  const first = obj(src.rows[0].message);
  if (first?.role !== "user" || first.content !== prompt) return false;
  const roles = new Set(src.rows.map((row) => row.attributionAgent).filter((item) => item !== undefined));
  return roles.size === 0 || (roles.size === 1 && roles.has(role));
}

export function graphEvent(sessionId: string, src: Source, ordinal: number, name: string, pointer: string,
  attributes: Record<string, TraceAttribute>): TraceEvent {
  const event = makeEvent(sessionId, src, ordinal, { type: name }, "orchestrator", null, null, null);
  const eventId = hash(`claude:${sessionId}:${src.id}:${pointer}:${name}`);
  return { ...event, name, eventId, spanId: eventId.slice(0, 16), attributes: { ...event.attributes, ...attributes },
    provenance: { ...event.provenance, sourceRef: {
      kind: "claude_graph_record", recordId: `${basename(src.path)}#${pointer}`, ordinal,
    } } };
}

export function pointerPart(value: string): string {
  return value.replace(/~/g, "~0").replace(/\//g, "~1");
}

export function completedNotification(parent: Source, callId: string, agentId: string): boolean {
  const notices: Array<{ call: string; agent: string; status: string; result: string }> = [];
  for (const row of parent.rows) {
    const origin = obj(row.origin);
    const content = row.type === "queue-operation" ? row.content :
      row.type === "user" && origin?.kind === "task-notification" ? obj(row.message)?.content : null;
    if (typeof content !== "string") continue;
    for (const match of content.matchAll(/<task-notification>([\s\S]*?)<\/task-notification>/g)) {
      const field = (tag: string) => new RegExp(`<${tag}>([\\s\\S]*?)<\\/${tag}>`).exec(match[1])?.[1] ?? "";
      notices.push({ call: field("tool-use-id"), agent: field("task-id"),
        status: field("status"), result: field("result") });
    }
  }
  const matches = notices.filter((item) => item.call === callId);
  return matches.length > 0 && matches.every((item) => item.agent === agentId &&
    item.status === "completed" && item.result.trim().length > 0);
}

export function terminalChild(child: Source, role: string): boolean {
  const roles = new Set(child.rows.map((row) => row.attributionAgent).filter((item) => item !== undefined));
  if (roles.size !== 1 || !roles.has(role)) return false;
  const assistants = child.rows.filter((row) => row.type === "assistant");
  const last = assistants.at(-1);
  const message = obj(last?.message);
  const content = last ? blocks(last) : [];
  return message?.role === "assistant" &&
    (message.stop_reason === "end_turn" || message.stop_reason === "stop_sequence") &&
    content.some((block) => block.type === "text" && typeof block.text === "string" && block.text.trim()) &&
    !content.some((block) => block.type === "tool_use") &&
    !last?.isApiErrorMessage && !last?.is_api_error_message && !last?.error;
}

async function withCacheLock(dir: string, action: () => Promise<void>): Promise<void> {
  await mkdir(dir, { recursive: true });
  const lock = join(dir, ".write-lock");
  const deadline = Date.now() + 5000;
  while (true) {
    try { await mkdir(lock); break; }
    catch (error) {
      if (!(error instanceof Error && "code" in error && error.code === "EEXIST")) throw error;
      try {
        if (Date.now() - (await nodeStat(lock)).mtimeMs > 30_000) await rmdir(lock);
      } catch { /* another writer may have released the lock */ }
      if (Date.now() >= deadline) throw new Error("Trace cache writer is busy");
      await delay(10);
    }
  }
  try { await action(); }
  finally { await rmdir(lock); }
}

export async function saveCache(dir: string, manifest: TraceManifest, events: TraceEvent[]): Promise<void> {
  await withCacheLock(dir, async () => {
    const suffix = `.${process.pid}.${Math.random().toString(36).slice(2)}.tmp`;
    const serialized = events.map(serializeTraceEvent).join("\n") + (events.length ? "\n" : "");
    manifest.eventFile = `events.${hash(serialized)}.jsonl`;
    const eventTmp = join(dir, `${manifest.eventFile}${suffix}`);
    const manifestTmp = join(dir, `manifest.json${suffix}`);
    await nodeWriteFile(eventTmp, serialized, "utf8");
    await nodeWriteFile(manifestTmp, JSON.stringify(manifest), "utf8");
    await rename(eventTmp, join(dir, manifest.eventFile));
    await rename(manifestTmp, join(dir, "manifest.json"));
    for (const name of await readdir(dir)) {
      if (/^events\.[a-f0-9]{64}\.jsonl$/.test(name) && name !== manifest.eventFile)
        await unlink(join(dir, name)).catch(() => {});
    }
  });
}

export async function clearCache(dir: string): Promise<void> {
  await withCacheLock(dir, async () => {
    for (const name of await readdir(dir))
      if (name === "manifest.json" || /^events\.[a-f0-9]{64}\.jsonl$/.test(name))
        await unlink(join(dir, name));
  });
}

export function cacheEventPath(dir: string, manifest: TraceManifest): string {
  if (!/^events\.[a-f0-9]{64}\.jsonl$/.test(manifest.eventFile)) throw new Error("Invalid cache event generation");
  return join(dir, manifest.eventFile);
}
