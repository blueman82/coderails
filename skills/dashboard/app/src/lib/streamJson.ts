// Line-oriented parsing for `claude -p --output-format stream-json`
// output. A real probe of this exact invocation (2026-07-07, this machine)
// observed 19+ distinct `type` values across ~90 JSONL lines in a single
// short run (system/hook/assistant/user/etc), and the CLI gives no schema
// guarantee that this parser has seen every type it will ever emit. Both
// pieces here are deliberately non-throwing: a malformed or unrecognised
// line must never crash the run that's streaming it.

// Splits a byte/text stream that arrives in arbitrary chunk boundaries into
// complete, newline-terminated JSONL lines, buffering any incomplete
// trailing line across calls to push(). Blank lines are dropped.
export class StreamJsonSplitter {
  private buffer = "";

  push(chunk: string): string[] {
    this.buffer += chunk;
    const lines: string[] = [];
    let idx: number;
    while ((idx = this.buffer.indexOf("\n")) !== -1) {
      const line = this.buffer.slice(0, idx);
      this.buffer = this.buffer.slice(idx + 1);
      if (line.trim() !== "") lines.push(line);
    }
    return lines;
  }

  // Returns and clears whatever incomplete content remains buffered (no
  // trailing newline yet) — call on process exit so a final unterminated
  // line isn't silently dropped.
  flush(): string[] {
    const rest = this.buffer;
    this.buffer = "";
    return rest.trim() !== "" ? [rest] : [];
  }
}

export type ParsedStreamJsonLine = { ok: true; value: Record<string, unknown> } | { ok: false; raw: string };

// Parses one JSONL line. Never throws: a malformed line, or a line that
// parses to valid JSON but isn't an object (e.g. a bare number), both come
// back as `{ ok: false, raw }` rather than propagating a SyntaxError or a
// shape downstream consumers can't rely on. An unrecognised-but-well-formed
// `type` is passed through as `ok: true` — this parser deliberately does not
// maintain an allowlist of known event types, so it stays forward-compatible
// with new stream-json event types the CLI adds later.
export function parseStreamJsonLine(line: string): ParsedStreamJsonLine {
  try {
    const value: unknown = JSON.parse(line);
    if (value !== null && typeof value === "object" && !Array.isArray(value)) {
      return { ok: true, value: value as Record<string, unknown> };
    }
    return { ok: false, raw: line };
  } catch {
    return { ok: false, raw: line };
  }
}

// Projects the raw stream-json log into just the assistant's readable prose, for the dashboard's
// "clean" default view (see OutputViewerPanel.tsx). Non-throwing, same posture as
// parseStreamJsonLine: malformed or partial lines are skipped rather than raised. Prefers the
// final `{"type":"result",...,"result":"<text>"}` line's `result` field — even across multiple
// assistant turns (e.g. a hook-block forcing extra turns) there is exactly one such line, and it
// already carries the single coherent final answer, so concatenating every turn's deltas would
// duplicate/garble content rather than clarify it. Falls back to concatenating `text_delta` values
// for a still-live run (deltas exist, no `result` line yet). If nothing parses as assistant text at
// all, returns the raw input unchanged so a run that produced output never renders an empty box.
export function projectAssistantText(raw: string): string {
  const lines = raw.split("\n");
  let resultText: string | undefined;
  let deltaText = "";

  for (const line of lines) {
    if (line.trim() === "") continue;
    const parsed = parseStreamJsonLine(line);
    if (!parsed.ok) continue;
    const value = parsed.value;

    if (value.type === "result" && typeof value.result === "string" && value.result.trim() !== "") {
      resultText = value.result;
      continue;
    }

    if (value.type === "stream_event") {
      const event = value.event as Record<string, unknown> | undefined;
      if (event?.type === "content_block_delta") {
        const delta = event.delta as Record<string, unknown> | undefined;
        if (delta?.type === "text_delta" && typeof delta.text === "string") {
          deltaText += delta.text;
        }
      }
    }
  }

  if (resultText !== undefined) return resultText;
  if (deltaText !== "") return deltaText;
  return raw;
}
