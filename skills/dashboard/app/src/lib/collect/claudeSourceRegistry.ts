import type { Source } from "./sessionTraceClaudeHelpers";
import type { TraceManifest } from "./sessionTraceSchema";

export function registeredClaudeSources(sources: Source[]): TraceManifest["sources"] {
  const registry = new Map<string, Source>();
  for (const source of sources) {
    const previous = registry.get(source.id);
    if (previous && (previous.fingerprint !== source.fingerprint || previous.cursor !== source.cursor))
      throw new Error("Native source changed during trace collection");
    if (!previous) registry.set(source.id, source);
  }
  return [...registry.values()].map((source) => ({
    sourceId: source.id, fingerprint: source.fingerprint, cursor: source.cursor,
  }));
}
