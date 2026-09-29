export const TRACE_SCHEMA_VERSION = 1 as const;

export type TraceProvider = "claude" | "codex";
export type EvidenceBasis = "source" | "observed" | "derived" | "unavailable";
export type TraceAttribute = string | number | boolean | null;

export interface SourceRef {
  kind: string;
  recordId: string;
  ordinal: number;
}

export interface TraceProvenance {
  provider: TraceProvider;
  nativeSessionId: string;
  sourceId: string;
  sourceOrdinal: number;
  basis: EvidenceBasis;
  sourceRef: SourceRef;
  derivation?: { method: string; sourceIds: string[] };
}

export interface TraceSpanEvent {
  name: string;
  timeUnixNano: string | null;
  attributes: Record<string, TraceAttribute>;
}

export interface TraceEvent {
  schemaVersion: typeof TRACE_SCHEMA_VERSION;
  eventId: string;
  traceId: string;
  spanId: string;
  parentSpanId: string | null;
  name: string;
  kind: "internal" | "client" | "server" | "producer" | "consumer";
  status: { value: "unset" | "ok" | "error" | "unavailable"; basis: EvidenceBasis; derivation?: { method: string; sourceIds: string[] } };
  startTimeUnixNano: string | null;
  endTimeUnixNano: string | null;
  events: TraceSpanEvent[];
  attributes: Record<string, TraceAttribute>;
  provenance: TraceProvenance;
}

export interface TraceManifest {
  schemaVersion: typeof TRACE_SCHEMA_VERSION;
  parserVersion: number;
  provider: TraceProvider;
  nativeSessionId: string;
  loopId: string | null;
  sources: Array<{ sourceId: string; fingerprint: string; cursor: string | null }>;
  generatedAt: string;
  complete: boolean;
  errors: string[];
  eventCount: number;
  eventFile: string;
}

export interface TracePage {
  events: TraceEvent[];
  inputCursor: string | null;
  nextCursor: string | null;
  complete: boolean;
  errors?: string[];
  scannedRecords?: number | null;
  emittedEvents?: number;
  truncated?: boolean;
}

export interface NativeSessionSummary {
  nativeSessionId: string;
  provider: TraceProvider;
  projectLabel: string;
  displayLabel: string;
  lastActivity: { value: string | null; basis: EvidenceBasis; derivation?: { method: string; sourceIds: string[] } };
}

export interface TraceCollectionDeps {
  sourceRoot: string;
  cacheRoot: string;
  graphRoot?: string;
  graphDiscoveryError?: string;
  auditPath?: string;
  now: () => Date;
  fs: {
    readFile: (path: string) => Promise<string>;
    writeFile: (path: string, content: string) => Promise<void>;
    stat: (path: string) => Promise<unknown>;
  };
}

export interface TraceDetail {
  sourceRef: SourceRef;
  provenance: TraceProvenance;
  content: string;
}

const eventKeys = ["schemaVersion", "eventId", "traceId", "spanId", "parentSpanId", "name", "kind", "status", "startTimeUnixNano", "endTimeUnixNano", "events", "attributes", "provenance"];
const provenanceKeys = ["provider", "nativeSessionId", "sourceId", "sourceOrdinal", "basis", "sourceRef", "derivation"];
const statusKeys = ["value", "basis", "derivation"];
const spanEventKeys = ["name", "timeUnixNano", "attributes"];
const sourceRefKeys = ["kind", "recordId", "ordinal"];
const derivationKeys = ["method", "sourceIds"];
const attributeKeys = new Set([
  "tool.name",
  "gen_ai.operation.name",
  "gen_ai.request.model",
  "gen_ai.response.model",
  "gen_ai.usage.input_tokens",
  "gen_ai.usage.output_tokens",
  "coderails.source.ordinal",
  "coderails.actor.kind",
  "coderails.actor.id",
  "coderails.loop.id",
  "coderails.graph.revision",
  "coderails.wave.id",
  "coderails.node.id",
  "coderails.attempt",
  "coderails.native.call_id",
  "coderails.child.id",
  "coderails.duration_ms",
  "coderails.duration.basis",
  "coderails.start_time.basis",
  "coderails.start_time.method",
  "coderails.start_time.source_refs",
  "coderails.end_time.basis",
  "coderails.end_time.method",
  "coderails.end_time.source_refs",
  "coderails.time.basis",
  "coderails.time.method",
  "coderails.time.source_refs",
  "coderails.elapsed_gap_ms",
  "coderails.elapsed_gap.basis",
  "coderails.elapsed_gap.method",
  "coderails.elapsed_gap.cause",
  "coderails.elapsed_gap.start_source_ref",
  "coderails.elapsed_gap.end_source_ref",
  "coderails.parent_join.basis",
  "coderails.parent_join.method",
  "coderails.parent_join.parent_source_ref",
  "coderails.parent_join.child_source_ref",
  "coderails.file.change_count",
  "coderails.evidence.kind",
  "coderails.evidence.id",
]);

