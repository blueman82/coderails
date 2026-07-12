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

// The stream-json event `type` values that are CLI machinery, NOT the
// assistant's readable output: control/transcript envelopes the `claude -p`
// stream emits around the actual prose.
const MACHINERY_TYPES = new Set(["system", "stream_event", "result", "assistant", "user"]);

// A raw log line is "recognised stream-json machinery" — i.e. NOT the
// assistant's readable output — if it is the plain-text stdin warning the
// `claude -p` CLI prints to stderr, or a parseable stream-json line whose
// `type` is one of MACHINERY_TYPES:
//   - `system` (init / hook_started / hook_response / hook_stop — in a cwd with
//     a SessionStart hook, hook_response carries the entire injected skill blob),
//   - `stream_event` (message_start / message_stop / content_block_start/stop /
//     *_delta — raw JSON envelopes, never prose),
//   - `result`, and `assistant`/`user` transcript lines.
// The fallback strips these so the clean view shows only genuinely-unrecognised
// remainder — which is where a crashed run's real error text lives, so a true
// failure is never blanked. Deliberately matched on KNOWN `type` values rather
// than "any JSON-shaped line": a crash/error payload that happens to be a JSON
// object WITHOUT a machinery `type` (e.g. `{"error":"OOM killed","code":137}`
// dumped by a wrapper) is NOT machinery — it survives the strip and stays
// visible, so a JSON-shaped failure is never silently reduced to "no output".
function isRecognisedMachineryLine(line: string): boolean {
  const trimmed = line.trim();
  if (trimmed === "") return false;
  // The CLI's stderr stdin-warning is plain text, not JSON — match its stable prefix.
  if (trimmed.startsWith("Warning: no stdin data received")) return true;
  const parsed = parseStreamJsonLine(trimmed);
  return parsed.ok && typeof parsed.value.type === "string" && MACHINERY_TYPES.has(parsed.value.type);
}

// Projects the raw stream-json log into just the assistant's readable prose, for the dashboard's
// "clean" default view (see OutputViewerPanel.tsx). Non-throwing, same posture as
// parseStreamJsonLine: malformed or partial lines are skipped rather than raised. Prefers the
// `{"type":"result",...,"result":"<text>"}` line's `result` field — normally there is one such
// line per run, and it carries the single coherent final answer, so concatenating every turn's
// deltas would duplicate/garble content rather than clarify it (even across multiple assistant
// turns, e.g. a hook-block forcing extra turns). If more than one result line were ever to appear,
// the last one wins rather than the first — still safer than concatenating deltas across turns.
// Falls back to concatenating `text_delta` values for a still-live run (deltas exist, no `result`
// line yet).
//
// Final fallback, when nothing parses as assistant text: return the raw input with the noise
// preamble (stdin warning + `system`/hook events) stripped — NOT the raw input verbatim. This is
// the fix for the live-streaming window, where a `claude -p` run emits the stdin warning and the
// SessionStart hook_started/hook_response events (the latter carrying the whole injected skill
// blob) BEFORE any assistant content: returning raw there dumped all of it into the clean view.
// A genuinely crashed run whose only output is an unrecognised error line still survives the strip
// (it is neither the warning nor a `system` event), so a real failure is never silently blanked.
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
  return lines.filter((line) => !isRecognisedMachineryLine(line)).join("\n").trim();
}
