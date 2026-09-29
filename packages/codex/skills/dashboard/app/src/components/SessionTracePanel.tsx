"use client";

import { useEffect, useRef, useState } from "react";
import type { NativeSessionSummary, SourceRef, TraceEvent, TracePage } from "@/lib/collect/sessionTrace";

type SessionsResponse = { sessions: NativeSessionSummary[] };
type DetailResponse = { content: string };

function url(path: string, token: string, params: Record<string, string> = {}): string {
  const query = new URLSearchParams({ token, ...params });
  return `${path}?${query}`;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: "no-store" });
  if (response.status === 409) throw new StaleTraceCursorError();
  if (!response.ok) throw new Error(`Request failed (${response.status})`);
  return response.json() as Promise<T>;
}

class StaleTraceCursorError extends Error {}

function attribute(event: TraceEvent, key: string): string | null {
  const value = event.attributes[key];
  return value === undefined || value === null ? null : String(value);
}

function timeLabel(nanos: string | null): string {
  if (nanos === null) return "time unavailable; source order only";
  const milliseconds = Number(BigInt(nanos) / BigInt(1000000));
  return Number.isFinite(milliseconds) ? new Date(milliseconds).toISOString() : "time unavailable; source order only";
}

function basisLabel(basis: string, derivation?: { method: string; sourceIds: string[] }): string {
  return basis === "derived" && derivation
    ? `derived: ${derivation.method} from ${derivation.sourceIds.join(", ")}`
    : basis === "source" || basis === "observed" ? "observed in source" : "unavailable";
}

function timeBasisLabel(event: TraceEvent, prefix: "start_time" | "end_time"): string {
  const basis = attribute(event, `coderails.${prefix}.basis`);
  if (basis === "source") return `observed in source; ref: ${event.provenance.sourceRef.recordId}`;
  if (basis === "derived") {
    const method = attribute(event, `coderails.${prefix}.method`);
    const encoded = attribute(event, `coderails.${prefix}.source_refs`);
    if (method && encoded) {
      try {
        const refs = JSON.parse(encoded) as SourceRef[];
        return `derived: ${method} from ${refs.map((ref) => ref.recordId).join(", ")}`;
      } catch { /* Invalid metadata is shown as unavailable. */ }
    }
  }
  return "unavailable";
}

