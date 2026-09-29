import { basename, join, resolve, sep } from "node:path";
import { TRACE_SCHEMA_VERSION, serializeTraceEvent, type NativeSessionSummary, type SourceRef, type TraceCollectionDeps, type TraceDetail, type TraceEvent, type TraceManifest, type TracePage } from "./traceSchema";
import { CODEX_PARSER_VERSION, MAX_SOURCE_SCAN_BYTES, TranscriptResolutionError, addElapsedGaps, cacheDir, dispatches, isSubagentTranscript, nativeEvent, obj, orderEvents, paths, payload, safeId, safeReadError, source, terminalTurn, transcript, validChild, type Dispatch, type NativeSource } from "./codexTraceNative";
import { auditEvents, auditSource, cacheEventPath, graphEvent, graphSource, pointer, saveCache } from "./codexTraceSupport";

function unavailableSummary(nativeSessionId: string, projectLabel = "unavailable"): NativeSessionSummary {
  const shortId = nativeSessionId.length > 12 ? nativeSessionId.slice(0, 8) : nativeSessionId;
  return { nativeSessionId, provider: "codex", projectLabel, displayLabel: `${projectLabel} · ${shortId}`,
    lastActivity: { value: null, basis: "unavailable" } };
}

function sessionSummary(nativeSessionId: string, text: string): NativeSessionSummary {
  let projectLabel = "unavailable";
  let latest: number | null = null;
  let first = true;
  for (const line of text.split("\n")) {
    if (!line.trim()) continue;
    let row: Record<string, unknown>;
    try {
      const parsed: unknown = JSON.parse(line);
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return unavailableSummary(nativeSessionId);
      row = parsed as Record<string, unknown>;
    } catch { return unavailableSummary(nativeSessionId); }
    if (first) {
      first = false;
      const meta = payload(row);
      if (row.type === "session_meta" && meta.id === nativeSessionId && typeof meta.cwd === "string") {
        const candidate = basename(meta.cwd);
        if (candidate && candidate !== "." && candidate !== "/") projectLabel = candidate;
      }
    }
    if (typeof row.timestamp !== "string") continue;
    const milliseconds = Date.parse(row.timestamp);
    if (Number.isFinite(milliseconds) && (latest === null || milliseconds > latest)) latest = milliseconds;
  }
  const shortId = nativeSessionId.length > 12 ? nativeSessionId.slice(0, 8) : nativeSessionId;
  return { nativeSessionId, provider: "codex", projectLabel, displayLabel: `${projectLabel} · ${shortId}`,
    lastActivity: latest === null ? { value: null, basis: "unavailable" } :
      { value: new Date(latest).toISOString(), basis: "observed" } };
}

export { TRACE_SCHEMA_VERSION, isTraceEvent, serializeTraceEvent } from "./traceSchema";
export type { TraceProvider, EvidenceBasis, TraceAttribute, SourceRef, TraceProvenance, TraceSpanEvent, TraceEvent, TraceManifest, TracePage, NativeSessionSummary, TraceCollectionDeps, TraceDetail } from "./traceSchema";