export function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function onlyKeys(value: Record<string, unknown>, keys: string[]): boolean {
  return Object.keys(value).every((key) => keys.includes(key));
}

function nonempty(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function ordinal(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function basis(value: unknown): value is EvidenceBasis {
  return value === "source" || value === "observed" || value === "derived" || value === "unavailable";
}

function derivation(value: unknown): boolean {
  return record(value) && onlyKeys(value, derivationKeys) && nonempty(value.method) &&
    Array.isArray(value.sourceIds) && value.sourceIds.length > 0 && value.sourceIds.every(nonempty);
}

function hasBasis(value: Record<string, unknown>): boolean {
  return basis(value.basis) && (value.basis !== "derived" || derivation(value.derivation)) &&
    (value.derivation === undefined || derivation(value.derivation));
}

function time(value: unknown): boolean {
  return value === null || (typeof value === "string" && /^\d+$/.test(value));
}

function timeSourceRefs(value: unknown): boolean {
  if (typeof value !== "string") return false;
  try {
    const refs: unknown = JSON.parse(value);
    return Array.isArray(refs) && refs.length > 0 && refs.every(sourceRef);
  } catch { return false; }
}

function timeBasis(value: unknown, attrs: Record<string, unknown>, prefix: string): boolean {
  const state = attrs[`${prefix}.basis`];
  const method = attrs[`${prefix}.method`];
  const refs = attrs[`${prefix}.source_refs`];
  if (!time(value)) return false;
  if (value === null) return state === "unavailable" && method === undefined && refs === undefined;
  if (state === "source") return method === undefined && refs === undefined;
  return state === "derived" && nonempty(method) && timeSourceRefs(refs);
}

function attributes(value: unknown): boolean {
  return record(value) && Object.entries(value).every(([key, item]) =>
    attributeKeys.has(key) && (item === null || typeof item === "string" ||
      (typeof item === "number" && Number.isFinite(item)) || typeof item === "boolean"));
}

function sourceRef(value: unknown): boolean {
  return record(value) && onlyKeys(value, sourceRefKeys) && nonempty(value.kind) &&
    nonempty(value.recordId) && ordinal(value.ordinal);
}

function provenance(value: unknown): boolean {
  return record(value) && onlyKeys(value, provenanceKeys) &&
    (value.provider === "claude" || value.provider === "codex") &&
    nonempty(value.nativeSessionId) && nonempty(value.sourceId) &&
    ordinal(value.sourceOrdinal) && hasBasis(value) && sourceRef(value.sourceRef);
}

function status(value: unknown): boolean {
  return record(value) && onlyKeys(value, statusKeys) &&
    (value.value === "unset" || value.value === "ok" || value.value === "error" || value.value === "unavailable") &&
    hasBasis(value);
}

function spanEvent(value: unknown): boolean {
  return record(value) && onlyKeys(value, spanEventKeys) &&
    nonempty(value.name) && attributes(value.attributes) &&
    timeBasis(value.timeUnixNano, value.attributes as Record<string, unknown>, "coderails.time");
}

export function isTraceEvent(value: unknown): value is TraceEvent {
  return record(value) && onlyKeys(value, eventKeys) &&
    value.schemaVersion === TRACE_SCHEMA_VERSION &&
    nonempty(value.eventId) && nonempty(value.traceId) && nonempty(value.spanId) &&
    (value.parentSpanId === null || nonempty(value.parentSpanId)) &&
    nonempty(value.name) &&
    (value.kind === "internal" || value.kind === "client" || value.kind === "server" ||
      value.kind === "producer" || value.kind === "consumer") &&
    status(value.status) && attributes(value.attributes) &&
    timeBasis(value.startTimeUnixNano, value.attributes as Record<string, unknown>, "coderails.start_time") &&
    timeBasis(value.endTimeUnixNano, value.attributes as Record<string, unknown>, "coderails.end_time") &&
    Array.isArray(value.events) && value.events.every(spanEvent) &&
    provenance(value.provenance);
}

export function serializeTraceEvent(value: TraceEvent): string {
  if (!isTraceEvent(value)) throw new TypeError("Invalid trace event metadata");
  return JSON.stringify(value);
}