function EventRow({ event, token, nativeSessionId, parentName }: {
  event: TraceEvent; token: string; nativeSessionId: string; parentName: string | null;
}) {
  const [expanded, setExpanded] = useState(false);
  const [detail, setDetail] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const detailRequest = useRef(0);
  const source = event.provenance;
  const input = attribute(event, "gen_ai.usage.input_tokens");
  const output = attribute(event, "gen_ai.usage.output_tokens");
  const tool = attribute(event, "tool.name");
  const callId = attribute(event, "coderails.native.call_id");
  const duration = attribute(event, "coderails.duration_ms");
  const durationBasis = attribute(event, "coderails.duration.basis");
  const elapsedGap = attribute(event, "coderails.elapsed_gap_ms");
  const parentJoinBasis = attribute(event, "coderails.parent_join.basis");
  const parentJoinMethod = attribute(event, "coderails.parent_join.method");
  const parentJoinParentRef = attribute(event, "coderails.parent_join.parent_source_ref");
  const parentJoinChildRef = attribute(event, "coderails.parent_join.child_source_ref");
  const refs = ["coderails.loop.id", "coderails.wave.id", "coderails.node.id", "coderails.attempt",
    "coderails.evidence.kind", "coderails.evidence.id"].flatMap((key) => {
    const value = attribute(event, key);
    return value === null ? [] : [`${key.replace("coderails.", "")}: ${value}`];
  });

  async function toggle() {
    const request = ++detailRequest.current;
    if (expanded) { setExpanded(false); setDetail(null); return; }
    setExpanded(true);
    setLoading(true);
    setDetailError(null);
    try {
      const path = url(`/api/sessions/${encodeURIComponent(nativeSessionId)}/trace/detail`, token,
        { ref: JSON.stringify(source.sourceRef) });
      const result = await getJson<DetailResponse>(path);
      if (request === detailRequest.current) setDetail(result.content);
    } catch (error) {
      if (request === detailRequest.current)
        setDetailError(error instanceof Error ? error.message : "Source detail unavailable");
    } finally { if (request === detailRequest.current) setLoading(false); }
  }

  return <li style={{ borderTop: "1px solid #45515e", padding: "0.65rem 0" }}>
    <div><strong>{event.name}</strong> · {timeLabel(event.startTimeUnixNano)} · time basis: {timeBasisLabel(event, "start_time")}</div>
    <div>end time: {timeLabel(event.endTimeUnixNano)} ({timeBasisLabel(event, "end_time")})</div>
    <div>status: {event.status.value} ({basisLabel(event.status.basis, event.status.derivation)})</div>
    <div>record: {basisLabel(source.basis, source.derivation)} · {source.sourceId}#{source.sourceOrdinal}</div>
    <div>tool: {tool ?? "unavailable"} · native call: {callId ?? "unavailable"}</div>
    <div>duration: {duration === null ? "unavailable" : `${duration} ms`} ({durationBasis === "source" || durationBasis === "observed" ? "observed" :
      durationBasis === "derived" ? "derived" : "unavailable"})</div>
    <div>elapsed gap: {elapsedGap === null ? "unavailable" : `${elapsedGap} ms (derived from request/result timestamps; cause unknown)`}</div>
    {parentName && <div>parent: {parentName} ({event.parentSpanId}) · join {parentJoinBasis === "derived" ? "derived" : "unavailable"};
      method: {parentJoinMethod ?? "unavailable"}; parent source: {parentJoinParentRef ?? "unavailable"};
      child source: {parentJoinChildRef ?? "unavailable"}</div>}
    {event.parentSpanId && !parentName && <div>parent join unresolved: {event.parentSpanId}</div>}
    {refs.length > 0 && <div>{refs.join(" · ")}</div>}
    <div>{input === null && output === null ? "usage unavailable (no token counts in this event)" :
      `usage observed: input ${input ?? "unavailable"}, output ${output ?? "unavailable"} tokens`}</div>
    <div>cost unavailable (no per-event cost source)</div>
    <div>Source reference: {source.sourceRef.kind} {source.sourceRef.recordId}</div>
    <button type="button" onClick={toggle} aria-expanded={expanded} aria-label={`Source detail for ${event.name}`}>
      {expanded ? "Hide source detail" : "Show source detail"}
    </button>
    {expanded && <div>{loading ? "Loading source detail…" : detailError ? `Source detail unavailable: ${detailError}` :
      <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{detail}</pre>}</div>}
  </li>;
}

