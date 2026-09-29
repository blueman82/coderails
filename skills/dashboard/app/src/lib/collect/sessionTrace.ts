import { basename, dirname, join, resolve, sep } from "node:path";
import { readdir } from "node:fs/promises";
import { TRACE_SCHEMA_VERSION, serializeTraceEvent, nonempty, type SourceRef, type TraceCollectionDeps, type TraceDetail, type TraceEvent, type TraceManifest, type TracePage, type NativeSessionSummary } from "./sessionTraceSchema";
import { CLAUDE_PARSER_VERSION, safeReadError, type NativeRecord, type Source, obj, safeSession, cacheDir, parentPath, source, artifactSource, auditSource, auditEvents, toolBlocks, dispatch, makeEvent, childValid, graphEvent, pointerPart, completedNotification, terminalChild, saveCache, clearCache, cacheEventPath } from "./sessionTraceClaudeHelpers";
export * from "./sessionTraceSchema";

export async function listClaudeSessions(deps: TraceCollectionDeps): Promise<NativeSessionSummary[]> {
  const projects = await readdir(deps.sourceRoot, { withFileTypes: true });
  const sessions: NativeSessionSummary[] = [];
  for (const project of projects) {
    if (!project.isDirectory()) continue;
    const dir = join(deps.sourceRoot, project.name);
    for (const entry of await readdir(dir, { withFileTypes: true })) {
      if (!entry.isFile() || !entry.name.endsWith(".jsonl")) continue;
      const nativeSessionId = basename(entry.name, ".jsonl");
      if (!safeSession(nativeSessionId)) continue;
      sessions.push({ nativeSessionId, provider: "claude", projectLabel: project.name,
        displayLabel: nativeSessionId,
        lastActivity: { value: null, basis: "unavailable" } });
    }
  }
  return sessions.sort((a, b) => a.nativeSessionId.localeCompare(b.nativeSessionId));
}

