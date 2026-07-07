import { describe, it, expect } from "vitest";
import {
  parseIntent,
  IntentValidationError,
  ESCALATION_CHANNELS,
  ConfigError,
  loadConfig,
} from "../src/index";

// Proves the package.json "main": "src/index.ts" entrypoint actually
// resolves and re-exports the full public surface — WU2 (the runner) will
// be the first real consumer importing via this barrel rather than the
// individual src/intent.ts / src/config.ts modules.
describe("src/index.ts barrel", () => {
  it("re-exports parseIntent and IntentValidationError from ./intent", () => {
    const intent = parseIntent({ button: "wiki-lint", requestedAt: 1751835600000, source: "web" });
    expect(intent.button).toBe("wiki-lint");
    expect(() => parseIntent(null)).toThrow(IntentValidationError);
  });

  it("re-exports ESCALATION_CHANNELS, ConfigError, and loadConfig from ./config", () => {
    expect(ESCALATION_CHANNELS).toEqual(["notification", "vault-note"]);
    expect(() => loadConfig("/nonexistent/path/config.json")).toThrow(ConfigError);
  });
});