export function SessionTracePanel({ token, dashboardRunId }: { token: string; dashboardRunId?: string | null }) {
  const [sessions, setSessions] = useState<NativeSessionSummary[]>([]);
  const [selected, setSelected] = useState("");
  const [events, setEvents] = useState<TraceEvent[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [complete, setComplete] = useState(true);
  const [diagnostics, setDiagnostics] = useState<string[]>([]);
  const [stale, setStale] = useState(false);
  const [coverage, setCoverage] = useState<{ scannedRecords: number | null; emittedEvents: number | null; truncated: boolean } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const currentSession = useRef("");

  useEffect(() => {
    let active = true;
    getJson<SessionsResponse>(url("/api/sessions", token)).then((result) => {
      if (active) setSessions(result.sessions);
    }).catch((cause) => { if (active) setError(`Native sessions unavailable: ${String(cause)}`); });
    return () => { active = false; };
  }, [token]);

  async function loadPage(sessionId: string, cursor: string | null, replace: boolean) {
    setLoading(true);
    setError(null);
    try {
      const params: Record<string, string> = { limit: "50" };
      if (cursor !== null) params.cursor = cursor;
      const page = await getJson<TracePage>(url(`/api/sessions/${encodeURIComponent(sessionId)}/trace`, token, params));
      if (currentSession.current !== sessionId) return;
      setEvents((previous) => replace ? page.events : [...previous, ...page.events]);
      setNextCursor(page.nextCursor);
      setComplete(page.complete);
      setDiagnostics(page.errors ?? []);
      setStale(false);
      setCoverage({ scannedRecords: page.scannedRecords ?? null, emittedEvents: page.emittedEvents ?? null,
        truncated: page.truncated ?? false });
    } catch (cause) {
      if (currentSession.current !== sessionId) return;
      if (cause instanceof StaleTraceCursorError) {
        setEvents([]);
        setNextCursor(null);
        setCoverage(null);
        setComplete(false);
        setDiagnostics([]);
        setStale(true);
        setError("The trace changed while paging. Restart to load the current version.");
      } else setError(`Trace unavailable: ${String(cause)}`);
    }
    finally { if (currentSession.current === sessionId) setLoading(false); }
  }

  function choose(sessionId: string) {
    currentSession.current = sessionId;
    setSelected(sessionId);
    setEvents([]);
    setNextCursor(null);
    setComplete(true);
    setDiagnostics([]);
    setStale(false);
    setCoverage(null);
    if (sessionId) void loadPage(sessionId, null, true);
  }

  const selectedSession = sessions.find((session) => session.nativeSessionId === selected);
  const spans = new Map(events.map((event) => [event.spanId, event.name]));
  const lanes = new Map<string, TraceEvent[]>();
  for (const event of events) {
    const actor = attribute(event, "coderails.actor.kind") === "worker"
      ? `Worker ${attribute(event, "coderails.actor.id") ?? "unknown"}` : "Orchestrator and evidence";
    lanes.set(actor, [...(lanes.get(actor) ?? []), event]);
  }
  const ambiguity = events.some((event) => event.startTimeUnixNano === null) ||
    new Set(events.map((event) => event.startTimeUnixNano).filter((value) => value !== null)).size <
      events.filter((event) => event.startTimeUnixNano !== null).length;

  return <section aria-label="Native session trace" style={{ color: "#e9eef4", background: "#17212b", padding: "1rem", overflow: "auto", maxHeight: "75vh" }}>
    <h2>Native session trace</h2>
    {dashboardRunId && <p>Dashboard run: {dashboardRunId}. Select a native session separately.</p>}
    <label htmlFor="native-session">Native session</label>{" "}
    <select id="native-session" value={selected} onChange={(event) => choose(event.target.value)}>
      <option value="">Select a native session</option>
      {sessions.map((session) => <option key={session.nativeSessionId} value={session.nativeSessionId}>
        {session.displayLabel} ({session.provider}, {session.nativeSessionId})
      </option>)}
    </select>
    {selectedSession && <p>Project: unavailable. Last activity: {selectedSession.lastActivity.value ?? "unavailable"}
      {` (${basisLabel(selectedSession.lastActivity.basis, selectedSession.lastActivity.derivation)})`}</p>}
    {error && <p role="alert">{error}</p>}
    {stale && selected && <button type="button" disabled={loading} onClick={() => void loadPage(selected, null, true)}>Restart trace</button>}
    {selected && <>
      <p>Trace events show attempts and recorded statuses. External effects and completion require separate evidence.</p>
      <p>Hook audit records appear only when their source line names this native session; untagged lines remain unlinked.</p>
      {!complete && <p>Unresolved trace: source collection is incomplete or ambiguous.</p>}
      {diagnostics.map((diagnostic, index) => <p key={index}>Trace diagnostic: {diagnostic}</p>)}
      {coverage && <p>Indexed source records: {coverage.scannedRecords === null ? "unavailable" : `${coverage.scannedRecords} (derived from local source scan)`}. Emitted events: {coverage.emittedEvents === null ? "unavailable" : `${coverage.emittedEvents} (derived from local trace index; not a native event count)`}.
        {coverage.truncated && " Source scan stopped at the size limit; this trace is incomplete."}</p>}
      {ambiguity && <p>Time is missing or tied for some records; source order is a display tie break, not a causal order.</p>}
      {[...lanes].map(([actor, rows]) => <section key={actor} aria-label={actor} style={{ marginTop: "1rem" }}>
        <h3>{actor}</h3>
        <ol style={{ listStyle: "none", paddingLeft: actor.startsWith("Worker") ? "1rem" : 0 }}>
          {rows.map((event) => <EventRow key={event.eventId} event={event} token={token} nativeSessionId={selected}
            parentName={event.parentSpanId ? spans.get(event.parentSpanId) ?? null : null} />)}
        </ol>
      </section>)}
      {nextCursor && <button type="button" disabled={loading} onClick={() => void loadPage(selected, nextCursor, false)}>
        Load more trace events
      </button>}
      {loading && <p>Loading trace…</p>}
    </>}
  </section>;
}
