import { describe, it, expect } from "vitest";
import { StreamJsonSplitter, parseStreamJsonLine, projectAssistantText } from "../src/lib/streamJson";

describe("StreamJsonSplitter", () => {
  it("splits a single chunk containing multiple complete JSONL lines into separate raw lines", () => {
    const splitter = new StreamJsonSplitter();
    const lines = splitter.push('{"type":"a"}\n{"type":"b"}\n');
    expect(lines).toEqual(['{"type":"a"}', '{"type":"b"}']);
  });

  it("buffers a partial trailing line across pushes rather than emitting it early", () => {
    const splitter = new StreamJsonSplitter();
    const first = splitter.push('{"type":"a"}\n{"type":"parti');
    expect(first).toEqual(['{"type":"a"}']);
    const second = splitter.push('al":true}\n');
    expect(second).toEqual(['{"type":"partial":true}']);
  });

  it("handles a chunk boundary landing exactly on a newline", () => {
    const splitter = new StreamJsonSplitter();
    const first = splitter.push('{"type":"a"}\n');
    const second = splitter.push('{"type":"b"}\n');
    expect(first).toEqual(['{"type":"a"}']);
    expect(second).toEqual(['{"type":"b"}']);
  });

  it("skips blank lines without emitting them", () => {
    const splitter = new StreamJsonSplitter();
    const lines = splitter.push('{"type":"a"}\n\n{"type":"b"}\n');
    expect(lines).toEqual(['{"type":"a"}', '{"type":"b"}']);
  });

  it("flush() returns and clears any incomplete trailing buffered content (e.g. on process exit with no final newline)", () => {
    const splitter = new StreamJsonSplitter();
    splitter.push('{"type":"a"}\n{"type":"no-newline-yet"');
    const flushed = splitter.flush();
    expect(flushed).toEqual(['{"type":"no-newline-yet"']);
    // a second flush with nothing left returns empty, not the same content again
    expect(splitter.flush()).toEqual([]);
  });
});

describe("parseStreamJsonLine", () => {
  it("parses a well-formed JSON line into its object form, tagged ok:true", () => {
    const result = parseStreamJsonLine('{"type":"assistant","uuid":"abc"}');
    expect(result).toEqual({ ok: true, value: { type: "assistant", uuid: "abc" } });
  });

  it("never throws on a malformed line — returns ok:false with the raw line preserved", () => {
    expect(() => parseStreamJsonLine("not json at all")).not.toThrow();
    const result = parseStreamJsonLine("not json at all");
    expect(result).toEqual({ ok: false, raw: "not json at all" });
  });

  it("never throws on a truncated/partial JSON line", () => {
    expect(() => parseStreamJsonLine('{"type":"assistant","incomplete')).not.toThrow();
    const result = parseStreamJsonLine('{"type":"assistant","incomplete');
    expect(result.ok).toBe(false);
  });

  it("treats a valid JSON line that parses to a non-object (e.g. a bare number or string) as unrecognised rather than crashing downstream consumers expecting an object shape", () => {
    const result = parseStreamJsonLine("42");
    expect(result).toEqual({ ok: false, raw: "42" });
  });

  it("handles an arbitrary unrecognised event 'type' value gracefully — forward-compatible with stream-json event types not yet known to this parser", () => {
    const result = parseStreamJsonLine('{"type":"some_future_event_type","payload":{"nested":true}}');
    expect(result).toEqual({
      ok: true,
      value: { type: "some_future_event_type", payload: { nested: true } },
    });
  });
});
