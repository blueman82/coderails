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
    // Turn 1 deltas + turn 2 deltas, but only ONE coherent final result line — mirrors a real
    // two-turn stream-json run (num_turns:2, one result line carrying the full answer).
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

  it("never leaks the claude -p stdin warning or SessionStart hook preamble, even before any assistant text has streamed (live window)", () => {
    // Reproduces the real dashboard run-output noise: a `claude -p` run in a
    // cwd with a SessionStart hook emits, BEFORE any assistant content, a
    // plain-text stdin warning plus system/hook_started/hook_response events
    // (the hook_response carries the entire using-coderails skill blob as
    // additionalContext). During the live-streaming window there is no result
    // line and no text_delta yet, so the projection must NOT fall through to
    // dumping this preamble — it must render nothing (empty -> "no output")
    // until real assistant text arrives.
    const raw = [
      "Warning: no stdin data received in 3s, proceeding without it. If piping from a slow command, redirect stdin explicitly: < /dev/null to skip, or wait longer.",
      JSON.stringify({ type: "system", subtype: "hook_started", hook_name: "SessionStart:startup" }),
      JSON.stringify({ type: "system", subtype: "hook_response", hook_name: "SessionStart:startup", output: "<EXTREMELY_IMPORTANT> ...giant skill blob... </EXTREMELY_IMPORTANT>" }),
      JSON.stringify({ type: "system", subtype: "init", session_id: "abc" }),
    ].join("\n") + "\n";
    const out = projectAssistantText(raw);
    expect(out).not.toContain("no stdin data received");
    expect(out).not.toContain("hook_started");
    expect(out).not.toContain("hook_response");
    expect(out).not.toContain("EXTREMELY_IMPORTANT");
    expect(out).toBe("");
  });

  it("strips the noise preamble but still shows real assistant text that streams in after it", () => {
    const raw = [
      "Warning: no stdin data received in 3s, proceeding without it.",
      JSON.stringify({ type: "system", subtype: "hook_started", hook_name: "SessionStart:startup" }),
      deltaLine(0, "BANANA"),
    ].join("\n") + "\n";
    expect(projectAssistantText(raw)).toBe("BANANA");
  });

  it("strips non-text stream_event envelopes (message_start/stop, content_block_start) from the live-window fallback, showing nothing rather than raw JSON", () => {
    // The real live-streaming window before any text_delta: message_start plus
    // content_block_start arrive as stream_event envelopes that are NOT prose.
    // The fallback must not dump these as raw JSON into the clean view.
    const raw = [
      JSON.stringify({ type: "stream_event", event: { type: "message_start", message: { model: "claude-x" } } }),
      JSON.stringify({ type: "stream_event", event: { type: "content_block_start", index: 0 } }),
    ].join("\n") + "\n";
    const out = projectAssistantText(raw);
    expect(out).not.toContain("message_start");
    expect(out).not.toContain("content_block_start");
    expect(out).toBe("");
  });

  it("returns a non-hook, non-warning raw remainder when a crashed run produced only unrecognised output (preserves genuine error visibility)", () => {
    // A genuinely crashed run whose only output is an unrecognised error line —
    // NOT hook/warning noise — should still be shown rather than blanked.
    const raw = "FATAL: the runner exploded before streaming anything\n";
    expect(projectAssistantText(raw)).toBe("FATAL: the runner exploded before streaming anything");
  });

  it("returns empty for a completely empty string", () => {
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

  it("falls back to accumulated deltas when the result line's `result` field is empty/whitespace-only, rather than blanking a run that had streamed output", () => {
    const raw = [deltaLine(0, "Hello"), deltaLine(0, " world"), resultLine("")].join("\n") + "\n";
    expect(projectAssistantText(raw)).toBe("Hello world");
  });
});
