// Line-oriented parsing for current `codex exec --json` output.
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

  flush(): string[] {
    const rest = this.buffer;
    this.buffer = "";
    return rest.trim() !== "" ? [rest] : [];
  }
}

export type ParsedStreamJsonLine =
  | { ok: true; value: Record<string, unknown> }
  | { ok: false; raw: string };

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

const MACHINERY_TYPES = new Set([
  "thread.started",
  "turn.started",
  "turn.completed",
  "turn.failed",
  "item.started",
  "item.updated",
  "item.completed",
]);

function agentMessage(value: Record<string, unknown>): string | undefined {
  if (value.type !== "item.completed" && value.type !== "item.updated") return undefined;
  const item = value.item as Record<string, unknown> | undefined;
  return item?.type === "agent_message" && typeof item.text === "string" ? item.text : undefined;
}

function isMachineryLine(line: string): boolean {
  const trimmed = line.trim();
  if (trimmed === "") return false;
  if (
    trimmed.startsWith("Reading additional input from stdin") ||
    trimmed.startsWith("Warning: no stdin data received")
  ) {
    return true;
  }
  const parsed = parseStreamJsonLine(trimmed);
  return parsed.ok && typeof parsed.value.type === "string" && MACHINERY_TYPES.has(parsed.value.type);
}

export function projectAssistantText(raw: string): string {
  const lines = raw.split("\n");
  let finalText: string | undefined;

  for (const line of lines) {
    if (line.trim() === "") continue;
    const parsed = parseStreamJsonLine(line);
    if (!parsed.ok) continue;
    const text = agentMessage(parsed.value);
    if (text?.trim()) finalText = text;
  }

  return finalText ?? lines.filter((line) => !isMachineryLine(line)).join("\n").trim();
}
