import { createHash } from "node:crypto";
import { open, readdir } from "node:fs/promises";
import { basename, join, relative, sep } from "node:path";
import { TRACE_SCHEMA_VERSION, record, type SourceRef, type TraceAttribute, type TraceCollectionDeps, type TraceEvent } from "./traceSchema";

export const CODEX_PARSER_VERSION = 4;
export const MAX_SOURCE_SCAN_BYTES = 64 * 1024 * 1024;
export function safeReadError(error: unknown): string {
  return error instanceof Error && error.message.startsWith("source exceeds trace scan limit:")
    ? "source exceeds trace scan limit" : "unreadable or invalid source";
}
export type Row = Record<string, unknown>;
export type NativeSource = { path: string; id: string; text: string; rows: Row[]; ordinals: number[]; fingerprint: string; cursor: string; errors: string[] };
export type Dispatch = { callId: string; task: string | null; childId: string; nickname: string | null; path: string | null; role: string | null; ordinal: number };
export class TranscriptResolutionError extends Error {
  constructor(sessionId: string, readonly candidateCount: number) {
    super(`thread ${sessionId} must resolve to exactly one Codex transcript`);
  }
}

export function obj(value: unknown): Row | null { return record(value) ? value : null; }
export function hash(value: string): string { return createHash("sha256").update(value).digest("hex"); }
export function safeId(value: string): boolean { return /^[A-Za-z0-9_-]+$/.test(value); }
export function cacheDir(sessionId: string, deps: TraceCollectionDeps): string {
  if (!safeId(sessionId)) throw new TypeError("Invalid native session ID");
  return join(deps.cacheRoot, "codex", sessionId);
}
export function payload(row: Row): Row { return obj(row.payload) ?? row; }
function eventItem(row: Row): Row | null { return obj(payload(row).item); }
export function timeNano(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const ms = Date.parse(value);
  return Number.isFinite(ms) ? (BigInt(ms) * BigInt(1000000)).toString() : null;
}
export async function paths(root: string): Promise<string[]> {
  const out: string[] = [];
  async function visit(dir: string) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) await visit(path);
      else if (entry.isFile() && entry.name.endsWith(".jsonl")) out.push(path);
    }
  }
  try { await visit(root); } catch (error) {
    if (!(error instanceof Error && "code" in error && error.code === "ENOENT")) throw error;
  }
  return out.sort();
}
export async function isSubagentTranscript(path: string): Promise<boolean> {
  try {
    const file = await open(path, "r");
    try {
      const buffer = Buffer.alloc(64 * 1024);
      const { bytesRead } = await file.read(buffer, 0, buffer.length, 0);
      const prefix = buffer.toString("utf8", 0, bytesRead);
      const end = prefix.indexOf("\n");
      if (end < 0 && bytesRead === buffer.length) return false;
      const first = obj(JSON.parse(end < 0 ? prefix : prefix.slice(0, end)));
      return first?.type === "session_meta" && payload(first).thread_source === "subagent";
    } finally { await file.close(); }
  } catch { return false; }
}
export async function source(path: string, deps: TraceCollectionDeps): Promise<NativeSource> {
  const info = await deps.fs.stat(path) as { dev?: number; ino?: number; size?: number; mtimeMs?: number };
  if (typeof info.size === "number" && info.size > MAX_SOURCE_SCAN_BYTES)
    throw new Error(`source exceeds trace scan limit: ${relative(deps.sourceRoot, path)}`);
  const text = await deps.fs.readFile(path);
  if (Buffer.byteLength(text, "utf8") > MAX_SOURCE_SCAN_BYTES)
    throw new Error(`source exceeds trace scan limit: ${relative(deps.sourceRoot, path)}`);
  const id = relative(deps.sourceRoot, path).split(sep).join("/");
  const lines = text.split("\n");
  if (lines.at(-1) === "") lines.pop();
  const rows: Row[] = [], ordinals: number[] = [], errors: string[] = [];
  for (const [index, line] of lines.entries()) {
    try {
      const parsed = obj(JSON.parse(line));
      if (!parsed) throw new Error("object expected");
      rows.push(parsed); ordinals.push(index + 1);
    } catch { errors.push(`malformed or truncated JSONL: ${id}:${index + 1}`); }
  }
  return { path, id, text, rows, ordinals, errors,
    fingerprint: `sha256:${hash(text)};identity:${[info.dev, info.ino, info.size, info.mtimeMs].join(":")}`,
    cursor: String(lines.length) };
}
export async function transcript(sessionId: string, deps: TraceCollectionDeps): Promise<NativeSource> {
  if (!safeId(sessionId)) throw new TypeError("Invalid native session ID");
  const candidates = (await paths(deps.sourceRoot)).filter((path) => basename(path) === `rollout-${sessionId}.jsonl` || basename(path).endsWith(`-${sessionId}.jsonl`));
  if (candidates.length !== 1) throw new TranscriptResolutionError(sessionId, candidates.length);
  const src = await source(candidates[0], deps);
  return src;
}
function task(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const parts = /^loop_worker_([0-9a-f]+)(?:_([0-9a-f]+))?(?:_a([1-9][0-9]*))?$/.exec(value);
  if (!parts || parts[3] === "1") return false;
  const encoded = parts[2] ? [parts[1], parts[2]] : [parts[1]];
  return encoded.every((hex) => {
    if (hex.length % 2) return false;
    const decoded = Buffer.from(hex, "hex").toString("utf8");
    return decoded.length > 0 && Buffer.from(decoded).toString("hex") === hex;
  });
}
function canonicalTask(value: string): { loopId: string; nodeId: string; attempt: number } | null {
  if (/^loop_worker_[0-9a-f]+_a[1-9][0-9]*$/.test(value)) return null;
  const match = /^loop_worker_([0-9a-f]+)_([0-9a-f]+)(?:_a([1-9][0-9]*))?$/.exec(value);
  if (!match || match[1].length % 2 || match[2].length % 2) return null;
  const loopId = Buffer.from(match[1], "hex").toString("utf8");
  const nodeId = Buffer.from(match[2], "hex").toString("utf8");
  const attempt = match[3] ? Number(match[3]) : 1;
  if (!loopId || !nodeId || !Number.isSafeInteger(attempt) || attempt < 1 ||
    Buffer.from(loopId).toString("hex") !== match[1] || Buffer.from(nodeId).toString("hex") !== match[2] ||
    `loop_worker_${match[1]}_${match[2]}${attempt === 1 ? "" : `_a${attempt}`}` !== value) return null;
  return { loopId, nodeId, attempt };
}
function currentCall(row: Row, ordinal: number): { callId: string; task: string; role: string | null; ordinal: number } | null {
  const item = payload(row);
  if (row.type !== "response_item" || item.type !== "function_call" || item.name !== "spawn_agent" ||
    typeof item.call_id !== "string" || typeof item.arguments !== "string") return null;
  try {
    const args = obj(JSON.parse(item.arguments));
    if (!args || typeof args.task_name !== "string" || !safeId(args.task_name)) return null;
    const role = typeof args.agent_type === "string" && args.agent_type.trim() ? args.agent_type : null;
    if (args.agent_type !== undefined && !role) return null;
    if (!role && item.namespace !== "collaboration") return null;
    return { callId: item.call_id, task: args.task_name, role, ordinal };
  } catch { return null; }
}
function activity(row: Row, ordinal: number): { callId: string; childId: string; path: string; ordinal: number } | null {
  const item = eventItem(row);
  return row.type === "event_msg" && item?.type === "SubAgentActivity" && item.kind === "started" &&
    typeof item.id === "string" && typeof item.agent_thread_id === "string" && typeof item.agent_path === "string" ?
    { callId: item.id, childId: item.agent_thread_id, path: item.agent_path, ordinal } : null;
}
function legacy(row: Row, ordinal: number): Dispatch | null {
  const item = eventItem(row), receivers = item?.receiver_thread_ids, agents = item?.receiver_agents;
  if (row.type !== "event_msg" || item?.type !== "CollabAgentToolCall" || item.tool !== "spawn_agent" ||
    item.status !== "completed" || typeof item.id !== "string" || typeof item.prompt !== "string" ||
    !Array.isArray(receivers) || receivers.length !== 1 || !Array.isArray(agents) || agents.length !== 1) return null;
  const agent = obj(agents[0]);
  const graphTask = item.prompt.split("\n", 1)[0].replace(/^CODERAILS_GRAPH_TASK=/, "");
  if (!task(graphTask) || typeof receivers[0] !== "string" || !agent || agent.thread_id !== receivers[0] ||
    typeof agent.agent_role !== "string" || !agent.agent_role.trim() || typeof agent.agent_nickname !== "string") return null;
  return { callId: item.id, task: graphTask, childId: receivers[0], nickname: agent.agent_nickname,
    path: null, role: agent.agent_role, ordinal };
}
export function dispatches(parent: NativeSource, errors: string[], parentPath: string): Dispatch[] {
  const calls = new Map<string, Array<ReturnType<typeof currentCall>>>();
  const activities = new Map<string, Array<ReturnType<typeof activity>>>();
  const callCounts = new Map<string, number>();
  const legacyRows: Dispatch[] = [];
  parent.rows.forEach((row, i) => {
    const ordinal = parent.ordinals[i], item = payload(row);
    if (row.type === "response_item" && item.type === "function_call" && typeof item.call_id === "string")
      callCounts.set(item.call_id, (callCounts.get(item.call_id) ?? 0) + 1);
    const call = currentCall(row, ordinal);
    if (call) calls.set(call.callId, [...(calls.get(call.callId) ?? []), call]);
    else if (row.type === "response_item" && item.type === "function_call" && item.name === "spawn_agent")
      errors.push(`unsupported spawn call at ${ordinal}`);
    const started = activity(row, ordinal);
    if (started) activities.set(started.callId, [...(activities.get(started.callId) ?? []), started]);
    const old = legacy(row, ordinal);
    if (old) legacyRows.push(old);
  });
  const resolved = [...legacyRows];
  for (const [id, matches] of calls) {
    const acts = activities.get(id) ?? [];
    if (matches.length !== 1 || callCounts.get(id) !== 1 || acts.length !== 1) {
      errors.push(`ambiguous or duplicate spawn call ${id}`); continue;
    }
    const call = matches[0]!, act = acts[0]!;
    if (act.ordinal <= call.ordinal || act.path !== `${parentPath}/${call.task}`) {
      errors.push(`unresolved child activity for ${id}`); continue;
    }
    resolved.push({ callId: id, task: call.task, childId: act.childId, nickname: null,
      path: act.path, role: call.role, ordinal: call.ordinal });
  }
  for (const id of activities.keys()) if (!calls.has(id) && !legacyRows.some((row) => row.callId === id))
    errors.push(`unresolved child activity for ${id}`);
  const ids = new Map<string, number>(), children = new Map<string, number>();
  for (const item of resolved) {
    ids.set(item.callId, (ids.get(item.callId) ?? 0) + 1);
    children.set(item.childId, (children.get(item.childId) ?? 0) + 1);
  }
  return resolved.filter((item) => {
    const valid = ids.get(item.callId) === 1 && children.get(item.childId) === 1 && safeId(item.childId);
    if (!valid) errors.push(`ambiguous duplicate child identity ${item.childId}`);
    return valid;
  });
}
export function validChild(src: NativeSource, root: string, parent: string, depth: number, dispatch: Dispatch): boolean {
  const meta = payload(src.rows[0]), spawn = obj(obj(obj(meta.source)?.subagent)?.thread_spawn);
  return meta.id === dispatch.childId && meta.session_id === root && meta.parent_thread_id === parent &&
    meta.thread_source === "subagent" && meta.agent_role === dispatch.role &&
    (dispatch.nickname === null || meta.agent_nickname === dispatch.nickname) &&
    (meta.agent_path === undefined || meta.agent_path === dispatch.path) &&
    spawn?.parent_thread_id === parent && spawn.depth === depth && spawn.agent_role === dispatch.role &&
    spawn.agent_path === dispatch.path &&
    (dispatch.nickname === null || spawn.agent_nickname === dispatch.nickname);
}
export function terminalTurn(src: NativeSource): string | null {
  const startedAt = src.rows[0]?.timestamp;
  if (typeof startedAt !== "string") return null;
  const lifecycle = src.rows.filter((row) => typeof row.timestamp === "string" && row.timestamp >= startedAt)
    .map(payload).filter((item) => ["task_started", "task_complete", "turn_aborted"].includes(String(item.type)));
  const last = lifecycle.at(-1);
  if (last?.type !== "task_complete" || typeof last.turn_id !== "string") return null;
  const starts = lifecycle.filter((item) => item.type === "task_started" && item.turn_id === last.turn_id);
  const terminals = lifecycle.filter((item) => item.type !== "task_started" && item.turn_id === last.turn_id);
  return starts.length === 1 && terminals.length === 1 && lifecycle.filter((item) => item.type === "task_started").at(-1) === starts[0] ? last.turn_id : null;
}
export function nativeEvent(sessionId: string, src: NativeSource, ordinal: number, row: Row,
  actor: "orchestrator" | "worker", actorId: string | null, dispatch: Dispatch | null, parentSpanId: string | null): TraceEvent {
  const item = payload(row), nested = eventItem(row);
  const nativeName = row.type === "event_msg" ? nested?.type ?? item.type : item.type ?? row.type;
  const name = typeof nativeName === "string" && /^[A-Za-z][A-Za-z0-9_]{0,79}$/.test(nativeName) ? nativeName : "record";
  const startTimeUnixNano = timeNano(row.timestamp);
  const attributes: Record<string, TraceAttribute> = { "coderails.source.ordinal": ordinal,
    "coderails.actor.kind": actor, "coderails.start_time.basis": startTimeUnixNano === null ? "unavailable" : "source",
    "coderails.end_time.basis": "unavailable", "coderails.duration_ms": null,
    "coderails.duration.basis": "unavailable" };
  const tool = item.name ?? nested?.tool;
  if (typeof tool === "string" && /^[A-Za-z][A-Za-z0-9_.-]{0,79}$/.test(tool)) attributes["tool.name"] = tool;
  if (typeof item.call_id === "string") attributes["coderails.native.call_id"] = item.call_id;
  if (dispatch) {
    attributes["coderails.child.id"] = dispatch.childId;
    const identity = dispatch.task ? canonicalTask(dispatch.task) : null;
    if (identity) {
      attributes["coderails.loop.id"] = identity.loopId;
      attributes["coderails.node.id"] = identity.nodeId;
      attributes["coderails.attempt"] = identity.attempt;
    }
  }
  if (actor === "worker" && actorId) attributes["coderails.actor.id"] = actorId;
  const model = obj(item.info)?.model ?? item.model;
  if (typeof model === "string") attributes["gen_ai.response.model"] = model;
  const usage = obj(obj(item.info)?.total_token_usage);
  if (typeof usage?.input_tokens === "number") attributes["gen_ai.usage.input_tokens"] = usage.input_tokens;
  if (typeof usage?.output_tokens === "number") attributes["gen_ai.usage.output_tokens"] = usage.output_tokens;
  const duration = item.duration_ms ?? nested?.duration_ms;
  if (typeof duration === "number" && Number.isFinite(duration)) {
    attributes["coderails.duration_ms"] = duration;
    attributes["coderails.duration.basis"] = "source";
  }
  const changes = item.changes ?? nested?.changes ?? obj(item.file_change)?.changes;
  if (Array.isArray(changes)) attributes["coderails.file.change_count"] = changes.length;
  const id = hash(`codex:${sessionId}:${src.id}:${ordinal}:${name}`);
  const sourceRef: SourceRef = { kind: actor === "worker" ? "codex_child_record" : "codex_parent_record",
    recordId: `${src.id}:${ordinal}`, ordinal };
  const explicit = nested?.status ?? item.status;
  const status: TraceEvent["status"] = name === "turn_aborted" ? { value: "error", basis: "observed" } :
    name === "task_complete" ? { value: "ok", basis: "observed" } :
    explicit === "failed" || explicit === "error" ? { value: "error", basis: "source" } :
    explicit === "completed" || explicit === "success" ? { value: "ok", basis: "source" } :
    { value: "unavailable", basis: "unavailable" };
  return { schemaVersion: TRACE_SCHEMA_VERSION, eventId: id, traceId: hash(`codex:${sessionId}`).slice(0, 32),
    spanId: id.slice(0, 16), parentSpanId, name, kind: "internal",
    status, startTimeUnixNano,
    endTimeUnixNano: null, events: [], attributes,
    provenance: { provider: "codex", nativeSessionId: sessionId, sourceId: src.id,
      sourceOrdinal: ordinal, basis: "observed", sourceRef } };
}
export function addElapsedGaps(src: NativeSource, events: TraceEvent[]): void {
  const byCall = new Map<string, { requests: TraceEvent[]; results: TraceEvent[] }>();
  for (const event of events) {
    if (event.provenance.sourceId !== src.id) continue;
    if (event.name !== "function_call" && event.name !== "function_call_output") continue;
    const callId = event.attributes["coderails.native.call_id"];
    if (typeof callId !== "string") continue;
    const pair = byCall.get(callId) ?? { requests: [], results: [] };
    (event.name === "function_call" ? pair.requests : pair.results).push(event);
    byCall.set(callId, pair);
  }
  for (const pair of byCall.values()) {
    if (pair.requests.length !== 1 || pair.results.length !== 1) continue;
    const request = pair.requests[0], result = pair.results[0];
    if (request.startTimeUnixNano === null || result.startTimeUnixNano === null ||
      result.provenance.sourceOrdinal <= request.provenance.sourceOrdinal) continue;
    const gap = BigInt(result.startTimeUnixNano) - BigInt(request.startTimeUnixNano);
    if (gap < 0 || gap > BigInt(Number.MAX_SAFE_INTEGER) * BigInt(1000000)) continue;
    request.attributes["coderails.elapsed_gap_ms"] = Number(gap / BigInt(1000000));
    request.attributes["coderails.elapsed_gap.basis"] = "derived";
    request.attributes["coderails.elapsed_gap.method"] = "timestamp_difference";
    request.attributes["coderails.elapsed_gap.cause"] = "unknown";
    request.attributes["coderails.elapsed_gap.start_source_ref"] = request.provenance.sourceRef.recordId;
    request.attributes["coderails.elapsed_gap.end_source_ref"] = result.provenance.sourceRef.recordId;
  }
}
export function orderEvents(events: TraceEvent[]): void {
  // Array.sort is stable: source traversal order remains the tie break for equal or absent times.
  events.sort((left, right) => {
    if (left.startTimeUnixNano === null) return right.startTimeUnixNano === null ? 0 : 1;
    if (right.startTimeUnixNano === null) return -1;
    const a = BigInt(left.startTimeUnixNano), b = BigInt(right.startTimeUnixNano);
    return a < b ? -1 : a > b ? 1 : 0;
  });
}
