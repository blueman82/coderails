import { describe, expect, it } from "vitest";
import {
  TRACE_SCHEMA_VERSION, isTraceEvent, serializeTraceEvent,
  type NativeSessionSummary, type SourceRef, type TraceCollectionDeps, type TraceDetail,
  type TraceEvent, type TraceManifest, type TracePage,
} from "../src/lib/collect/sessionTrace";

const sourceRef: SourceRef = { kind: "transcript_record", recordId: "record-7", ordinal: 7 };
const event: TraceEvent = {
  schemaVersion: 1, eventId: "event-7", traceId: "trace-1", spanId: "span-7",
  parentSpanId: null, name: "tool call", kind: "internal",
  status: { value: "unavailable", basis: "unavailable" },
  startTimeUnixNano: null, endTimeUnixNano: null,
  events: [{ name: "recorded", timeUnixNano: null, attributes: { "coderails.time.basis": "unavailable", "coderails.source.ordinal": 7 } }],
  attributes: { "tool.name": "Read", "gen_ai.usage.input_tokens": 12,
    "coderails.start_time.basis": "unavailable", "coderails.end_time.basis": "unavailable" },
  provenance: { provider: "codex", nativeSessionId: "native-1", sourceId: "parent", sourceOrdinal: 7, basis: "observed", sourceRef },
};

