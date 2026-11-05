import { createHash } from "node:crypto";
import type { TraceEvent } from "./sessionTraceSchema";
import { obj, type NativeRecord } from "./sessionTraceClaudeHelpers";

type Target = { kind: "skill" | "context"; id: string };
type Observation = "invocation" | "read" | "failed_read" | "mention" | "uncertain";

function digest(value: string): string {
  return createHash("sha256").update(value).digest("hex");
}

function target(path: unknown): Target | null {
  if (typeof path !== "string") return null;
  const normalized = path.replace(/\\/g, "/");
  const skill = /(?:^|\/)skills\/([a-z][a-z0-9-]{0,40})\/SKILL\.md$/.exec(normalized);
  if (skill) return { kind: "skill", id: `skill:${skill[1]}` };
  const context = /(?:^|\/)(AGENTS\.md|CLAUDE\.md|progress\.json|evals\.json)$/.exec(normalized);
  return context ? { kind: "context", id: `context:${context[1]}` } : null;
}

function mark(event: TraceEvent, kind: Observation, item: Target, bytes: number | null): void {
  event.attributes["coderails.observation.kind"] = kind;
  event.attributes["coderails.observation.target_kind"] = item.kind;
  event.attributes["coderails.observation.target_sha256"] = digest(item.id);
  event.attributes["coderails.observation.bytes"] = bytes;
}

function textFields(value: unknown): string[] {
  if (typeof value === "string") return [value];
  if (!Array.isArray(value)) return [];
  return value.flatMap((item) => {
    const part = obj(item);
    return part?.type === "text" && typeof part.text === "string" ? [part.text] : [];
  });
}

export function readTarget(block: NativeRecord): Target | null {
  if (block.type !== "tool_use" || block.name !== "Read") return null;
  const input = obj(block.input);
  return target(input?.file_path ?? input?.path);
}

export function markClaudeRequestOrMention(event: TraceEvent, row: NativeRecord,
  block: NativeRecord | null): void {
  if (block?.type === "tool_use" && block.name === "Skill") {
    const skill = obj(block.input)?.skill;
    if (typeof skill === "string" && /^[A-Za-z][A-Za-z0-9:_-]{0,79}$/.test(skill)) {
      mark(event, "invocation", { kind: "skill", id: `skill:${skill.split(":").at(-1)!.toLowerCase()}` },
        Buffer.byteLength(skill, "utf8"));
    }
    return;
  }
  if (block !== null || (row.type !== "assistant" && row.type !== "user")) return;
  for (const text of textFields(obj(row.message)?.content)) {
    const mention = /(?:^|[\s`])((?:[^\s`]+\/)?skills\/[a-z][a-z0-9-]{0,40}\/SKILL\.md|AGENTS\.md|CLAUDE\.md)(?=$|[\s`,.;:])/i.exec(text);
    const item = mention ? target(mention[1]) : null;
    if (item) {
      mark(event, "mention", item, Buffer.byteLength(text, "utf8"));
      return;
    }
  }
}

function markClaudeRead(request: TraceEvent, result: TraceEvent | null,
  requestBlock: NativeRecord, resultBlock: NativeRecord | null): void {
  const item = readTarget(requestBlock);
  if (!item) return;
  if (!result || !resultBlock) { mark(request, "uncertain", item, null); return; }
  const fields = textFields(resultBlock.content);
  const bytes = fields.length ? Buffer.byteLength(fields.join(""), "utf8") : null;
  const validSuccess = resultBlock.is_error === undefined || resultBlock.is_error === false;
  const kind = resultBlock.is_error === true ? "failed_read" :
    !validSuccess || bytes === null || item.kind === "skill" ? "uncertain" : "read";
  mark(result, kind, item, bytes);
}

export function markClaudeReadPairs(inputs: Map<string, NativeRecord[]>,
  outputs: Map<string, NativeRecord[]>, requests: Map<string, TraceEvent[]>,
  results: Map<string, TraceEvent[]>, errors: string[]): void {
  for (const [callId, blocks] of inputs) {
    const uses = requests.get(callId) ?? [];
    const returns = results.get(callId) ?? [];
    const values = outputs.get(callId) ?? [];
    if (blocks.length !== 1 || uses.length !== 1) {
      errors.push(`ambiguous read call ${callId}`);
      continue;
    }
    const valid = returns.length === 1 && values.length === 1 &&
      returns[0].provenance.sourceOrdinal > uses[0].provenance.sourceOrdinal;
    if (returns.length === 1 && !valid) errors.push(`out-of-order read result ${callId}`);
    markClaudeRead(uses[0], valid ? returns[0] : null, blocks[0], valid ? values[0] : null);
  }
}
