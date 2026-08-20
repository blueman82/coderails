import { describe, expect, it } from "vitest";
import { StreamJsonSplitter, parseStreamJsonLine, projectAssistantText } from "../src/lib/streamJson";

describe("StreamJsonSplitter", () => {
  it("splits complete JSONL lines and buffers a partial line", () => {
    const splitter = new StreamJsonSplitter();
    expect(splitter.push('{"type":"thread.started"}\n{"type":"turn')).toEqual([
      '{"type":"thread.started"}',
    ]);
    expect(splitter.push('.started"}\n')).toEqual(['{"type":"turn.started"}']);
  });

  it("flushes an unterminated final line once", () => {
    const splitter = new StreamJsonSplitter();
    splitter.push('{"type":"turn.completed"}');
    expect(splitter.flush()).toEqual(['{"type":"turn.completed"}']);
    expect(splitter.flush()).toEqual([]);
  });
});

describe("parseStreamJsonLine", () => {
  it("parses object events", () => {
    expect(parseStreamJsonLine('{"type":"thread.started"}')).toEqual({
      ok: true,
      value: { type: "thread.started" },
    });
  });

  it("preserves malformed or non-object lines without throwing", () => {
    expect(parseStreamJsonLine("not json")).toEqual({ ok: false, raw: "not json" });
    expect(parseStreamJsonLine("42")).toEqual({ ok: false, raw: "42" });
  });
});

function message(text: string): string {
  return JSON.stringify({
    type: "item.completed",
    item: { id: "item_0", type: "agent_message", text },
  });
}

describe("projectAssistantText", () => {
  it("extracts the current Codex agent_message event", () => {
    const raw = [
      '{"type":"thread.started","thread_id":"t1"}',
      '{"type":"turn.started"}',
      message("PONG"),
      '{"type":"turn.completed","usage":{}}',
    ].join("\n");
    expect(projectAssistantText(raw)).toBe("PONG");
  });

  it("uses the last completed agent message", () => {
    expect(projectAssistantText([message("draft"), message("final")].join("\n"))).toBe("final");
  });

  it("hides Codex machinery and stdin notices before any answer", () => {
    const raw = [
      "Reading additional input from stdin...",
      '{"type":"thread.started","thread_id":"t1"}',
      '{"type":"turn.started"}',
      '{"type":"item.started","item":{"type":"reasoning"}}',
    ].join("\n");
    expect(projectAssistantText(raw)).toBe("");
  });

  it("keeps an unrecognised crash line visible", () => {
    expect(projectAssistantText("FATAL: runner failed\n")).toBe("FATAL: runner failed");
    expect(projectAssistantText('{"error":"OOM killed","code":137}\n')).toContain("OOM killed");
  });
});
