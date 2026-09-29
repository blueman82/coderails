import { mkdir, readFile as nodeReadFile, readdir, rename, stat as nodeStat, unlink, writeFile as nodeWriteFile } from "node:fs/promises";
import { basename, join } from "node:path";
import { TRACE_SCHEMA_VERSION, serializeTraceEvent, type TraceAttribute, type TraceCollectionDeps, type TraceEvent, type TraceManifest } from "./traceSchema";
import { MAX_SOURCE_SCAN_BYTES, hash, nativeEvent, timeNano, type NativeSource } from "./codexTraceNative";

export async function graphSource(path: string, name: string, deps: TraceCollectionDeps): Promise<NativeSource> {
  const info = await deps.fs.stat(path) as { dev?: number; ino?: number; size?: number; mtimeMs?: number };
  if (typeof info.size === "number" && info.size > MAX_SOURCE_SCAN_BYTES)
    throw new Error(`source exceeds trace scan limit: graph/${name}`);
  const text = await deps.fs.readFile(path);
  return { path, id: `graph/${name}`, text, rows: [], ordinals: [], errors: [], cursor: "1",
    fingerprint: `sha256:${hash(text)};identity:${[info.dev, info.ino, info.size, info.mtimeMs].join(":")}` };
}
export async function auditSource(path: string, deps: TraceCollectionDeps): Promise<NativeSource> {
  const info = await deps.fs.stat(path) as { dev?: number; ino?: number; size?: number; mtimeMs?: number };
  if (typeof info.size === "number" && info.size > MAX_SOURCE_SCAN_BYTES)
    throw new Error("source exceeds trace scan limit: hook audit");
  const text = await deps.fs.readFile(path);
  if (Buffer.byteLength(text, "utf8") > MAX_SOURCE_SCAN_BYTES)
    throw new Error("source exceeds trace scan limit: hook audit");
  return { path, id: "audit/discipline.log", text, rows: [], ordinals: [], errors: [],
    fingerprint: `sha256:${hash(text)};identity:${[info.dev, info.ino, info.size, info.mtimeMs].join(":")}`,
    cursor: String(text.split("\n").filter(Boolean).length) };
}
export function auditEvents(sessionId: string, src: NativeSource): TraceEvent[] {
  const events: TraceEvent[] = [];
  for (const [index, line] of src.text.split("\n").entries()) {
    const tokens = line.split(/\s+/);
    if (!tokens.includes(`session=${sessionId}`)) continue;
    const hook = tokens.find((token) => /^hook=[a-z0-9_-]+$/.test(token))?.slice(5);
    if (!hook) continue;
    const ordinal = index + 1;
    const eventId = hash(`codex:${sessionId}:${src.id}:${ordinal}:hook_audit`);
    const flagged = tokens.some((token) => ["blocked=1", "denied=1", "decision=deny"].includes(token));
    const startTimeUnixNano = timeNano(tokens[0]);
    events.push({ schemaVersion: TRACE_SCHEMA_VERSION, eventId, traceId: hash(`codex:${sessionId}`).slice(0, 32),
      spanId: eventId.slice(0, 16), parentSpanId: null, name: "hook_audit", kind: "internal",
      status: flagged ? { value: "error", basis: "source" } : { value: "unavailable", basis: "unavailable" },
      startTimeUnixNano, endTimeUnixNano: null, events: [],
      attributes: { "coderails.source.ordinal": ordinal, "coderails.actor.kind": "orchestrator",
        "coderails.start_time.basis": startTimeUnixNano === null ? "unavailable" : "source",
        "coderails.end_time.basis": "unavailable", "coderails.duration_ms": null,
        "coderails.duration.basis": "unavailable",
        "coderails.evidence.kind": "hook_audit", "coderails.evidence.id": hook },
      provenance: { provider: "codex", nativeSessionId: sessionId, sourceId: src.id,
        sourceOrdinal: ordinal, basis: "observed",
        sourceRef: { kind: "codex_hook_audit_record", recordId: `audit:${ordinal}`, ordinal } } });
  }
  return events;
}
export function graphEvent(sessionId: string, src: NativeSource, ordinal: number, name: string, pointer: string,
  attributes: Record<string, TraceAttribute>): TraceEvent {
  const event = nativeEvent(sessionId, src, ordinal, { type: name }, "orchestrator", null, null, null);
  const eventId = hash(`codex:${sessionId}:${src.id}:${pointer}:${name}`);
  return { ...event, eventId, spanId: eventId.slice(0, 16),
    attributes: { ...attributes, "coderails.start_time.basis": "unavailable",
      "coderails.end_time.basis": "unavailable", "coderails.duration_ms": null,
      "coderails.duration.basis": "unavailable" },
    provenance: { ...event.provenance, sourceRef: { kind: "codex_graph_record",
      recordId: `${basename(src.path)}#${pointer}`, ordinal } } };
}
export function pointer(value: string): string { return value.replace(/~/g, "~0").replace(/\//g, "~1"); }
export async function saveCache(dir: string, manifest: TraceManifest, events: TraceEvent[], nativeParentAvailable: boolean): Promise<void> {
  await mkdir(dir, { recursive: true });
  const suffix = `.${process.pid}.${Math.random().toString(36).slice(2)}.tmp`;
  const serialized = events.map(serializeTraceEvent).join("\n") + (events.length ? "\n" : "");
  manifest.eventFile = `events.${hash(serialized)}.jsonl`;
  const eventTemp = join(dir, `${manifest.eventFile}${suffix}`), manifestTemp = join(dir, `manifest.json${suffix}`);
  await nodeWriteFile(eventTemp, serialized, "utf8");
  await nodeWriteFile(manifestTemp, JSON.stringify(manifest), "utf8");
  await rename(eventTemp, join(dir, manifest.eventFile));
  await rename(manifestTemp, join(dir, "manifest.json"));
  // Keep the current and one prior generation for readers already opening a page.
  const current = JSON.parse(await nodeReadFile(join(dir, "manifest.json"), "utf8")) as TraceManifest;
  const candidates = (await readdir(dir)).filter((name) => /^events\.[a-f0-9]{64}\.jsonl$/.test(name));
  const dated = (await Promise.all(candidates.map(async (name) => {
    try { return { name, mtime: (await nodeStat(join(dir, name))).mtimeMs }; } catch { return null; }
  }))).filter((item): item is { name: string; mtime: number } => item !== null);
  const retained = new Set([current.eventFile,
    ...(nativeParentAvailable ? dated.sort((a, b) => b.mtime - a.mtime).slice(0, 2).map((item) => item.name) : [])]);
  for (const name of candidates) if (!retained.has(name)) {
    try { await unlink(join(dir, name)); } catch { /* another writer may have retired it */ }
  }
}
export function cacheEventPath(dir: string, manifest: TraceManifest): string {
  if (!/^events\.[a-f0-9]{64}\.jsonl$/.test(manifest.eventFile)) throw new Error("Invalid cache event generation");
  return join(dir, manifest.eventFile);
}