export async function collectClaudeSessionTrace(sessionId: string, deps: TraceCollectionDeps): Promise<TraceManifest> {
  let path: string;
  try { path = await parentPath(sessionId, deps); }
  catch (error) {
    if (safeSession(sessionId)) await clearCache(cacheDir(sessionId, deps));
    throw error;
  }
  const errors: string[] = deps.graphDiscoveryError ? [deps.graphDiscoveryError] : [];
  const sources: Source[] = [];
  const events: TraceEvent[] = [];
  let loopId: string | null = null;
  try {
    const parent = await source(path, deps);
    sources.push(parent);
    const uses = new Map<string, { row: NativeRecord; block: NativeRecord; ownership: NativeRecord; ordinal: number }>();
    const duplicateCalls = new Set<string>();
    const results = new Map<string, NativeRecord[]>();
    const agents = new Set<string>();
    const validatedAgents = new Set<string>();
    const childSources = new Map<string, Source>();
    const scan = async (native: Source, actor: "orchestrator" | "worker", childId: string | null,
      parentSpanId: string | null, ownership: NativeRecord | null,
      parentSourceRef: SourceRef | null = null): Promise<void> => {
      const localUses = new Map<string, { prompt: string; role: string; owner: NativeRecord | null;
        spanId: string; sourceRef: SourceRef }>();
      const toolRequests = new Map<string, TraceEvent[]>();
      const toolResults = new Map<string, TraceEvent[]>();
      const localResults = new Map<string, NativeRecord[]>();
      const localDuplicates = new Set<string>();
      for (const [index, row] of native.rows.entries()) {
        if (row.sessionId !== undefined && row.sessionId !== sessionId) {
          errors.push(`foreign session identity at ${native.id}:${native.ordinals[index]}`);
          continue;
        }
        if (actor === "orchestrator" && row.isSidechain === true) continue;
        const ordinal = native.ordinals[index];
        const items = toolBlocks(row);
        for (const { block, item } of items) {
          const owner = dispatch(block, sessionId);
          if (block.type === "tool_use" && block.name === "Agent") {
            const input = obj(block.input);
            if (nonempty(block.id) && typeof input?.prompt === "string" && nonempty(input.subagent_type)) {
              if (localUses.has(block.id)) { errors.push(`ambiguous duplicate Agent call: ${block.id}`); localDuplicates.add(block.id); }
              else {
                const event = makeEvent(sessionId, native, ordinal, row, actor, childId, parentSpanId,
                  owner ?? ownership, block, item, parentSourceRef);
                localUses.set(block.id, { prompt: input.prompt, role: input.subagent_type, owner,
                  spanId: event.spanId, sourceRef: event.provenance.sourceRef });
                if (owner && actor === "orchestrator") {
                  loopId ??= String(owner.loop_id);
                  uses.set(block.id, { row, block, ownership: owner, ordinal });
                }
              }
            } else errors.push(`unresolved Agent call at ${native.id}:${ordinal}`);
            if (!owner && typeof input?.prompt === "string" && input.prompt.startsWith("CODERAILS_GRAPH_DISPATCH="))
              errors.push(`invalid graph dispatch at ${native.id}:${ordinal}`);
          }
          if (row.type === "user" && block.type === "tool_result" && typeof block.tool_use_id === "string") {
            const value = obj(row.toolUseResult);
            if (value || block.is_error === true) {
              const result = value ?? { is_error: true };
              localResults.set(block.tool_use_id, [...(localResults.get(block.tool_use_id) ?? []), result]);
              if (actor === "orchestrator") results.set(block.tool_use_id,
                [...(results.get(block.tool_use_id) ?? []), result]);
            }
          }
        }
        if (items.length) for (const { block, item } of items) {
          const event = makeEvent(sessionId, native, ordinal, row, actor, childId, parentSpanId,
            dispatch(block, sessionId) ?? ownership, block, item, parentSourceRef);
          events.push(event);
          const callId = event.attributes["coderails.native.call_id"];
          if (typeof callId === "string") {
            const target = block.type === "tool_use" ? toolRequests : toolResults;
            target.set(callId, [...(target.get(callId) ?? []), event]);
          }
        } else events.push(makeEvent(sessionId, native, ordinal, row, actor, childId,
          parentSpanId, ownership, null, -1, parentSourceRef));
      }
      for (const [callId, matching] of toolResults) {
        const requests = toolRequests.get(callId) ?? [];
        if (requests.length !== 1 || matching.length !== 1) continue;
        const request = requests[0];
        const result = matching[0];
        if (request.startTimeUnixNano === null || result.startTimeUnixNano === null) continue;
        const gap = BigInt(result.startTimeUnixNano) - BigInt(request.startTimeUnixNano);
        if (gap < 0 || gap % BigInt(1000000) !== BigInt(0)) continue;
        const milliseconds = Number(gap / BigInt(1000000));
        if (!Number.isSafeInteger(milliseconds)) continue;
        result.attributes["coderails.elapsed_gap_ms"] = milliseconds;
        result.attributes["coderails.elapsed_gap.basis"] = "derived";
        result.attributes["coderails.elapsed_gap.method"] = "timestamp_difference";
        result.attributes["coderails.elapsed_gap.cause"] = "unknown";
        result.attributes["coderails.elapsed_gap.start_source_ref"] = JSON.stringify(request.provenance.sourceRef);
        result.attributes["coderails.elapsed_gap.end_source_ref"] = JSON.stringify(result.provenance.sourceRef);
      }
      const claims = new Map<string, number>();
      for (const [callId] of localUses) {
        const values = localResults.get(callId) ?? [];
        if (values.length === 1 && typeof values[0].agentId === "string")
          claims.set(values[0].agentId, (claims.get(values[0].agentId) ?? 0) + 1);
      }
      for (const [callId, use] of localUses) {
        if (localDuplicates.has(callId)) { duplicateCalls.add(callId); continue; }
        const values = localResults.get(callId) ?? [];
        const agentId = values.length === 1 ? values[0].agentId : undefined;
        if (typeof agentId !== "string" || !/^[A-Za-z0-9_-]+$/.test(agentId)) {
          errors.push(`unresolved child for Agent call ${callId}`); continue;
        }
        if (claims.get(agentId) !== 1 || agents.has(agentId)) {
          errors.push(`ambiguous child identity ${agentId}`); continue;
        }
        agents.add(agentId);
        try {
          const child = await source(join(dirname(path), sessionId, "subagents", `agent-${agentId}.jsonl`), deps);
          sources.push(child);
          if (!childValid(child, sessionId, agentId, use.prompt, use.role)) {
            errors.push(`foreign child identity or prompt for ${agentId}`); continue;
          }
          validatedAgents.add(agentId);
          childSources.set(agentId, child);
          await scan(child, "worker", agentId, use.spanId, use.owner ?? ownership, use.sourceRef);
        } catch (error) { errors.push(`unreadable or malformed child ${agentId}: ${safeReadError(error)}`); }
      }
    };
    await scan(parent, "orchestrator", null, null, null);
    if (deps.graphRoot) {
      const path = join(deps.graphRoot, "progress.json");
      try {
        const graphSource = await artifactSource(path, "progress.json", deps);
        sources.push(graphSource);
        const progress = obj(JSON.parse(graphSource.text));
        const graph = obj(progress?.graph);
        const nodes = obj(graph?.nodes);
        if (progress?.schema_version !== 3 || progress.session_id !== sessionId ||
          !nonempty(progress.loop_id) || !nodes) throw new Error("foreign or malformed graph progress");
        if (loopId && progress.loop_id !== loopId) errors.push("graph loop identity differs from native dispatch");
        loopId ??= String(progress.loop_id);
        let ordinal = 0;
        for (const [nodeId, value] of Object.entries(nodes)) {
          const node = obj(value);
          if (!node) { errors.push(`malformed graph node ${nodeId}`); continue; }
          const pointer = `/graph/nodes/${pointerPart(nodeId)}`;
          events.push(graphEvent(sessionId, graphSource, ++ordinal, "graph_node", pointer,
            { "coderails.node.id": nodeId }));
          const retry = obj(node.retry);
          if (typeof retry?.attempts === "number" && retry.attempts > 0)
            events.push(graphEvent(sessionId, graphSource, ++ordinal, "graph_retry", `${pointer}/retry`,
              { "coderails.node.id": nodeId, "coderails.attempt": retry.attempts }));
          const respawn = obj(node.respawn);
          if (typeof respawn?.generation === "number" && respawn.generation > 0)
            events.push(graphEvent(sessionId, graphSource, ++ordinal, "graph_respawn", `${pointer}/respawn`,
              { "coderails.node.id": nodeId, "coderails.attempt": respawn.generation }));
          if (!Array.isArray(node.evidence)) continue;
          for (const [index, raw] of node.evidence.entries()) {
            const ref = obj(raw);
            if (ref?.kind !== "claude_agent") continue;
            const native = typeof ref.tool_use_id === "string" ? uses.get(ref.tool_use_id) : undefined;
            const valid = native && !duplicateCalls.has(String(ref.tool_use_id)) &&
              native.row.uuid === ref.record_uuid && native.ownership.role === ref.subagent_type &&
              native.ownership.node_id === nodeId && native.ownership.wave_id === ref.wave_id &&
              native.ownership.loop_id === progress.loop_id &&
              (ref.agent_id === undefined || (typeof ref.agent_id === "string" && validatedAgents.has(ref.agent_id) &&
                (results.get(String(ref.tool_use_id)) ?? []).some((result) => result.agentId === ref.agent_id)));
            const history = obj(graph?.wave_history);
            const wave = history && typeof ref.wave_id === "string" ? obj(history[ref.wave_id]) : null;
            const waveValid = !history || (wave && typeof wave.cursor === "number" &&
              native !== undefined && native.ordinal > wave.cursor &&
              Array.isArray(wave.nodes) && wave.nodes.includes(nodeId) &&
              (wave.revision === undefined || wave.revision === native.ownership.revision));
            if (!valid || !waveValid) errors.push(`graph evidence has no validated native linkage: ${nodeId} item ${index}`);
            if (valid && ref.outcome === "done" &&
              !(typeof ref.agent_id === "string" && childSources.has(ref.agent_id) &&
                terminalChild(childSources.get(ref.agent_id)!, String(ref.subagent_type)) &&
                completedNotification(parent, String(ref.tool_use_id), ref.agent_id)))
              errors.push(`graph evidence lacks native completion notification or terminal child: ${nodeId} item ${index}`);
            events.push(graphEvent(sessionId, graphSource, ++ordinal, "graph_evidence",
              `${pointer}/evidence/${index}`, { "coderails.node.id": nodeId,
                "coderails.evidence.kind": "claude_agent",
                "coderails.native.call_id": typeof ref.tool_use_id === "string" ? ref.tool_use_id : null,
                "coderails.attempt": typeof ref.attempt === "number" ? ref.attempt : null }));
          }
        }
        if (obj(graph?.hard_stop)) {
          const stop = obj(graph?.hard_stop);
          events.push(graphEvent(sessionId, graphSource, ++ordinal, "graph_hard_stop", "/graph/hard_stop",
            { "coderails.node.id": typeof stop?.node === "string" ? stop.node : null }));
        }
      } catch (error) { errors.push(`unreadable graph progress: ${safeReadError(error)}`); }
      for (const name of ["evals", "proof", "retro"] as const) {
        try {
          const src = await artifactSource(join(deps.graphRoot, `${name}.json`), `${name}.json`, deps);
          const parsed = obj(JSON.parse(src.text));
          if (!parsed) throw new Error("artifact must be an object");
          sources.push(src);
          events.push(graphEvent(sessionId, src, 1, `${name}_reference`, "",
            { "coderails.evidence.kind": name, "coderails.evidence.id": `${name}.json` }));
        } catch (error) {
          if (!(error instanceof Error && "code" in error && error.code === "ENOENT"))
            errors.push(`unreadable ${name} artifact: ${safeReadError(error)}`);
        }
      }
    }
  } catch (error) {
    errors.push(safeReadError(error));
    events.length = 0;
  }
  if (deps.auditPath) {
    try {
      const audit = await auditSource(deps.auditPath, deps);
      sources.push(audit);
      events.push(...auditEvents(sessionId, audit));
    } catch (error) {
      if (!(error instanceof Error && "code" in error && error.code === "ENOENT"))
        errors.push(`unreadable hook audit: ${safeReadError(error)}`);
    }
  }
  events.sort((left, right) => {
    if (left.startTimeUnixNano !== null && right.startTimeUnixNano !== null) {
      const difference = BigInt(left.startTimeUnixNano) - BigInt(right.startTimeUnixNano);
      if (difference !== BigInt(0)) return difference < 0 ? -1 : 1;
    } else if (left.startTimeUnixNano !== right.startTimeUnixNano)
      return left.startTimeUnixNano === null ? 1 : -1;
    return left.provenance.sourceId.localeCompare(right.provenance.sourceId) ||
      left.provenance.sourceOrdinal - right.provenance.sourceOrdinal ||
      (Number(left.attributes["coderails.source.item"] ?? -1) - Number(right.attributes["coderails.source.item"] ?? -1));
  });
  const manifest: TraceManifest = {
    schemaVersion: TRACE_SCHEMA_VERSION, parserVersion: CLAUDE_PARSER_VERSION,
    provider: "claude", nativeSessionId: sessionId, loopId,
    sources: sources.map((item) => ({ sourceId: item.id, fingerprint: item.fingerprint, cursor: item.cursor })),
    generatedAt: deps.now().toISOString(), complete: errors.length === 0, errors, eventCount: events.length, eventFile: "",
  };
  const dir = cacheDir(sessionId, deps);
  try {
    const previous = JSON.parse(await deps.fs.readFile(join(dir, "manifest.json"))) as TraceManifest;
    const indexed = await deps.fs.readFile(cacheEventPath(dir, previous));
    if (previous.schemaVersion === TRACE_SCHEMA_VERSION &&
      previous.parserVersion === CLAUDE_PARSER_VERSION &&
      previous.nativeSessionId === sessionId &&
      JSON.stringify(previous.sources) === JSON.stringify(manifest.sources) &&
      JSON.stringify(previous.errors) === JSON.stringify(manifest.errors) &&
      indexed === events.map(serializeTraceEvent).join("\n") + (events.length ? "\n" : "")) return previous;
  } catch { /* absent or damaged derived index is rebuilt */ }
  await saveCache(dir, manifest, events);
  return manifest;
}

