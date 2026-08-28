const credentialName = "(?:(?:access|refresh)[_-]?token|client[_-]?secret|api[_-]?key|token|secret|password)";
const maskedCredential = "[credential masked]";
const credentialKey = new RegExp(`^${credentialName}$`, "i");

export function maskText(value) {
  const text = typeof value === "string" ? value : JSON.stringify(value);
  const payload = text
    .replace(new RegExp(`(["']?\\b${credentialName}\\b["']?\\s*:\\s*")(.*?)(")`, "gi"), `$1${maskedCredential}$3`)
    .replace(new RegExp(`(["']?\\b${credentialName}\\b["']?\\s*:\\s*')(.*?)(')`, "gi"), `$1${maskedCredential}$3`)
    .replace(new RegExp(`(\\b${credentialName}\\b\\s*[=:]\\s*)([^\\s,}\\]]+)`, "gi"), `$1${maskedCredential}`)
    .replace(/(\bAuthorization\s*:\s*Bearer\s+)\S+/gi, `$1${maskedCredential}`);
  return { payload, redacted: payload !== text };
}

export function maskValue(value) {
  if (typeof value === "string") return maskText(value).payload;
  if (Array.isArray(value)) return value.map(maskValue);
  if (value && typeof value === "object") {
    const masked = Object.fromEntries(Object.entries(value).map(([key, item]) => [key, credentialKey.test(key) ? maskedCredential : maskValue(item)]));
    if (typeof value.name === "string" && credentialKey.test(value.name) && "value" in masked) masked.value = maskedCredential;
    return masked;
  }
  return value;
}

export function safeEvidence({ runId, order, type, source, timestamp, nodeId, payload }) {
  if (!runId || !Number.isInteger(order) || !type || !source || !timestamp) throw new Error("invalid evidence record");
  const masked = maskText(payload);
  return {
    runId, order, type, source, timestamp,
    ...(nodeId ? { nodeId } : {}),
    redacted: masked.redacted,
    payload: masked.payload,
  };
}
