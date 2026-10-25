import { hash, obj, payload, type NativeSource, type Row } from "./codexTraceNative";
import type { TraceAttribute, TraceEvent } from "./traceSchema";

type Candidate = { event: TraceEvent; item: Row };
type Target = { kind: "skill" | "context"; id: string };
type Observation = "invocation" | "read" | "failed_read" | "mention" | "uncertain";
const targetPattern = /(?:[./A-Za-z0-9_-]+\/)*skills\/[a-z][a-z0-9-]{0,40}\/SKILL\.md|(?:[./A-Za-z0-9_-]+\/)*(?:AGENTS|CLAUDE)\.md/;

function text(value: unknown): string | null {
  if (typeof value === "string") return value;
  if (!Array.isArray(value)) return null;
  const parts = value.flatMap((entry) => {
    const block = obj(entry);
    return block && typeof block.text === "string" ? [block.text] : [];
  });
  return parts.length ? parts.join("") : null;
}

function args(value: unknown): Row | null {
  if (typeof value !== "string") return obj(value);
  try { return obj(JSON.parse(value)); } catch { return null; }
}

function observed(event: TraceEvent, kind: Observation, target: Target, body: string | null): void {
  const attrs: Record<string, TraceAttribute> = event.attributes;
  attrs["coderails.observation.kind"] = kind;
  attrs["coderails.observation.target_kind"] = target.kind;
  attrs["coderails.observation.target_sha256"] = hash(target.id);
  attrs["coderails.observation.bytes"] = body === null ? null : Buffer.byteLength(body, "utf8");
}

function target(value: unknown): Target | null {
  if (typeof value !== "string") return null;
  const path = value.trim().replace(/\\/g, "/");
  const skill = /(?:^|\/)skills\/([a-z][a-z0-9-]{0,40})\/SKILL\.md$/.exec(path);
  if (skill) return { kind: "skill", id: `skill:${skill[1]}` };
  const context = /(?:^|\/)(AGENTS\.md|CLAUDE\.md|progress\.json|evals\.json)$/.exec(path);
  return context ? { kind: "context", id: `context:${context[1]}` } : null;
}

function invokedSkill(value: unknown): Target | null {
  if (typeof value !== "string" || !/^[A-Za-z][A-Za-z0-9:_-]{0,79}$/.test(value)) return null;
  return { kind: "skill", id: `skill:${value.split(":").at(-1)!.toLowerCase()}` };
}

function isDirectRead(name: unknown): boolean {
  return name === "read_file" || name === "read_mcp_resource" || name === "Read";
}

function resultKind(item: Row): Observation {
  if (item.is_error === true || item.status === "error" || item.status === "failed") return "failed_read";
  if (item.is_error === false || item.status === "success" || item.status === "completed") return "read";
  return "uncertain";
}

export function observeCodexSource(src: NativeSource, events: TraceEvent[]): void {
  const byOrdinal = new Map(events.filter((event) => event.provenance.sourceId === src.id)
    .map((event) => [event.provenance.sourceOrdinal, event]));
  const requests = new Map<string, Candidate[]>();
  const results = new Map<string, Candidate[]>();
  src.rows.forEach((row, index) => {
    const event = byOrdinal.get(src.ordinals[index]);
    if (!event) return;
    const item = payload(row);
    const sessionId = event.provenance.nativeSessionId;
    if ((typeof row.session_id === "string" && row.session_id !== sessionId) ||
      (typeof item.session_id === "string" && item.session_id !== sessionId)) return;
    if (row.type === "response_item" && item.type === "function_call" && typeof item.call_id === "string") {
      requests.set(item.call_id, [...(requests.get(item.call_id) ?? []), { event, item }]);
      const parsed = args(item.arguments);
      const skill = item.name === "skill" || item.name === "Skill" ? invokedSkill(parsed?.skill ?? parsed?.name) : null;
      if (skill) observed(event, "invocation", skill,
        typeof item.arguments === "string" ? item.arguments : null);
      else if (!isDirectRead(item.name) && typeof item.arguments === "string") {
        const mention = targetPattern.exec(item.arguments)?.[0];
        const itemTarget = target(mention);
        if (itemTarget) observed(event, "uncertain", itemTarget, item.arguments);
      }
    } else if (row.type === "response_item" && item.type === "function_call_output" && typeof item.call_id === "string") {
      results.set(item.call_id, [...(results.get(item.call_id) ?? []), { event, item }]);
    } else if (row.type === "response_item" && item.type === "message") {
      const body = text(item.content);
      const mention = body && targetPattern.exec(body)?.[0];
      const itemTarget = target(mention);
      if (itemTarget) observed(event, "mention", itemTarget, body);
    }
  });
  for (const [callId, calls] of requests) {
    const outputs = results.get(callId) ?? [];
    for (const call of calls) {
      if (!isDirectRead(call.item.name)) continue;
      const input = args(call.item.arguments);
      const path = target(input?.path ?? input?.uri);
      if (!path) continue;
      if (calls.length !== 1 || outputs.length !== 1 ||
        outputs[0].event.provenance.sourceOrdinal <= call.event.provenance.sourceOrdinal) {
        observed(call.event, "uncertain", path,
          typeof call.item.arguments === "string" ? call.item.arguments : null);
        continue;
      }
      const output = outputs[0];
      const body = text(output.item.output ?? output.item.content);
      const result = resultKind(output.item);
      observed(output.event, result === "read" && body === null ? "uncertain" : result, path, body);
    }
  }
}