export async function readClaudeTracePage(sessionId: string, cursor: string | null, limit: number,
  deps: TraceCollectionDeps): Promise<TracePage> {
  if (!Number.isSafeInteger(limit) || limit < 1 || limit > 1000)
    throw new TypeError("Invalid trace page cursor or limit");
  const parsed = cursor === null ? null : /^g:([a-f0-9]{64}):(0|[1-9]\d*)$/.exec(cursor);
  if (cursor !== null && !parsed) throw new TypeError("Invalid trace page cursor or limit");
  const index = parsed ? Number(parsed[2]) : 0;
  if (!Number.isSafeInteger(index)) throw new TypeError("Invalid trace page cursor or limit");
  let manifest = await collectClaudeSessionTrace(sessionId, deps);
  let generation = /^events\.([a-f0-9]{64})\.jsonl$/.exec(manifest.eventFile)?.[1];
  if (!generation) throw new Error("Invalid cache event generation");
  if (parsed && parsed[1] !== generation) throw new Error("Stale trace generation cursor");
  let raw: string;
  try { raw = await deps.fs.readFile(cacheEventPath(cacheDir(sessionId, deps), manifest)); }
  catch {
    manifest = await collectClaudeSessionTrace(sessionId, deps);
    generation = /^events\.([a-f0-9]{64})\.jsonl$/.exec(manifest.eventFile)?.[1];
    if (parsed && parsed[1] !== generation) throw new Error("Stale trace generation cursor");
    raw = await deps.fs.readFile(cacheEventPath(cacheDir(sessionId, deps), manifest));
  }
  const rows = raw.split("\n").filter(Boolean);
  const events = rows.slice(index, index + limit).map((line) => JSON.parse(line) as TraceEvent);
  return { events, inputCursor: cursor, nextCursor: index + limit < rows.length ? `g:${generation}:${index + limit}` : null,
    complete: manifest.complete, errors: manifest.errors, scannedRecords: manifest.sources.length ?
      manifest.sources.reduce((total, item) => total + Number(item.cursor ?? 0), 0) : null,
    emittedEvents: manifest.eventCount, truncated: manifest.errors.some((error) => error.includes("trace scan limit")) };
}

