import { describe, it, expect } from "vitest";
import { projectAssistantText } from "../src/lib/streamJson";

describe("edge probes (scratch, not part of PR)", () => {
  it("preserves a truncated trailing stream_event line in the fallback (not stripped as machinery, since it fails to parse)", () => {
    const raw =
      JSON.stringify({ type: "system", subtype: "init" }) +
      "\n" +
      '{"type":"stream_event","event":{"type":"content_block_delta"';
    const out = projectAssistantText(raw);
    expect(out).toContain("content_block_delta");
  });

  it("a valid assistant answer with JSON-looking prose text is NOT stripped when it arrives via a completed result line (fallback never fires)", () => {
    const raw =
      JSON.stringify({ type: "result", subtype: "success", is_error: false, result: '{"looks":"like json"}' }) + "\n";
    expect(projectAssistantText(raw)).toBe('{"looks":"like json"}');
  });

  it("documents behavior for a bare JSON-looking line with no recognised envelope type", () => {
    const raw = JSON.stringify({ foo: "bar", not_a_cli_event: true }) + "\n";
    const out = projectAssistantText(raw);
    console.log("RESULT:", JSON.stringify(out));
  });
});
