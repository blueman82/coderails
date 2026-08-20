export type IntentSource = "web" | "obsidian" | "cli" | string;

export interface Intent {
  button: string;
  input?: string;
  requestedAt: number; // epoch-ms — matches obsidian/src/exec.ts's IntentFile.requestedAt
  source: IntentSource;
}

export class IntentValidationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "IntentValidationError";
  }
}

export function parseIntent(raw: unknown): Intent {
  if (typeof raw !== "object" || raw === null) {
    throw new IntentValidationError("Intent must be a JSON object");
  }
  const obj = raw as Record<string, unknown>;

  if (typeof obj.button !== "string") {
    throw new IntentValidationError("Intent.button must be a string");
  }
  if (typeof obj.requestedAt !== "number" || !Number.isFinite(obj.requestedAt)) {
    throw new IntentValidationError("Intent.requestedAt must be an epoch-ms number");
  }
  if (typeof obj.source !== "string") {
    throw new IntentValidationError("Intent.source must be a string");
  }
  if (obj.input !== undefined && typeof obj.input !== "string") {
    throw new IntentValidationError("Intent.input must be a string when present");
  }

  const intent: Intent = {
    button: obj.button,
    requestedAt: obj.requestedAt,
    source: obj.source,
  };
  if (obj.input !== undefined) intent.input = obj.input as string;
  return intent;
}