export async function readClaudeTraceDetail(sessionId: string, sourceRef: SourceRef,
  deps: TraceCollectionDeps): Promise<TraceDetail> {
  const manifest = await collectClaudeSessionTrace(sessionId, deps);
  const raw = await deps.fs.readFile(cacheEventPath(cacheDir(sessionId, deps), manifest));
  const event = raw.split("\n").filter(Boolean).map((line) => JSON.parse(line) as TraceEvent)
    .find((item) => item.provenance.sourceRef.kind === sourceRef.kind &&
      item.provenance.sourceRef.recordId === sourceRef.recordId &&
      item.provenance.sourceRef.ordinal === sourceRef.ordinal);
  if (!event) throw new Error("Source reference is unavailable in this trace");
  if (sourceRef.kind === "claude_hook_audit_record") {
    if (!deps.auditPath || sourceRef.recordId !== `audit:${sourceRef.ordinal}`) throw new Error("Invalid audit source reference");
    const audit = await auditSource(deps.auditPath, deps);
    if (manifest.sources.find((item) => item.sourceId === audit.id)?.fingerprint !== audit.fingerprint)
      throw new Error("Audit source changed during detail request");
    const content = audit.text.split("\n")[sourceRef.ordinal - 1];
    if (!content?.split(/\s+/).includes(`session=${sessionId}`)) throw new Error("Audit source record is unavailable");
    return { sourceRef, provenance: event.provenance, content };
  }
  if (sourceRef.kind === "claude_graph_record") {
    if (!deps.graphRoot) throw new Error("Graph source is unavailable");
    const [name, pointer] = sourceRef.recordId.split("#", 2);
    if (!["progress.json", "evals.json", "proof.json", "retro.json"].includes(name) || pointer === undefined)
      throw new Error("Invalid graph source reference");
    const graph = await artifactSource(join(deps.graphRoot, name), name, deps);
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
  const lines = native.text.split("\n");
  const content = lines[sourceRef.ordinal - 1];
  if (!content) throw new Error("Source record is unavailable");
  return { sourceRef, provenance: event.provenance, content };
}
