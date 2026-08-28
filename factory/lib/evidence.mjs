function redact(value) {
  if (Array.isArray(value)) return value.map(redact);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, redact(item)]));
  return "[redacted]";
}

export function safeEvidence({ runId, order, type, source, timestamp, nodeId, payload }) {
  if (!runId || !Number.isInteger(order) || !type || !source || !timestamp) throw new Error("invalid evidence record");
  return {
    runId, order, type, source, timestamp,
    ...(nodeId ? { nodeId } : {}),
    redacted: true,
    payload: redact(payload),
  };
}