describe("session trace contract", () => {
  it("has versioned metadata with nullable time and explicit provenance", () => {
    expect(TRACE_SCHEMA_VERSION).toBe(1);
    expect(isTraceEvent(event)).toBe(true);
    expect(JSON.parse(serializeTraceEvent(event))).toMatchObject({
      schemaVersion: 1, startTimeUnixNano: null, endTimeUnixNano: null,
      provenance: { nativeSessionId: "native-1", sourceOrdinal: 7, sourceRef },
    });
  });

  it("rejects raw content and non-primitive attributes before JSONL serialization", () => {
    expect(isTraceEvent({ ...event, prompt: "secret" })).toBe(false);
    expect(isTraceEvent({ ...event, attributes: { "tool.name": "Read", "tool.arguments": "secret" } })).toBe(false);
    expect(isTraceEvent({ ...event, attributes: { "tool.name": { raw: "secret" } } })).toBe(false);
    expect(isTraceEvent({ ...event, events: [{ ...event.events[0], resultBody: "secret" }] })).toBe(false);
    expect(() => serializeTraceEvent({ ...event, resultBody: "secret" } as TraceEvent)).toThrow();
  });

  it("accepts decimal nanosecond timing and rejects invented time", () => {
    expect(isTraceEvent({ ...event, startTimeUnixNano: "1727524800000000000",
      attributes: { ...event.attributes, "coderails.start_time.basis": "source" } })).toBe(true);
    expect(isTraceEvent({ ...event, startTimeUnixNano: "unknown" })).toBe(false);
  });

  it("requires an independent, consistent basis for each timestamp", () => {
    expect(isTraceEvent(event)).toBe(true);
    expect(isTraceEvent({ ...event, attributes: { "coderails.end_time.basis": "unavailable" } })).toBe(false);
    expect(isTraceEvent({ ...event, attributes: { "coderails.start_time.basis": "unavailable" } })).toBe(false);
    expect(isTraceEvent({ ...event, attributes: { ...event.attributes, "coderails.start_time.basis": "source" } })).toBe(false);
    expect(isTraceEvent({ ...event, startTimeUnixNano: "1727524800000000000" })).toBe(false);
    expect(isTraceEvent({ ...event, endTimeUnixNano: "1727524800000000000" })).toBe(false);
    expect(isTraceEvent({ ...event, startTimeUnixNano: "1727524800000000000",
      attributes: { ...event.attributes, "coderails.start_time.basis": "derived" } })).toBe(false);
    expect(isTraceEvent({ ...event, startTimeUnixNano: "1727524800000000000",
      attributes: { ...event.attributes, "coderails.start_time.basis": "derived",
        "coderails.start_time.method": "record_correlation",
        "coderails.start_time.source_refs": JSON.stringify([sourceRef]) } })).toBe(true);
    expect(isTraceEvent({ ...event, events: [{ ...event.events[0], timeUnixNano: "1727524800000000000" }] })).toBe(false);
    expect(isTraceEvent({ ...event, events: [{ ...event.events[0], attributes: {} }] })).toBe(false);
    expect(() => serializeTraceEvent({ ...event, attributes: {} })).toThrow();
  });

  it("uses structured source references for derived start, end, and span event times", () => {
    const cases = [
      { prefix: "coderails.start_time", build: (attributes: Record<string, unknown>) => ({
        ...event, startTimeUnixNano: "1727524800000000000", attributes: { ...event.attributes, ...attributes } }) },
      { prefix: "coderails.end_time", build: (attributes: Record<string, unknown>) => ({
        ...event, endTimeUnixNano: "1727524800000000000", attributes: { ...event.attributes, ...attributes } }) },
      { prefix: "coderails.time", build: (attributes: Record<string, unknown>) => ({
        ...event, events: [{ ...event.events[0], timeUnixNano: "1727524800000000000", attributes }] }) },
    ];
    for (const { prefix, build } of cases) {
      const derived = { [`${prefix}.basis`]: "derived", [`${prefix}.method`]: "record_correlation",
        [`${prefix}.source_refs`]: JSON.stringify([sourceRef]) };
      expect(isTraceEvent(build(derived)), prefix).toBe(true);
      expect(isTraceEvent(build({ ...derived, [`${prefix}.source_refs`]: JSON.stringify([sourceRef.recordId]) })), prefix).toBe(false);
      expect(isTraceEvent(build({ ...derived, [`${prefix}.source_refs`]: JSON.stringify([{ ...sourceRef, ordinal: -1 }]) })), prefix).toBe(false);
      expect(isTraceEvent(build({ ...derived, [`${prefix}.source_refs`]: "not-json" })), prefix).toBe(false);
      expect(isTraceEvent(build({ ...derived, [`${prefix}.source_refs`]: "[]" })), prefix).toBe(false);
    }
  });

  it("rejects derivation metadata on source and unavailable timestamps", () => {
    for (const prefix of ["coderails.start_time", "coderails.end_time", "coderails.time"]) {
      for (const state of ["source", "unavailable"]) {
        const timestamp = state === "source" ? "1727524800000000000" : null;
        for (const stray of [
          { [`${prefix}.method`]: "record_correlation" },
          { [`${prefix}.source_refs`]: JSON.stringify([sourceRef]) },
        ]) {
          const attributes = { [`${prefix}.basis`]: state, ...stray };
          const candidate = prefix === "coderails.time"
            ? { ...event, events: [{ ...event.events[0], timeUnixNano: timestamp, attributes }] }
            : { ...event, [prefix === "coderails.start_time" ? "startTimeUnixNano" : "endTimeUnixNano"]: timestamp,
              attributes: { ...event.attributes, ...attributes } };
          expect(isTraceEvent(candidate), `${prefix} ${state}`).toBe(false);
        }
      }
    }
  });

  it("keeps cache, page, summary and requested detail contracts distinct", () => {
    const manifest: TraceManifest = {
      schemaVersion: 1, parserVersion: 1, provider: "codex", nativeSessionId: "native-1",
      loopId: null, sources: [{ sourceId: "parent", fingerprint: "sha256:abc", cursor: "7" }],
      generatedAt: "2026-09-28T12:00:00Z", complete: false, errors: ["missing child"], eventCount: 1,
      eventFile: "events." + "0".repeat(64) + ".jsonl",
    };
    const page: TracePage = { events: [event], inputCursor: null, nextCursor: null, complete: false };
    const summary: NativeSessionSummary = {
      nativeSessionId: "native-1", provider: "codex", projectLabel: "project", displayLabel: "session",
      lastActivity: { value: null, basis: "unavailable" },
    };
    const detail: TraceDetail = { sourceRef, provenance: event.provenance, content: "requested raw record" };
    const deps: TraceCollectionDeps = {
      sourceRoot: "/source", cacheRoot: "/cache", now: () => new Date("2026-09-28T12:00:00Z"),
      fs: { readFile: async () => "", writeFile: async () => undefined, stat: async () => null },
    };
    expect({ manifest, page, summary, detail, deps }.page.events).toHaveLength(1);
    expect(JSON.stringify({ manifest, page, summary })).not.toContain(detail.content);
  });
});
