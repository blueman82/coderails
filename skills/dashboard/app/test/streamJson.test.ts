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

// Helper: builds a text_delta stream_event line for a given index/text — the shape
// projectAssistantText concatenates for live-streaming (no final result line yet).
function deltaLine(index: number, text: string): string {
  return JSON.stringify({
    type: "stream_event",
    event: { type: "content_block_delta", index, delta: { type: "text_delta", text } },
  });
}

function resultLine(result: string): string {
  return JSON.stringify({ type: "result", subtype: "success", is_error: false, result });
}

describe("projectAssistantText", () => {
  it("concatenates text_delta events into prose when no final result line exists yet (live streaming)", () => {
    const raw = [deltaLine(0, "This"), deltaLine(0, " is"), deltaLine(0, " streaming.")].join("\n") + "\n";
    expect(projectAssistantText(raw)).toBe("This is streaming.");
  });

  it("prefers the final result line's `result` field over concatenated deltas when both exist", () => {
    const raw =
      [deltaLine(0, "draft"), deltaLine(0, " text"), resultLine("The real final answer.")].join("\n") + "\n";
    expect(projectAssistantText(raw)).toBe("The real final answer.");
  });

  it("uses the result field even across multiple assistant turns (num_turns > 1) rather than concatenating every turn's deltas", () => {
    // Turn 1 deltas + turn 2 deltas, but only ONE coherent final result line — mirrors the
    // ca01962c69681a03.log fixture (num_turns:2, one result line carrying the full answer).
    const raw =
      [
        deltaLine(0, "turn one partial"),
        JSON.stringify({ type: "assistant", message: { content: [] } }),
        deltaLine(0, "turn two partial"),
        resultLine("Final coherent answer covering both turns."),
      ].join("\n") + "\n";
    expect(projectAssistantText(raw)).toBe("Final coherent answer covering both turns.");
  });

  it("skips malformed/unparseable lines interleaved with valid delta lines rather than throwing or corrupting output", () => {
    const raw = [deltaLine(0, "Hello"), "not json at all", deltaLine(0, " world"), "{truncated"].join("\n") + "\n";
    expect(() => projectAssistantText(raw)).not.toThrow();
    expect(projectAssistantText(raw)).toBe("Hello world");
  });

  it("handles an incomplete/partial trailing line (no newline yet) without throwing or losing prior text", () => {
    const raw = deltaLine(0, "Complete line") + "\n" + '{"type":"stream_event","event":{"type":"content_block_delta"';
    expect(() => projectAssistantText(raw)).not.toThrow();
    expect(projectAssistantText(raw)).toBe("Complete line");
  });

  it("returns the raw input unchanged when nothing parses as assistant text (never shows an empty box for a run that produced output)", () => {
    const raw = [JSON.stringify({ type: "system", subtype: "init" }), "some raw unparseable garbage"].join("\n") + "\n";
    expect(projectAssistantText(raw)).toBe(raw);
  });

  it("returns the raw input unchanged for a completely empty string", () => {
    expect(projectAssistantText("")).toBe("");
  });

  it("ignores non-text_delta stream_event deltas (e.g. input_json_delta from tool-use blocks)", () => {
    const toolDelta = JSON.stringify({
      type: "stream_event",
      event: { type: "content_block_delta", index: 0, delta: { type: "input_json_delta", partial_json: "{\"x\":1}" } },
    });
    const raw = [deltaLine(0, "Hello "), toolDelta, deltaLine(0, "world")].join("\n") + "\n";
    expect(projectAssistantText(raw)).toBe("Hello world");
  });
});