export async function listCodexSessions(deps: TraceCollectionDeps): Promise<NativeSessionSummary[]> {
  const sessions: NativeSessionSummary[] = [];
  for (const path of await paths(deps.sourceRoot)) {
    const name = basename(path);
    const dated = /^rollout-\d{4}-\d{2}-\d{2}T[^/]+-([0-9a-f-]{36})\.jsonl$/.exec(name);
    const id = dated?.[1] ?? (/^rollout-([A-Za-z0-9_-]+)\.jsonl$/.exec(name)?.[1]);
    if (!id || !safeId(id) || await isSubagentTranscript(path)) continue;
    let summary: NativeSessionSummary;
    try {
      const info = await deps.fs.stat(path) as { size?: number };
      if (typeof info.size === "number" && info.size > MAX_SOURCE_SCAN_BYTES) summary = unavailableSummary(id);
      else {
        const text = await deps.fs.readFile(path);
        summary = Buffer.byteLength(text, "utf8") > MAX_SOURCE_SCAN_BYTES ? unavailableSummary(id) : sessionSummary(id, text);
      }
    } catch { summary = unavailableSummary(id); }
    sessions.push(summary);
  }
  return sessions.sort((a, b) => a.nativeSessionId.localeCompare(b.nativeSessionId));
}
export async function collectCodexSessionTrace(sessionId: string, deps: TraceCollectionDeps): Promise<TraceManifest> {
  const errors: string[] = deps.graphDiscoveryError ? [deps.graphDiscoveryError] : [], sources: NativeSource[] = [], events: TraceEvent[] = [];
  let loopId: string | null = null;
  let nativeParentAvailable = false;
  let allowAudit = false;
  try {
    const parent = await transcript(sessionId, deps);
    nativeParentAvailable = true;
    sources.push(parent);
    errors.push(...parent.errors);
    if (parent.rows[0]?.type !== "session_meta" || payload(parent.rows[0]).id !== sessionId ||
      payload(parent.rows[0]).thread_source === "subagent") {
      throw new Error(`thread ${sessionId} transcript has foreign session metadata`);
    }
    allowAudit = true;
    const validated = new Map<string, NativeSource>();
    const visited = new Set([sessionId]);
    const allDispatch: Dispatch[] = [];
    async function include(src: NativeSource, parentId: string, parentPath: string, depth: number,
      actor: "orchestrator" | "worker", inherited: Dispatch | null, parentSpanId: string | null): Promise<void> {
      const dispatch = dispatches(src, errors, parentPath);
      allDispatch.push(...dispatch);
      const byOrdinal = new Map(dispatch.map((item) => [item.ordinal, item]));
      src.rows.forEach((row, index) => {
        const ordinal = src.ordinals[index];
        const event = nativeEvent(sessionId, src, ordinal, row, actor, actor === "worker" ? parentId : null,
          byOrdinal.get(ordinal) ?? inherited, parentSpanId);
        if (actor === "worker" && parentSpanId && inherited) {
          const parent = events.find((candidate) => candidate.spanId === parentSpanId);
          if (parent) {
            event.attributes["coderails.parent_join.basis"] = "derived";
            event.attributes["coderails.parent_join.method"] = "codex_dispatch_child_metadata";
            event.attributes["coderails.parent_join.parent_source_ref"] = parent.provenance.sourceRef.recordId;
            event.attributes["coderails.parent_join.child_source_ref"] = `${src.id}:${src.ordinals[0]}`;
          }
        }
        events.push(event);
      });
      addElapsedGaps(src, events);
      for (const item of dispatch) {
        if (visited.has(item.childId)) { errors.push(`duplicate child identity ${item.childId}`); continue; }
        visited.add(item.childId);
        try {
          const child = await transcript(item.childId, deps);
          sources.push(child);
          errors.push(...child.errors);
          if (!validChild(child, sessionId, parentId, depth + 1, item)) {
            errors.push(`foreign child metadata for ${item.childId}`); continue;
          }
          validated.set(item.childId, child);
          const spawnSpan = events.find((event) => event.provenance.sourceId === src.id && event.provenance.sourceOrdinal === item.ordinal)?.spanId ?? null;
          await include(child, item.childId, item.path ?? `${parentPath}/${item.task ?? item.childId}`, depth + 1, "worker", item, spawnSpan);
        } catch (error) { errors.push(`unreadable child ${item.childId}: ${safeReadError(error)}`); }
      }
    }
    await include(parent, sessionId, "/root", 0, "orchestrator", null, null);
    if (deps.graphRoot) {
      try {
        const src = await graphSource(join(deps.graphRoot, "progress.json"), "progress.json", deps);
        sources.push(src);
        const progress = obj(JSON.parse(src.text)), graph = obj(progress?.graph), nodes = obj(graph?.nodes);
        if (progress?.schema_version !== 3 || progress.session_id !== sessionId || typeof progress.loop_id !== "string" || !nodes)
          throw new Error("foreign or malformed graph progress");
        loopId = progress.loop_id;
        let ordinal = 0;
        for (const [nodeId, raw] of Object.entries(nodes)) {
          const node = obj(raw); if (!node) { errors.push(`malformed graph node ${nodeId}`); continue; }
          const path = `/graph/nodes/${pointer(nodeId)}`;
          events.push(graphEvent(sessionId, src, ++ordinal, "graph_node", path, { "coderails.node.id": nodeId }));
          const retry = obj(node.retry);
          if (typeof retry?.attempts === "number" && retry.attempts > 0)
            events.push(graphEvent(sessionId, src, ++ordinal, "graph_retry", `${path}/retry`, { "coderails.node.id": nodeId, "coderails.attempt": retry.attempts }));
          const refs = Array.isArray(node.evidence) ? node.evidence : [];
          refs.forEach((rawRef, index) => {
            const ref = obj(rawRef);
            if (ref?.kind !== "codex_agent") return;
            const attempt = ref.attempt;
            const suffix = Number.isSafeInteger(attempt) && Number(attempt) > 1 ? `_a${attempt}` : "";
            const nodeHex = Buffer.from(nodeId).toString("hex"), loopHex = Buffer.from(loopId ?? "").toString("hex");
            const currentTask = `loop_worker_${loopHex}_${nodeHex}${suffix}`;
            const legacyTask = `loop_worker_${nodeHex}${suffix}`;
            const matches = allDispatch.filter((item) => {
              const child = validated.get(item.childId);
              return item.callId === ref.spawn_call_id && item.childId === ref.agent_thread_id &&
                (item.task === currentTask || item.task === legacyTask) && child !== undefined &&
                terminalTurn(child) === ref.task_complete_turn_id;
            });
            if (matches.length !== 1) errors.push(`graph evidence has no validated native linkage: ${nodeId} item ${index}`);
            events.push(graphEvent(sessionId, src, ++ordinal, "graph_evidence", `${path}/evidence/${index}`,
              { "coderails.node.id": nodeId, "coderails.evidence.kind": "codex_agent",
                "coderails.native.call_id": typeof ref.spawn_call_id === "string" ? ref.spawn_call_id : null,
                "coderails.attempt": typeof ref.attempt === "number" ? ref.attempt : null }));
          });
        }
        if (obj(graph?.hard_stop)) events.push(graphEvent(sessionId, src, ++ordinal, "graph_hard_stop", "/graph/hard_stop", {}));
      } catch (error) { errors.push(`unreadable graph progress: ${safeReadError(error)}`); }
      for (const name of ["evals", "proof", "retro"] as const) {
        try {
          const src = await graphSource(join(deps.graphRoot, `${name}.json`), `${name}.json`, deps);
          if (!obj(JSON.parse(src.text))) throw new Error("artifact must be an object");
          sources.push(src);
          events.push(graphEvent(sessionId, src, 1, `${name}_reference`, "", { "coderails.evidence.kind": name, "coderails.evidence.id": `${name}.json` }));
        } catch (error) { if (!(error instanceof Error && "code" in error && error.code === "ENOENT")) errors.push(`unreadable ${name} artifact: ${safeReadError(error)}`); }
      }
    }
  } catch (error) {
    errors.push(safeReadError(error)); events.length = 0;
    allowAudit = error instanceof TranscriptResolutionError && error.candidateCount === 0;
  }
  if (deps.auditPath && allowAudit) {
    try {
      const audit = await auditSource(deps.auditPath, deps);
      sources.push(audit);
      events.push(...auditEvents(sessionId, audit));
    } catch (error) {
      if (!(error instanceof Error && "code" in error && error.code === "ENOENT"))
        errors.push(`unreadable hook audit: ${safeReadError(error)}`);
    }
  }
  orderEvents(events);
  const manifest: TraceManifest = { schemaVersion: TRACE_SCHEMA_VERSION, parserVersion: CODEX_PARSER_VERSION,
    provider: "codex", nativeSessionId: sessionId, loopId,
    sources: sources.map((src) => ({ sourceId: src.id, fingerprint: src.fingerprint, cursor: src.cursor })),
    generatedAt: deps.now().toISOString(), complete: errors.length === 0, errors, eventCount: events.length, eventFile: "" };
  const dir = cacheDir(sessionId, deps);
  try {
    const previous = JSON.parse(await deps.fs.readFile(join(dir, "manifest.json"))) as TraceManifest;
    const indexed = await deps.fs.readFile(cacheEventPath(dir, previous));
    if (previous.schemaVersion === TRACE_SCHEMA_VERSION && previous.parserVersion === CODEX_PARSER_VERSION &&
      previous.nativeSessionId === sessionId && JSON.stringify(previous.sources) === JSON.stringify(manifest.sources) &&
      JSON.stringify(previous.errors) === JSON.stringify(manifest.errors) &&
      indexed === events.map(serializeTraceEvent).join("\n") + (events.length ? "\n" : ""))
      return previous;
  } catch { /* absent or damaged derived cache is rebuilt */ }
  await saveCache(dir, manifest, events, nativeParentAvailable);
  return manifest;
}
export async function readCodexTracePage(sessionId: string, cursor: string | null, limit: number,
  deps: TraceCollectionDeps): Promise<TracePage> {
  const parsed = cursor === null ? null : /^g:([a-f0-9]{64}):([0-9]+)$/.exec(cursor);
  const index = parsed ? Number(parsed[2]) : 0;
  if ((cursor !== null && !parsed) || !Number.isSafeInteger(index) ||
    !Number.isSafeInteger(limit) || limit < 1 || limit > 1000)
    throw new TypeError("Invalid trace page cursor or limit");
  let manifest = await collectCodexSessionTrace(sessionId, deps);
  let generation = /^events\.([a-f0-9]{64})\.jsonl$/.exec(manifest.eventFile)?.[1];
  if (parsed && parsed[1] !== generation) throw new Error("Stale trace page cursor; restart pagination");
  let indexed: string;
  try { indexed = await deps.fs.readFile(cacheEventPath(cacheDir(sessionId, deps), manifest)); }
  catch {
    // A concurrent rebuild may retire a generation between manifest and event reads.
    manifest = await collectCodexSessionTrace(sessionId, deps);
    generation = /^events\.([a-f0-9]{64})\.jsonl$/.exec(manifest.eventFile)?.[1];
    if (parsed && parsed[1] !== generation) throw new Error("Stale trace page cursor; restart pagination");
    indexed = await deps.fs.readFile(cacheEventPath(cacheDir(sessionId, deps), manifest));
  }
  const rows = indexed.split("\n").filter(Boolean);
  const events = rows.slice(index, index + limit).map((line) => JSON.parse(line) as TraceEvent);
  return { events, inputCursor: cursor, nextCursor: index + limit < rows.length ? `g:${generation}:${index + limit}` : null,
    complete: manifest.complete, errors: manifest.errors, scannedRecords: manifest.sources.length ?
      manifest.sources.reduce((total, item) => total + Number(item.cursor ?? 0), 0) : null,
    emittedEvents: manifest.eventCount, truncated: manifest.errors.some((error) => error.includes("trace scan limit")) };
}
export async function readCodexTraceDetail(sessionId: string, sourceRef: SourceRef,
  deps: TraceCollectionDeps): Promise<TraceDetail> {
  const manifest = await collectCodexSessionTrace(sessionId, deps);
  const cached = (await deps.fs.readFile(cacheEventPath(cacheDir(sessionId, deps), manifest))).split("\n").filter(Boolean);
  const event = cached.map((line) => JSON.parse(line) as TraceEvent).find((value) =>
    value.provenance.sourceRef.kind === sourceRef.kind && value.provenance.sourceRef.recordId === sourceRef.recordId &&
    value.provenance.sourceRef.ordinal === sourceRef.ordinal);
  if (!event) throw new Error("Source reference is unavailable in this trace");
  if (sourceRef.kind === "codex_hook_audit_record") {
    if (!deps.auditPath || sourceRef.recordId !== `audit:${sourceRef.ordinal}`) throw new Error("Invalid audit source reference");
    const audit = await auditSource(deps.auditPath, deps);
    if (manifest.sources.find((item) => item.sourceId === audit.id)?.fingerprint !== audit.fingerprint)
      throw new Error("Audit source changed during detail request");
    const content = audit.text.split("\n")[sourceRef.ordinal - 1];
    if (!content?.split(/\s+/).includes(`session=${sessionId}`)) throw new Error("Audit source record is unavailable");
    return { sourceRef, provenance: event.provenance, content };
  }
  if (sourceRef.kind === "codex_graph_record") {
    if (!deps.graphRoot) throw new Error("Graph source is unavailable");
    const [name, pointer] = sourceRef.recordId.split("#", 2);
    if (!["progress.json", "evals.json", "proof.json", "retro.json"].includes(name) || pointer === undefined)
      throw new Error("Invalid graph source reference");
    const graph = await graphSource(join(deps.graphRoot, name), name, deps);
    if (manifest.sources.find((item) => item.sourceId === graph.id)?.fingerprint !== graph.fingerprint)
      throw new Error("Graph source changed during detail request");
    let value: unknown = JSON.parse(graph.text);
    for (const part of pointer.split("/").slice(1)) {
      const key = part.replace(/~1/g, "/").replace(/~0/g, "~");
      value = Array.isArray(value) ? value[Number(key)] : obj(value)?.[key];
      if (value === undefined) throw new Error("Graph source record is unavailable");
    }
    return { sourceRef, provenance: event.provenance, content: JSON.stringify(value) };
  }
  const path = resolve(deps.sourceRoot, event.provenance.sourceId);
  if (!path.startsWith(resolve(deps.sourceRoot) + sep)) throw new Error("Invalid source path");
  const native = await source(path, deps);
  if (manifest.sources.find((item) => item.sourceId === native.id)?.fingerprint !== native.fingerprint)
    throw new Error("Native source changed during detail request");
  const content = native.text.split("\n")[sourceRef.ordinal - 1];
  if (!content) throw new Error("Source record is unavailable");
  return { sourceRef, provenance: event.provenance, content };
}
